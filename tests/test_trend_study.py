"""固定趋势假设的时序、共同现金、成本、不可覆盖与重放验证。"""

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.contracts import RESEARCH_BARS, UNIVERSE, SnapshotSpec
from invest.market import BAR_SCHEMA
from invest.quality import regular_sessions
from invest.research_data import create_snapshot
from invest.trend_study import load_config, rule_signals, run_trend_study, verify_trend_study


def trend_inputs(root: Path, *, shock: bool = False, late: bool = False) -> Path:
    root.mkdir(parents=True)
    days = regular_sessions(date(2024, 7, 1), date(2025, 8, 29)).to_pylist()[:268]
    source_rows = []
    for symbol, slope in (("ALPHA", ".002"), ("BETA", ".003"), ("SPY", ".001")):
        rows = []
        for i, session in enumerate(days):
            price = (Decimal(100) * (1 + Decimal(slope)) ** i).quantize(Decimal(".000001"))
            if shock and i >= 262 and symbol != "SPY":
                price *= 2
            values = {
                "date": session["date"],
                "open": price,
                "close": price,
                "high": price + 1,
                "low": price - 1,
                "volume": 1000000,
            }
            rows.append(
                {
                    **values,
                    "symbol": symbol,
                    "split_ratio": 1,
                    "dividend": Decimal(0),
                    "dividend_pay_date": None,
                }
            )
            source_rows.append(
                {
                    **values,
                    "instrument": symbol,
                    "available_at": session["close_at"] + timedelta(days=int(late and i == 253)),
                    "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
                }
            )
        pq.write_table(
            pa.Table.from_pylist(
                rows,
                schema=BAR_SCHEMA.with_metadata(
                    {
                        **(BAR_SCHEMA.metadata or {}),
                        b"source": b"synthetic",
                    }
                ),
            ),
            root / f"{symbol}.parquet",
            compression="zstd",
        )
    for name, symbols in (("stocks", ["ALPHA", "BETA"]), ("benchmark", ["SPY"])):
        create_snapshot(
            pa.Table.from_pylist(
                [r for r in source_rows if r["instrument"] in symbols], schema=RESEARCH_BARS
            ),
            pa.Table.from_pylist(
                [
                    {
                        "instrument": s,
                        "symbol": s,
                        "start": days[0]["date"],
                        "end": days[-1]["date"],
                        "available_at": days[0]["open_at"],
                    }
                    for s in symbols
                ],
                schema=UNIVERSE,
            ),
            root / name,
            SnapshotSpec("synthetic", "trend_test", "raw", "shares", "synthetic"),
            allow_exploratory=True,
        )
    design = root / "rule-design.toml"
    design.write_text(f"""design = "selected_stock_trend_v1"
symbols = ["ALPHA", "BETA"]
benchmark = "SPY"
data_start = {days[0]["date"]}
start = {days[253]["date"]}
end = {days[-1]["date"]}
known_through = {days[-1]["date"]}
initial_cash = "5000"
strategy_trials = 1
history_status = "known_history_post_selection"
account_eligible = false
min_price = 10.0
min_dollar_volume = 20000000.0
max_volatility = 0.6
max_drawdown = 0.3
[policy]
allow_exploratory = true
allocation = "0.75"
position_cap = "0.25"
commission = "1"
slippage_bps = "5"
exit_mode = "protective"
sale_proceeds = "next_session"
""")
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "sha256": hashlib.sha256(design.read_bytes()).hexdigest(),
                    "body": design.read_bytes(),
                    "strategy_trials": 1,
                    "registered_at": datetime(2026, 1, 1, tzinfo=UTC),
                }
            ]
        ),
        root / "rule-registration.parquet",
        compression="zstd",
    )
    config = root / "inputs.toml"
    config.write_text("""design = "rule-design.toml"
snapshot = "stocks"
benchmark_snapshot = "benchmark"
[execution]
ALPHA = "ALPHA.parquet"
BETA = "BETA.parquet"
[benchmark_execution]
SPY = "SPY.parquet"
""")
    return config


def test_future_prices_do_not_change_earlier_signals_and_late_prices_are_blocked(
    tmp_path: Path,
) -> None:
    path = trend_inputs(tmp_path / "base")
    frame, tables, _ = rule_signals(load_config(path))
    changed, _, _ = rule_signals(load_config(trend_inputs(tmp_path / "shock", shock=True)))
    cutoff = tables["indicators"]["date"][18].as_py()
    for left, right in zip(frame.table.to_pylist(), changed.table.to_pylist(), strict=True):
        if left["date"] <= cutoff:
            assert {k: v for k, v in left.items() if k != "pool_id"} == {
                k: v for k, v in right.items() if k != "pool_id"
            }
    late, _, _ = rule_signals(load_config(trend_inputs(tmp_path / "late", late=True)))
    assert frame.table.to_pylist()[2]["direction"] == 1
    assert late.table.to_pylist()[2]["direction"] == 0
    assert frame.table.schema.metadata[b"signal_kind"] == b"prespecified_rule"
    assert frame.table.schema.metadata[b"trade_eligible"] == b"false"


def test_study_reuses_cash_costs_and_preserves_empty_action_context(tmp_path: Path) -> None:
    path = trend_inputs(tmp_path / "inputs")
    before = {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    output = tmp_path / "study"
    result = run_trend_study(path, output)
    assert result["status"] == "completed" and not result["trade_eligible"]
    metrics = {r["scenario"]: r for r in pq.read_table(output / "metrics.parquet").to_pylist()}
    assert metrics["strategy"]["commissions"] > 0
    assert metrics["strategy"]["final_equity"] > metrics["double_cost"]["final_equity"]
    assert metrics["cash"]["final_equity"] == Decimal(5000)
    costs = pq.read_table(output / "costs.parquet").to_pylist()
    assert costs[0]["slippage_cost"] > 0
    fills = pq.read_table(output / "fills.parquet").to_pylist()
    assert all(r["date"] > r["decision_date"] for r in fills)
    assert min(pq.read_table(output / "equity.parquet")["cash"].to_pylist()) >= 0
    actions = pq.read_table(output / "current_actions.parquet")
    assert all(r["current_quantity"] == 0 and r["action"] == "BUY" for r in actions.to_pylist())
    assert all(r["target_weight"] <= Decimal(".25") for r in actions.to_pylist())
    assert actions.schema.metadata[b"context_kind"] == b"independent_empty_simulation"
    assert not (output / "factor_pool.parquet").exists()
    assert all(p.read_bytes() == body for p, body in before.items())
    assert verify_trend_study(output)["tables"] > 50
    with pytest.raises(FileExistsError):
        run_trend_study(path, output)
    assert (output / "current.html").is_file()


def test_unregistered_changes_and_in_range_splits_are_rejected(tmp_path: Path) -> None:
    path = trend_inputs(tmp_path / "inputs")
    config = load_config(path)
    table = pq.read_table(config.execution["ALPHA"])
    rows = table.to_pylist()
    rows[200]["split_ratio"] = 2
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        config.execution["ALPHA"],
        compression="zstd",
    )
    with pytest.raises(ValueError, match="split-free"):
        run_trend_study(path, tmp_path / "failed")
    assert pq.read_table(tmp_path / "failed/run.parquet")["status"].to_pylist() == ["failed"]
    config.design.write_text(config.design.read_text().replace('"5000"', '"6000"'))
    with pytest.raises(ValueError, match="prior research registration"):
        rule_signals(replace(config))
