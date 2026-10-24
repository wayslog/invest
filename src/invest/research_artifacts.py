"""研究产物的冻结、完整清单和只读校验。"""

import json
import platform
import shutil
from importlib.metadata import version
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from invest.contracts import research_schema
from invest.research_data import digest

MANIFEST_SCHEMA = research_schema("run_artifacts", [("path", pa.string()), ("sha256", pa.string())])


def protect_inputs(destinations: tuple[Path, ...], sources: tuple[Path, ...]) -> None:
    if any(
        target.resolve().is_relative_to(source.resolve())
        for target in destinations
        for source in sources
    ):
        raise ValueError("Research writes cannot modify historical input directories")


def runtime_versions() -> str:
    return json.dumps(
        {
            "python": platform.python_version(),
            **{
                name: version(name)
                for name in (
                    "pyqlib",
                    "alphalens-reloaded",
                    "pyarrow",
                    "pandas",
                    "numpy",
                    "exchange-calendars",
                )
            },
        },
        sort_keys=True,
    )


def seal_artifacts(directory: Path) -> None:
    rows = [
        {"path": str(path.relative_to(directory)), "sha256": digest(path)}
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path != directory / "artifacts.parquet"
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=MANIFEST_SCHEMA),
        directory / "artifacts.parquet",
        compression="zstd",
    )


def verify_artifacts(directory: Path) -> None:
    rows = pq.read_table(directory / "artifacts.parquet").to_pylist()
    names = {row["path"] for row in rows}
    actual = {
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file() and path != directory / "artifacts.parquet"
    }
    if len(names) != len(rows) or names != actual:
        raise ValueError("Research artifact inventory changed")
    for row in rows:
        path = directory / row["path"]
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(directory.resolve())
            or not path.is_file()
            or digest(path) != row["sha256"]
        ):
            raise ValueError(f"Research artifact changed: {row['path']}")


def freeze_engine(directory: Path) -> None:
    target = directory / "engine" / "invest"
    target.mkdir(parents=True)
    for source in Path(__file__).parent.glob("*.py"):
        shutil.copy2(source, target / source.name)
    lock = Path(__file__).resolve().parents[2] / "uv.lock"
    if lock.is_file():
        shutil.copy2(lock, directory / "uv.lock")
