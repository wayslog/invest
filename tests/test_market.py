from pathlib import Path

import pyarrow.parquet as pq
import pytest

from invest.market import read_bars
from tests.helpers import make_bars


def test_typed_parquet_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    table = make_bars([100, 110, 120])
    pq.write_table(table, path, compression="zstd")
    assert read_bars(path, "DEMO").equals(table, check_metadata=True)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("symbol", "WRONG", "configured symbol"),
        ("volume", -1, "Invalid volume"),
        ("split_ratio", 0, "Invalid volume"),
    ],
)
def test_invalid_bar_values(tmp_path: Path, key: str, value: object, message: str) -> None:
    path = tmp_path / "bars.parquet"
    pq.write_table(make_bars([100, 110], updates={0: {key: value}}), path)
    with pytest.raises(ValueError, match=message):
        read_bars(path, "DEMO")


def test_adjusted_prices_cannot_be_used_for_fills(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    table = make_bars([100, 110])
    table = table.replace_schema_metadata({**table.schema.metadata, b"price_basis": b"adjusted"})
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="price_basis"):
        read_bars(path, "DEMO")


def test_duplicate_session_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    table = make_bars([100, 110]).take([0, 0])
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="strictly increasing"):
        read_bars(path, "DEMO")
