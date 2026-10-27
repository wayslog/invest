"""扩展的因果算子：回看长度、拒绝规则及与 pandas/numpy 参考实现一致。"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from invest.contracts import RESEARCH_BARS, UNIVERSE, DataSnapshot, SnapshotSpec
from invest.qlib_adapter import calculate_factors, expression_lookback
from invest.quality import regular_sessions
from invest.research_data import create_snapshot

SPEC = SnapshotSpec("synthetic", "test_factor_operators_v1", "raw", "shares", "synthetic")


def zigzag(tmp_path: Path, length: int = 30) -> DataSnapshot:
    sessions = regular_sessions(date(2024, 1, 2), date(2024, 3, 29)).to_pylist()[:length]
    rows, members = [], []
    for number in (1, 2):
        instrument = f"ZIG{number}"
        members.append(
            {
                "instrument": instrument,
                "symbol": instrument,
                "start": sessions[0]["date"],
                "end": sessions[-1]["date"],
                "available_at": sessions[0]["open_at"],
            }
        )
        for index, session in enumerate(sessions):
            close = Decimal(100 + number * index) + Decimal((index * 7 * number) % 5)
            rows.append(
                {
                    "date": session["date"],
                    "instrument": instrument,
                    "open": close - Decimal((index % 3) - 1),
                    "high": close + 2 + Decimal(index % 4),
                    "low": close - 2,
                    "close": close,
                    "volume": Decimal(1000 + 50 * ((index * number) % 6)),
                    "available_at": session["close_at"],
                    "captured_at": datetime(2024, 4, 1, tzinfo=UTC),
                }
            )
    return create_snapshot(
        pa.Table.from_pylist(rows, schema=RESEARCH_BARS),
        pa.Table.from_pylist(members, schema=UNIVERSE),
        tmp_path / "snapshot",
        SPEC,
    )


@pytest.mark.parametrize(
    ("expression", "lookback"),
    [
        ("Greater($open,$close)", 0),
        ("Less(Ref($open,2),$close)", 2),
        ("Mean($close>Ref($close,1),5)", 5),
        ("Mean($close<=Ref($close,3),4)", 6),
        ("Quantile($close,10,0.8)/$close", 9),
        ("Quantile(Ref($close,1),3,1)", 3),
        ("Slope($close,20)/$close", 19),
        ("Rsquare($close,5)", 4),
        ("Resi(Ref($close,2),5)", 6),
        ("(IdxMax($high,10)-IdxMin($low,10))/10", 9),
        ("Sum(Greater($close-Ref($close,1),0),5)", 5),
    ],
)
def test_extended_causal_operators_report_lookback(expression: str, lookback: int) -> None:
    assert expression_lookback(expression) == lookback


@pytest.mark.parametrize(
    "expression",
    [
        "Quantile($close,5,1.5)",
        "Quantile($close,5,True)",
        "Quantile($close,0,0.5)",
        "Quantile($close,$close,0.5)",
        "Slope($close,0)",
        "IdxMax($high,-2)",
        "Greater($close)",
        "Greater($close,$open,$low)",
        "$close==$open",
        "$close!=$open",
        "$low<$close<$high",
        "Mean($close>Ref($close,-1),5)",
        "Rsquare($vwap,5)",
        "EMA($close,5)",
    ],
)
def test_extended_operators_reject_future_or_undeclared_forms(expression: str) -> None:
    with pytest.raises(ValueError, match="causal"):
        expression_lookback(expression)


def test_extended_operators_match_reference_calculations(tmp_path: Path) -> None:
    data = zigzag(tmp_path)
    expressions = {
        "greater": "Greater($open,$close)",
        "less": "Less($open,$close)",
        "up_share": "Mean($close>Ref($close,1),5)",
        "upper_quantile": "Quantile($close,6,0.8)",
        "argmax": "IdxMax($high,4)",
        "argmin": "IdxMin($low,4)",
        "slope": "Slope($close,5)",
        "rsquare": "Rsquare($close,5)",
        "residual": "Resi($close,5)",
    }
    table = calculate_factors(data, expressions, tmp_path / "cache").table.to_pandas()
    bars = data.bars.to_pandas()
    for instrument, group in bars.groupby("instrument"):
        frame = group.set_index("date")[["open", "high", "low", "close"]].astype(float)
        close = frame["close"]

        def fit(window: np.ndarray) -> tuple[float, float, float]:
            x = np.arange(len(window), dtype=float)
            slope, intercept = np.polyfit(x, window, 1)
            fitted = slope * x + intercept
            total = float(((window - window.mean()) ** 2).sum())
            rsquare = 1 - float(((window - fitted) ** 2).sum()) / total
            return slope, rsquare, float(window[-1] - fitted[-1])

        fits = [fit(close.to_numpy()[i - 4 : i + 1]) if i >= 4 else None for i in range(len(close))]
        expected = {
            "greater": np.maximum(frame["open"], close),
            "less": np.minimum(frame["open"], close),
            "up_share": (close > close.shift(1))
            .astype(float)
            .rolling(5)
            .mean()
            .where(close.shift(5).notna()),
            "upper_quantile": close.rolling(6).quantile(0.8),
            "argmax": frame["high"].rolling(4).apply(lambda x: x.argmax() + 1, raw=True),
            "argmin": frame["low"].rolling(4).apply(lambda x: x.argmin() + 1, raw=True),
            "slope": pd.Series([f and f[0] for f in fits], index=close.index, dtype=float),
            "rsquare": pd.Series([f and f[1] for f in fits], index=close.index, dtype=float),
            "residual": pd.Series([f and f[2] for f in fits], index=close.index, dtype=float),
        }
        for name, reference in expected.items():
            actual = (
                table[(table["instrument"] == instrument) & (table["factor"] == name)]
                .set_index("date")["value"]
                .astype(float)
            )
            lookback = expression_lookback(expressions[name])
            assert actual.iloc[:lookback].isna().all(), name
            np.testing.assert_allclose(
                actual.iloc[lookback:].to_numpy(),
                reference.iloc[lookback:].to_numpy(),
                rtol=1e-4,
                atol=1e-4,
                err_msg=name,
            )
