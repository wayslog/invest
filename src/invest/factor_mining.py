"""有预算的因子候选搜索；开发反馈只使用训练和验证区间。"""

from __future__ import annotations

import ast
import hashlib
import json
import platform
import random
import re
import uuid
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as arrow_compute
import pyarrow.parquet as pq

from invest.contracts import (
    FACTOR_SCHEMA,
    LABEL_SCHEMA,
    SIGNAL_SCHEMA,
    TIME,
    UNIVERSE,
    DataSnapshot,
    FactorFrame,
    LabelFrame,
    research_schema,
)
from invest.engine import engine_digest, research_engine_digest
from invest.factor_diagnostics import (
    FactorDiagnostics,
    describe_factor,
    diagnose_factor,
    forward_labels,
    qlib_dataset_frame,
)
from invest.factor_statistics import corrected_ic_test
from invest.mining_config import MiningConfig, parse_mining_config
from invest.qlib_adapter import calculate_factors, expression_lookback
from invest.quality import regular_sessions
from invest.quant_report import write_quant_report
from invest.research_artifacts import freeze_engine, protect_inputs, seal_artifacts
from invest.research_data import (
    create_snapshot,
    identity,
    load_snapshot,
    validate_snapshot_tables,
)
from invest.signals import cross_sectional_ranks, freeze_factor_pool, generate_signals

pc: Any = arrow_compute

TRIAL_SCHEMA = research_schema(
    "mining_trials",
    [
        ("trial_id", pa.int32()),
        *[
            (name, pa.string())
            for name in (
                "factor",
                "family",
                "expression",
                "status",
                "reason",
                "error",
                "cost_status",
                "cost_reason",
            )
        ],
        ("depth", pa.int32()),
        ("nodes", pa.int32()),
        ("direction", pa.int8()),
        *[
            (name, pa.float64())
            for name in (
                "train_ic",
                "validation_ic",
                "train_coverage",
                "validation_coverage",
                "max_correlation",
                "incremental_ic",
                "pvalue",
                "adjusted_pvalue",
                "net_return",
                "stress_return",
                "net_excess",
                "cost_drawdown",
            )
        ],
        ("train_sessions", pa.int32()),
        ("validation_sessions", pa.int32()),
        ("test_blocks", pa.int32()),
        ("test_family_size", pa.int32()),
    ],
)
DIAGNOSTIC_SCHEMA = research_schema(
    "factor_diagnostics",
    [
        ("factor", pa.string()),
        ("segment", pa.string()),
        ("metric", pa.string()),
        ("date", pa.date32()),
        ("group", pa.string()),
        ("value", pa.float64()),
    ],
)
RUN_SCHEMA = research_schema(
    "mining_run",
    [
        *[
            (name, pa.string())
            for name in (
                "run_id",
                "status",
                "source_snapshot_id",
                "development_snapshot_id",
                "config_sha256",
                "engine_digest",
                "financial_digest",
                "versions",
                "holdout_status",
                "pool_id",
            )
        ],
        ("created_at", TIME),
        ("completed_at", TIME),
        ("known_through", pa.date32()),
        ("test_start", pa.date32()),
        ("test_end", pa.date32()),
        ("candidates", pa.int32()),
        ("selected", pa.int32()),
        ("account_eligible", pa.bool_()),
        ("limitations", pa.list_(pa.field("element", pa.string()))),
    ],
)


@dataclass(frozen=True)
class MiningResult:
    directory: Path
    run_id: str
    status: str
    pool_id: str
    candidates: int
    selected: int


@dataclass(frozen=True)
class Candidate:
    trial_id: int
    factor: str
    family: str
    expression: str
    depth: int
    nodes: int


def alpha158_expressions(windows: tuple[int, ...]) -> list[str]:
    """Qlib Alpha158 定义：K 线形态、当日开高低相对收盘及滚动价量统计。

    价格均为快照口径的同一价格基准；比值无单位，成交量相关项沿用快照成交量单位。
    快照不含 VWAP，因此不生成 VWAP0；顺序随 Qlib 版本固定，版本已登记。
    """
    from qlib.contrib.data.loader import Alpha158DL

    fields, _ = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW"]},
            "rolling": {"windows": sorted(windows)},
        }
    )
    return list(fields)


def generate_candidates(config: MiningConfig) -> list[Candidate]:
    templates = {
        "momentum": "$close/Ref($close,{w})-1",
        "reversal": "0-($close/Ref($close,{w})-1)",
        "volatility": "Std($close/Ref($close,1)-1,{w})",
        "volume_trend": "$volume/Mean($volume,{w})-1",
        "range_position": "($close-Min($low,{w}))/(Max($high,{w})-Min($low,{w}))",
        "price_volume": "Corr($close/Ref($close,1)-1,$volume/Mean($volume,{w}),{w})",
    }
    choices = []
    for family in config.families:
        expressions = (
            alpha158_expressions(config.windows)
            if family == "alpha158"
            else [templates[family].format(w=window) for window in sorted(config.windows)]
        )
        choices += [(family, expression) for expression in expressions]
    if len({expression for _, expression in choices}) != len(choices):
        raise ValueError("Candidate expressions must be unique")
    random.Random(config.seed).shuffle(choices)

    def depth(node: ast.AST) -> int:
        return 1 + max((depth(child) for child in ast.iter_child_nodes(node)), default=0)

    candidates = []
    for index, (family, expression) in enumerate(choices[: config.candidate_budget]):
        expression_lookback(expression)
        tree = ast.parse(re.sub(r"\$([a-z]+)", r"\1", expression), mode="eval")
        candidates.append(
            Candidate(
                index,
                "factor_" + identity({"expression": expression})[:16],
                family,
                expression,
                depth(tree),
                len(list(ast.walk(tree))),
            )
        )
    return candidates


def purge_segment(
    factors: FactorFrame,
    labels: LabelFrame,
    start: date,
    end: date,
    horizon: int,
    *,
    snapshot: DataSnapshot,
    allow_exploratory: bool = False,
) -> tuple[FactorFrame, LabelFrame, int]:
    """剔除跨段标签，并按本段末收盘时实际可得的入场、退出价格准入。"""
    if type(horizon) is not int or horizon < 1:
        raise ValueError("Label horizon must be a positive session count")
    snapshot = load_snapshot(snapshot.directory, expected_id=snapshot.snapshot_id)
    label_metadata = labels.table.schema.metadata or {}
    if any(
        label_metadata.get(key) != value for key, value in snapshot.metadata(LABEL_SCHEMA).items()
    ):
        raise ValueError("Label admission requires its original snapshot provenance")
    if snapshot.scope == "exploratory" and not allow_exploratory:
        raise ValueError("Exploratory labels require explicit opt-in")
    calendar = regular_sessions(start, end).to_pylist()
    eligible = pa.array([row["date"] for row in calendar[: -horizon - 1]], type=pa.date32())
    in_segment = pc.and_(
        pc.greater_equal(factors.table["date"], start), pc.less_equal(factors.table["date"], end)
    )
    admitted = factors.table.filter(pc.is_in(factors.table["date"], value_set=eligible))
    purged = factors.table.filter(in_segment).num_rows - admitted.num_rows
    selected = labels.table.filter(
        pc.and_(
            pc.is_in(labels.table["date"], value_set=eligible),
            pc.equal(labels.table["horizon"], horizon),
        )
    )
    if calendar:
        selected = selected.filter(
            pc.and_(
                pc.greater_equal(selected["entry_at"], calendar[0]["open_at"]),
                pc.less_equal(selected["exit_at"], calendar[-1]["close_at"]),
            )
        )
    prices = {(row["date"], row["instrument"]): row for row in snapshot.bars.to_pylist()}
    rows = selected.to_pylist()
    unknown_count, rejected_count = 0, 0
    for row in rows:
        available = [
            prices[row[key].date(), row["instrument"]]["available_at"]
            for key in ("entry_at", "exit_at")
        ]
        unknown = any(value is None for value in available)
        late = any(value is not None and value > calendar[-1]["close_at"] for value in available)
        if row["value"] is not None:
            unknown_count += int(unknown)
            if late or (unknown and not allow_exploratory):
                row["value"] = None
                rejected_count += 1
    metadata = {
        **label_metadata,
        b"input_scope": snapshot.scope.encode(),
        b"scope": b"exploratory"
        if allow_exploratory and unknown_count
        else snapshot.scope.encode(),
        b"label_timing_policy": b"segment_close_price_availability",
        b"label_available_by": calendar[-1]["close_at"].isoformat().encode() if calendar else b"",
        b"label_unknown_timing_rows": str(unknown_count).encode(),
        b"label_timing_rejected_rows": str(rejected_count).encode(),
    }
    return (
        FactorFrame(admitted),
        LabelFrame(pa.Table.from_pylist(rows, schema=selected.schema.with_metadata(metadata))),
        purged,
    )


def _sample_dates(start: date, end: date, horizon: int) -> pd.DatetimeIndex:
    # H 步标签之间不重叠，但这不代表样本在统计意义上独立。
    days = regular_sessions(start, end)["date"].to_pylist()[: -horizon - 1]
    return pd.DatetimeIndex(days[::horizon])


def _metric(
    rows: list[dict[str, Any]],
    factor: str,
    segment: str,
    metric: str,
    value: float,
    day: date | None = None,
    group: str = "all",
) -> None:
    rows.append(
        {
            "factor": factor,
            "segment": segment,
            "metric": metric,
            "date": day,
            "group": group,
            "value": float(value) if np.isfinite(value) else None,
        }
    )


def _diagnostic_rows(
    result: FactorDiagnostics,
    factor: str,
    segment: str,
    sampled: pd.DatetimeIndex,
    rows: list[dict[str, Any]],
) -> None:
    for day, value in result.rank_ic.iloc[:, 0].items():
        _metric(rows, factor, segment, "rank_ic", value, cast(pd.Timestamp, day).date())
    selected = result.rank_ic.reindex(sampled).iloc[:, 0].dropna()
    for year, value in selected.groupby(pd.DatetimeIndex(selected.index).year).mean().items():
        _metric(rows, factor, segment, "annual_rank_ic", value, group=str(year))
    for metric, frame in describe_factor(result).items():
        for index, values in frame.iterrows():
            for column, value in values.items():
                group, day = index if isinstance(index, tuple) else (column, index)
                _metric(rows, factor, segment, metric, value, day.date(), str(group))


def _evaluate(
    candidate: Candidate,
    factors: FactorFrame,
    labels: LabelFrame,
    snapshot: DataSnapshot,
    config: MiningConfig,
    trial: dict[str, Any],
    records: list[dict[str, Any]],
) -> tuple[pd.Series[Any], pd.Series[Any], pd.Series[Any]] | None:
    from alphalens.utils import MaxLossExceededError
    from scipy.stats import ConstantInputWarning  # type: ignore[import-untyped]

    views = {}
    validation_ic = pd.Series(dtype=float)
    failure = ""
    for segment, start, end in (
        ("train", config.train_start, config.train_end),
        ("validation", config.validation_start, config.validation_end),
    ):
        segment_factors, segment_labels, purged = purge_segment(
            factors,
            labels,
            start,
            end,
            config.horizon,
            snapshot=snapshot,
            allow_exploratory=config.allow_exploratory,
        )
        view = qlib_dataset_frame(
            segment_factors, segment_labels, allow_exploratory=config.allow_exploratory
        )
        views[segment] = view
        _metric(records, candidate.factor, segment, "boundary_purged_rows", purged)
        _metric(records, candidate.factor, segment, "input_rows", segment_factors.table.num_rows)
        for name in (
            "timing_rejected_rows",
            "unknown_timing_rows",
            "label_timing_rejected_rows",
            "label_unknown_timing_rows",
        ):
            _metric(records, candidate.factor, segment, name, view.attrs["invest"][name])
        try:
            # 恒定标签会使 IC 无定义，保留 NaN 并由有效会话数量门槛拒绝。
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConstantInputWarning)
                result = diagnose_factor(
                    segment_factors,
                    segment_labels,
                    candidate.factor,
                    quantiles=config.quantiles,
                    max_loss=1 - config.min_coverage,
                    allow_exploratory=config.allow_exploratory,
                )
            sampled = _sample_dates(start, end, config.horizon)
            ic = result.rank_ic.reindex(sampled).iloc[:, 0].dropna()
            if segment == "validation":
                validation_ic = result.rank_ic.reindex(sampled).iloc[:, 0]
            trial[f"{segment}_coverage"] = 1 - result.loss_fraction
            trial[f"{segment}_sessions"] = len(ic)
            trial[f"{segment}_ic"] = float(ic.mean()) if len(ic) else None
            _metric(records, candidate.factor, segment, "coverage", 1 - result.loss_fraction)
            _diagnostic_rows(result, candidate.factor, segment, sampled, records)
            if len(ic) < config.min_sessions:
                failure = "insufficient_evidence"
        except (ValueError, MaxLossExceededError) as exc:
            trial["error"] += f"{segment}: {exc}\n"
            failure = "insufficient_evidence"
    if failure:
        trial["reason"] = failure
        return None
    direction = 1 if trial["train_ic"] > 0 else -1
    trial["direction"] = direction
    family_size = config.test_family_size or config.candidate_budget
    pvalue, adjusted, blocks = corrected_ic_test(
        validation_ic,
        direction=direction,
        block_size=config.test_block_size,
        family_size=family_size,
        resamples=config.test_resamples,
        seed=config.seed,
    )
    trial.update(
        pvalue=pvalue, adjusted_pvalue=adjusted, test_blocks=blocks, test_family_size=family_size
    )
    if abs(trial["train_ic"]) < config.min_train_ic or trial["train_ic"] == 0:
        trial["reason"] = "weak_training_ic"
        return None
    if direction * trial["validation_ic"] < config.min_validation_ic:
        trial["reason"] = "weak_validation_ic"
        return None
    if adjusted > config.test_alpha:
        trial["reason"] = "multiple_testing_rejected"
        return None
    ranks = {
        segment: cross_sectional_ranks(cast(pd.DataFrame, view["feature"]))[candidate.factor]
        * direction
        for segment, view in views.items()
    }
    return (
        ranks["train"],
        ranks["validation"],
        views["validation"]["label"][f"return_{config.horizon}d"],
    )


def _incremental_ic(
    values: pd.DataFrame,
    labels: pd.Series[Any],
    config: MiningConfig,
) -> float | None:
    from alphalens.performance import factor_information_coefficient
    from scipy.stats import ConstantInputWarning

    complete = values.join(labels.rename("label")).dropna()
    if complete.empty:
        return None
    samples = _sample_dates(config.validation_start, config.validation_end, config.horizon)
    series = []
    # 对齐同一批完整横截面后比较旧组合与加入候选的组合，不能靠改变覆盖范围改善 IC。
    for width in (values.shape[1] - 1, values.shape[1]):
        if width == 0:
            series.append(pd.Series(0.0, index=samples))
            continue
        clean = pd.DataFrame(
            {
                "factor": complete.iloc[:, :width].mean(axis=1),
                f"{config.horizon}D": complete["label"],
            }
        )
        clean.index.names = ["date", "asset"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConstantInputWarning)
            ic = factor_information_coefficient(clean).iloc[:, 0].reindex(samples)
        series.append(ic)
    paired = pd.concat(series, axis=1).dropna()
    if len(paired) < config.min_sessions:
        return None
    return float((paired.iloc[:, 1] - paired.iloc[:, 0]).mean())


def _development_tables(source: DataSnapshot, config: MiningConfig) -> tuple[pa.Table, pa.Table]:
    members = [
        {**row, "end": min(row["end"], config.validation_end)}
        for row in source.universe.to_pylist()
        if row["start"] <= config.validation_end
    ]
    instruments = pa.array(sorted({row["instrument"] for row in members}), type=pa.string())
    bars = source.bars.filter(
        pc.and_(
            pc.less_equal(source.bars["date"], config.validation_end),
            pc.is_in(source.bars["instrument"], value_set=instruments),
        )
    )
    return bars, pa.Table.from_pylist(members, schema=UNIVERSE)


def _result_metadata(
    snapshot: DataSnapshot,
    schema: pa.Schema,
    run_id: str,
    scope: str,
) -> dict[bytes, bytes]:
    return {
        **snapshot.metadata(schema),
        b"run_id": run_id.encode(),
        b"scope": scope.encode(),
        b"input_scope": snapshot.scope.encode(),
        b"timing_policy": b"xnys_session_close",
        b"evidence_status": b"research_only",
    }


@contextmanager
def _record_trial(
    candidate: Candidate,
    directory: Path,
    metadata: dict[bytes, bytes],
) -> Iterator[dict[str, Any]]:
    trial: dict[str, Any] = {
        **asdict(candidate),
        "status": "rejected",
        "reason": "",
        "error": "",
        "cost_status": "not_evaluated",
    }
    try:
        yield trial
    except Exception as exc:
        trial.update(status="error", reason="execution_error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        # 异常也保留当前尝试；不把中断的实验登记成已完成，不覆盖已有分片。
        path = directory / f"trial_{candidate.trial_id:04d}.parquet"
        with path.open("xb") as stream:
            pq.write_table(
                pa.Table.from_pylist([trial], schema=TRIAL_SCHEMA.with_metadata(metadata)),
                stream,
                compression="zstd",
            )


def run_mining(
    config_path: Path,
    output: Path,
    *,
    cache_root: Path = Path("data/cache"),
) -> MiningResult:
    """冻结一次搜索预算并保存全部候选；测试区间只登记，不进入特征或标签计算。"""
    body = config_path.read_bytes()
    config = parse_mining_config(body, config_path.parent)
    source = load_snapshot(config.snapshot)
    bars, universe = _development_tables(source, config)
    _, limitations = validate_snapshot_tables(bars, universe, source.spec)
    if limitations and not config.allow_exploratory:
        raise ValueError("Exploratory input requires explicit opt-in")
    scope = (
        "exploratory"
        if limitations
        else "synthetic"
        if source.spec.source == "synthetic"
        else "research"
    )
    source_metadata = {
        b"source_scope": source.scope.encode(),
        b"source_limitations": json.dumps(list(source.limitations)).encode(),
    }
    days = set(source.calendar["date"].to_pylist())
    if any(
        day not in days
        for day in (
            config.train_start,
            config.train_end,
            config.validation_start,
            config.validation_end,
        )
    ):
        raise ValueError("Development boundaries must be completed sessions inside the snapshot")
    reserved = regular_sessions(config.test_start, config.test_end)["date"].to_pylist()
    if not reserved or reserved[0] != config.test_start or reserved[-1] != config.test_end:
        raise ValueError("Reserved test boundaries must be XNYS sessions")
    output = output.resolve()
    if output.is_relative_to(source.directory):
        raise ValueError("Mining output cannot modify its source snapshot")
    protected: tuple[Path, ...] = (source.directory,)
    if config.cost_screen:
        protected += tuple(config.cost_screen.execution.values())
    protect_inputs((output, cache_root), protected)
    protect_inputs((cache_root,), (output,))
    candidates = generate_candidates(config)
    run_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "run_id": run_id,
        "status": "registered",
        "source_snapshot_id": source.snapshot_id,
        "config_sha256": hashlib.sha256(body).hexdigest(),
        "engine_digest": engine_digest(),
        "financial_digest": research_engine_digest(),
        "versions": json.dumps(
            {
                "python": platform.python_version(),
                **{
                    name: version(name)
                    for name in (
                        "pyqlib",
                        "alphalens-reloaded",
                        "numpy",
                        "pandas",
                        "pyarrow",
                        "scipy",
                        "exchange-calendars",
                    )
                },
            },
            sort_keys=True,
        ),
        "holdout_status": "known_history_reserved"
        if config.known_through >= config.test_start
        else "reserved_unassessed",
        "created_at": datetime.now(UTC),
        "known_through": config.known_through,
        "test_start": config.test_start,
        "test_end": config.test_end,
        "candidates": len(candidates),
        "selected": 0,
        "account_eligible": False,
        "limitations": list(limitations)
        + [
            "development_selection_only",
            "reserved_test_not_assessed",
            "block_sign_symmetry_and_between_block_independence_assumed",
            "search_family_excludes_undeclared_prior_experiments",
            "industry_and_risk_exposures_not_available",
        ]
        + ([] if config.cost_screen else ["cost_and_portfolio_validation_pending"]),
    }
    # 新目录是唯一写入范围；注册和候选表先落盘，异常退出仍保留搜索预算及已完成尝试。
    output.mkdir(parents=True, exist_ok=False)
    freeze_engine(output)
    (output / "config.toml").write_bytes(body)
    pq.write_table(
        pa.Table.from_pylist(
            [record],
            schema=RUN_SCHEMA.with_metadata(
                {**_result_metadata(source, RUN_SCHEMA, run_id, scope), **source_metadata}
            ),
        ),
        output / "registration.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist([asdict(c) for c in candidates], schema=TRIAL_SCHEMA),
        output / "candidates.parquet",
        compression="zstd",
    )
    (output / "trials.parquet").mkdir()
    development = create_snapshot(
        bars,
        universe,
        output / "development",
        source.spec,
        allow_exploratory=config.allow_exploratory,
    )
    cost_inputs = {}
    if config.cost_screen:
        from invest.alpaca_research import freeze_execution_evidence
        from invest.backtest_study import execution_inputs

        cost_inputs = execution_inputs(
            source, config.cost_screen.execution, config.validation_start, config.validation_end
        )
        (output / "execution").mkdir()
        for instrument, table in cost_inputs.items():
            pq.write_table(
                table, output / "execution" / f"{instrument}.parquet", compression="zstd"
            )
            freeze_execution_evidence(
                config.cost_screen.execution[instrument],
                output / "execution" / f"{instrument}.parquet",
            )
    labels = forward_labels(development, (config.horizon,))
    record["development_snapshot_id"] = development.snapshot_id
    diagnostics: list[dict[str, Any]] = []
    factors_all: list[pa.Table] = []
    selected: list[dict[str, Any]] = []
    train_vectors: dict[str, pd.Series[Any]] = {}
    validation_vectors: dict[str, pd.Series[Any]] = {}
    trial_metadata = _result_metadata(development, TRIAL_SCHEMA, run_id, scope)
    for candidate in candidates:
        with _record_trial(candidate, output / "trials.parquet", trial_metadata) as trial:
            if candidate.depth > config.max_depth or candidate.nodes > config.max_nodes:
                trial["reason"] = "complexity_budget"
            else:
                factors = calculate_factors(
                    development, {candidate.factor: candidate.expression}, cache_root
                )
                factors_all.append(factors.table)
                evaluation = _evaluate(
                    candidate, factors, labels, development, config, trial, diagnostics
                )
                if evaluation is not None:
                    train, validation, target = evaluation
                    correlations = [
                        abs(train.corr(previous)) for previous in train_vectors.values()
                    ]
                    trial["max_correlation"] = max(correlations, default=0.0)
                    if any(not np.isfinite(value) for value in correlations):
                        trial["reason"] = "insufficient_correlation_overlap"
                    elif trial["max_correlation"] >= config.max_correlation:
                        trial["reason"] = "redundant_correlation"
                    elif len(selected) >= config.pool_size:
                        trial["reason"] = "pool_capacity"
                    else:
                        incremental = _incremental_ic(
                            pd.DataFrame({**validation_vectors, candidate.factor: validation}),
                            target,
                            config,
                        )
                        trial["incremental_ic"] = incremental
                        if incremental is None:
                            trial["reason"] = "insufficient_incremental_evidence"
                        elif incremental < config.min_incremental_ic:
                            trial["reason"] = "no_incremental_ic"
                        else:
                            if config.cost_screen:
                                from invest.factor_costs import screen_pool

                                trial.update(
                                    screen_pool(
                                        [*selected, trial],
                                        development,
                                        cost_inputs,
                                        config,
                                        output / "cost_screen" / f"trial_{candidate.trial_id:04d}",
                                        cache_root,
                                    )
                                )
                                if trial["cost_status"] != "passed":
                                    trial["reason"] = trial["cost_reason"]
                                    continue
                            trial.update(status="selected", reason="passed")
                            selected.append(trial)
                            (
                                train_vectors[candidate.factor],
                                validation_vectors[candidate.factor],
                            ) = (
                                train,
                                validation,
                            )
    pool = freeze_factor_pool(
        [
            {key: row[key] for key in ("factor", "expression", "direction", "trial_id")}
            | {"weight": 1 / len(selected)}
            for row in selected
        ],
        {
            "snapshot_id": development.snapshot_id,
            "source": development.spec.source,
            "price_basis": development.spec.price_basis,
            "volume_unit": development.spec.volume_unit,
            "currency": development.spec.currency,
            "scope": scope,
            "input_scope": development.scope,
            "source_ref": development.spec.source_ref,
            "source_snapshot_id": source.snapshot_id,
            **{key.decode(): value.decode() for key, value in source_metadata.items()},
            "run_id": run_id,
            "config_sha256": record["config_sha256"],
            "knowledge_through": config.validation_end.isoformat(),
            "horizon": str(config.horizon),
            "weighting": "equal_signed_cross_sectional_rank",
            "evidence_status": "research_only",
            "multiple_testing": "block_sign_bonferroni",
            "test_family_size": str(config.test_family_size or config.candidate_budget),
            "cost_screen": "passed" if config.cost_screen and selected else "not_evaluated",
            **(
                {
                    "cost_policy_id": config.cost_screen.policy.policy_id,
                    "cost_initial_cash": str(config.cost_screen.initial_cash),
                }
                if config.cost_screen
                else {}
            ),
        },
    )
    pq.write_table(pool.table, output / "factor_pool.parquet", compression="zstd")
    combined = (
        pa.concat_tables(factors_all)
        if factors_all
        else pa.Table.from_pylist(
            [], schema=FACTOR_SCHEMA.with_metadata(development.metadata(FACTOR_SCHEMA))
        )
    )
    pq.write_table(combined, output / "factors.parquet", compression="zstd")
    segment_labels = [
        purge_segment(
            FactorFrame(combined),
            labels,
            start,
            end,
            config.horizon,
            snapshot=development,
            allow_exploratory=config.allow_exploratory,
        )[1].table
        for start, end in (
            (config.train_start, config.train_end),
            (config.validation_start, config.validation_end),
        )
    ]
    label_metadata = {
        **_result_metadata(development, LABEL_SCHEMA, run_id, scope),
        b"label_timing_policy": b"segment_close_price_availability",
        **{
            f"{segment}_available_by".encode(): (table.schema.metadata or {})[b"label_available_by"]
            for segment, table in zip(("train", "validation"), segment_labels, strict=True)
        },
        **{
            key: str(
                sum(int((table.schema.metadata or {})[key]) for table in segment_labels)
            ).encode()
            for key in (b"label_timing_rejected_rows", b"label_unknown_timing_rows")
        },
    }
    pq.write_table(
        pa.concat_tables(segment_labels).replace_schema_metadata(label_metadata),
        output / "labels.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(
            diagnostics,
            schema=DIAGNOSTIC_SCHEMA.with_metadata(
                _result_metadata(development, DIAGNOSTIC_SCHEMA, run_id, scope)
            ),
        ),
        output / "diagnostics.parquet",
        compression="zstd",
    )
    signals = (
        generate_signals(
            pool,
            development,
            config.validation_end,
            allow_exploratory=config.allow_exploratory,
            cache_root=cache_root,
        ).table
        if selected
        else pa.Table.from_pylist(
            [],
            schema=SIGNAL_SCHEMA.with_metadata(
                {
                    **development.metadata(SIGNAL_SCHEMA),
                    b"scope": pool.metadata["scope"].encode(),
                    b"pool_id": pool.metadata["pool_id"].encode(),
                    b"evidence_status": b"research_only",
                }
            ),
        )
    )
    pq.write_table(signals, output / "signals.parquet", compression="zstd")
    record.update(
        status="selected" if selected else "rejected",
        selected=len(selected),
        pool_id=pool.metadata["pool_id"],
        completed_at=datetime.now(UTC),
    )
    pq.write_table(
        pa.Table.from_pylist(
            [record],
            schema=RUN_SCHEMA.with_metadata(
                {**_result_metadata(development, RUN_SCHEMA, run_id, scope), **source_metadata}
            ),
        ),
        output / "run.parquet",
        compression="zstd",
    )
    write_quant_report(output, "mining", record)
    seal_artifacts(output)
    return MiningResult(
        output,
        run_id,
        cast(str, record["status"]),
        pool.metadata["pool_id"],
        len(candidates),
        len(selected),
    )
