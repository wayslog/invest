"""Parquet 快照到 Qlib 原生缓存与因子表；串行隔离 Qlib 全局状态。"""

import ast
import re
import shutil
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock

from invest.contracts import FACTOR_SCHEMA, DataSnapshot, FactorFrame
from invest.research_data import digest, identity, load_snapshot

FIELDS = ("open", "high", "low", "close", "volume")
CONVERTER_VERSION = "invest_qlib_cache_v1"
_LOCK = threading.RLock()
_ROLLING = frozenset(
    ("Mean", "Std", "Sum", "Max", "Min", "Rank", "Slope", "Rsquare", "Resi", "IdxMax", "IdxMin")
)


@contextmanager
def _session(directory: Path) -> Iterator[None]:
    # Qlib 会修改全局配置和 NumPy 错误策略；本模块的调用串行，退出恢复 NumPy 策略。
    with _LOCK, np.errstate():
        import qlib

        qlib.init(
            provider_uri={"day": str(directory.resolve())},
            region="us",
            kernels=1,
            expression_cache=None,
            dataset_cache=None,
            clear_mem_cache=True,
            skip_if_reg=False,
            logging_level=40,
            exp_manager={
                "class": "MLflowExpManager",
                "module_path": "qlib.workflow.expm",
                "kwargs": {
                    "uri": (directory.resolve() / "mlruns").as_uri(),
                    "default_exp_name": "research",
                },
            },
        )
        yield


def _verify_cache(directory: Path, expected: dict[str, str]) -> None:
    if pq.read_table(directory / "manifest.parquet").to_pylist() != [expected]:
        raise ValueError("Qlib cache manifest mismatch; rebuild only this derived cache")
    inventory = pq.read_table(directory / "files.parquet").to_pylist()
    names = {row["path"] for row in inventory}
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    if len(names) != len(inventory) or actual != names | {"files.parquet", "manifest.parquet"}:
        raise ValueError("Qlib cache inventory mismatch")
    for row in inventory:
        path = directory / row["path"]
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(directory.resolve())
            or digest(path) != row["sha256"]
        ):
            raise ValueError("Qlib cache data changed; rebuild only this derived cache")


def build_qlib_cache(snapshot: DataSnapshot, cache_root: Path = Path("data/cache")) -> Path:
    """原生缓存可复用、可整目录删除重建；绝不清理输入快照或既有缓存。"""
    snapshot = load_snapshot(snapshot.directory, expected_id=snapshot.snapshot_id)
    record = {
        "snapshot_id": snapshot.snapshot_id,
        "converter_version": CONVERTER_VERSION,
        "qlib_version": version("pyqlib"),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "frequency": "day",
        "region": "us",
        "dtype": "float32",
        "fields": ",".join(FIELDS),
        "price_basis": snapshot.spec.price_basis,
        "volume_unit": snapshot.spec.volume_unit,
    }
    record["cache_id"] = identity(record)
    root = cache_root.resolve() / "qlib"
    directory = root / record["cache_id"]
    if root.is_relative_to(snapshot.directory) or snapshot.directory.is_relative_to(directory):
        raise ValueError("Cache and authoritative snapshot directories must be separate")
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(root / f".{record['cache_id']}.lock", timeout=60):
        if directory.exists():
            _verify_cache(directory, record)
            return directory
        staging = root / f".{record['cache_id']}.{uuid.uuid4().hex}.tmp"
        staging.mkdir()
        try:
            (staging / "calendars").mkdir()
            (staging / "instruments").mkdir()
            dates = snapshot.calendar["date"].to_pylist()
            # 仅第三方派生缓存采用文本日历和股票池；业务快照保持 Parquet。
            (staging / "calendars/day.txt").write_text("".join(f"{d.isoformat()}\n" for d in dates))
            (staging / "instruments/all.txt").write_text(
                "".join(
                    f"{r['instrument']}\t{r['start'].isoformat()}\t{r['end'].isoformat()}\n"
                    for r in snapshot.universe.to_pylist()
                )
            )
            bars = snapshot.bars.to_pandas()
            with _session(staging):
                from qlib.data.storage.file_storage import FileFeatureStorage

                for instrument, group in bars.groupby("instrument", sort=True):
                    (staging / "features" / str(instrument).lower()).mkdir(parents=True)
                    aligned = group.set_index("date").reindex(dates)
                    for field in FIELDS:
                        values = aligned[field].to_numpy(dtype=np.float32, na_value=np.nan)
                        if np.isinf(values).any():
                            raise ValueError("Research values exceed Qlib float32 capacity")
                        FileFeatureStorage(
                            str(instrument), field, "day", provider_uri={"day": str(staging)}
                        ).write(values, index=0)
            inventory = pa.Table.from_pylist(
                [
                    {"path": str(path.relative_to(staging)), "sha256": digest(path)}
                    for path in sorted(staging.rglob("*"))
                    if path.is_file()
                ],
                schema=pa.schema([("path", pa.string()), ("sha256", pa.string())]),
            )
            pq.write_table(inventory, staging / "files.parquet", compression="zstd")
            pq.write_table(
                pa.Table.from_pylist([record]), staging / "manifest.parquet", compression="zstd"
            )
            staging.rename(directory)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return directory


def _window(node: ast.AST) -> int:
    if isinstance(node, ast.Constant) and type(node.value) is int and 1 <= node.value <= 2520:
        return node.value
    raise ValueError("Only declared causal factor fields and operators are allowed")


def expression_lookback(expression: str) -> int:
    """只接收回看历史的白名单算子；未来 Ref、任意代码和未声明字段直接拒绝。

    返回所需的此前会话数：Ref(x,N) 回看 N，N 会话滚动窗口回看 N-1。
    """
    if len(expression) > 4096:
        raise ValueError("Factor expression is too long")
    try:
        tree = ast.parse(re.sub(r"\$([A-Za-z_][A-Za-z_0-9]*)", r"\1", expression), mode="eval")
    except SyntaxError as exc:
        raise ValueError("Invalid factor expression") from exc

    def visit(node: ast.AST) -> int:
        if isinstance(node, ast.Name) and node.id in FIELDS:
            return 0
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
            and np.isfinite(node.value)
        ):
            return 0
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            return max(visit(node.left), visit(node.right))
        # 单一比较得到 0/1 序列，如 Mean($close>Ref($close,1),N) 为 N 会话上涨占比。
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], (ast.Gt, ast.GtE, ast.Lt, ast.LtE))
        ):
            return max(visit(node.left), visit(node.comparators[0]))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name, args = node.func.id, node.args
            if name in {"Abs", "Log", "Sign"} and len(args) == 1:
                return visit(args[0])
            # Greater、Less 为逐会话的两序列较大、较小值，不是滚动算子。
            if name in {"Greater", "Less"} and len(args) == 2:
                return max(visit(args[0]), visit(args[1]))
            if name == "Ref" and len(args) == 2:
                return visit(args[0]) + _window(args[1])
            if name in {"Corr", "Cov"} and len(args) == 3:
                return max(visit(args[0]), visit(args[1])) + _window(args[2]) - 1
            if name == "Quantile" and len(args) == 3:
                level = args[2]
                if (
                    isinstance(level, ast.Constant)
                    and isinstance(level.value, (int, float))
                    and not isinstance(level.value, bool)
                    and 0 <= level.value <= 1
                ):
                    return visit(args[0]) + _window(args[1]) - 1
            # Rank 为本证券窗口内的时序分位；IdxMax/IdxMin 为窗口内极值位置（1 为最早）。
            if name in _ROLLING and len(args) == 2:
                return visit(args[0]) + _window(args[1]) - 1
        raise ValueError("Only declared causal factor fields and operators are allowed")

    return visit(tree.body)


def calculate_factors(
    snapshot: DataSnapshot,
    expressions: Mapping[str, str],
    cache_root: Path = Path("data/cache"),
    *,
    start: date | None = None,
    end: date | None = None,
) -> FactorFrame:
    if not expressions or any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in expressions):
        raise ValueError("At least one named factor expression is required")
    lookbacks = {name: expression_lookback(expr) for name, expr in expressions.items()}
    snapshot = load_snapshot(snapshot.directory, expected_id=snapshot.snapshot_id)
    dates = snapshot.calendar["date"].to_pylist()
    start, end = start or dates[0], end or dates[-1]
    if start not in dates or end not in dates or start > end:
        raise ValueError("Factor range must use ordered snapshot sessions")
    cache = build_qlib_cache(snapshot, cache_root)
    with _session(cache):
        from qlib.data import D

        frame = cast(
            pd.DataFrame,
            D.features(
                D.instruments("all"),
                list(expressions.values()),
                start_time=start.isoformat(),
                end_time=end.isoformat(),
                freq="day",
            ),
        )
        frame.columns = list(expressions)
        frame = frame.copy()
    indices = {day: index for index, day in enumerate(dates)}
    bars = {(r["date"], r["instrument"]): r for r in snapshot.bars.to_pylist()}
    members = snapshot.universe.to_pylist()
    rows = []
    for index, values in frame.iterrows():
        instrument, stamp = cast(tuple[str, pd.Timestamp], index)
        day = stamp.date()
        membership = next(
            r for r in members if r["instrument"] == instrument and r["start"] <= day <= r["end"]
        )
        for name, expression in expressions.items():
            first_index, last_index = indices[day] - lookbacks[name], indices[day]
            inputs = [
                bars.get((d, instrument)) for d in dates[max(0, first_index) : last_index + 1]
            ]
            complete = first_index >= 0 and all(r is not None for r in inputs)
            times = [
                membership["available_at"],
                *[r["available_at"] if r else None for r in inputs],
            ]
            available = max(times) if complete and all(t is not None for t in times) else None
            value = float(values[name])
            rows.append(
                {
                    "date": day,
                    "instrument": instrument,
                    "factor": name,
                    "expression": expression,
                    "value": value if complete and np.isfinite(value) else None,
                    "available_at": available,
                }
            )
    return FactorFrame(
        pa.Table.from_pylist(
            rows, schema=FACTOR_SCHEMA.with_metadata(snapshot.metadata(FACTOR_SCHEMA))
        )
    )
