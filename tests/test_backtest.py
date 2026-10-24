"""P3 的共同决策、成交时序、会计重建和不可覆盖研究产物。"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from invest.contracts import SignalFrame
from invest.strategies import Policy, decide
from tests.test_decisions import signals
from tests.test_portfolio import bars

D = Decimal


def policy(**changes: Any) -> Policy:
    return replace(
        Policy(
            top_k=1,
            allocation=D(1),
            position_cap=D(1),
            commission=D(1),
            slippage_bps=D(0),
            stop_loss=D(0),
            trailing_stop=D(0),
            take_profit=D(0),
            account_drawdown=D(1),
            max_holding_sessions=0,
        ),
        **changes,
    )


def test_backtest_uses_the_same_decisions_and_reduces_gap_fills() -> None:
    from invest.backtest import simulate_signals

    inputs = {"ALPHA": bars("ALPHA", [100, 200, 200, 200]), "BETA": bars("BETA", [100] * 4)}
    days = inputs["ALPHA"]["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    result = simulate_signals(inputs, history, policy(), days[1], days[-1], initial_cash=D(1000))
    trades = result.portfolio.trades.to_pylist()
    assert len(trades) == 1
    assert trades[0]["decision_date"] == days[0] and trades[0]["date"] == days[1]
    assert trades[0]["quantity"] == 4 and trades[0]["cash_after"] == D(199)
    assert result.portfolio.equity["equity"].to_pylist() == [D(999)] * 3
    for account, state in result.contexts:
        repeated = decide(history, account, state, policy())
        expected = result.actions.filter(
            pa.array([day == account.as_of for day in result.actions["date"].to_pylist()])
        )
        assert repeated.actions.equals(expected, check_metadata=True)
    short = simulate_signals(
        {key: table.slice(0, 3) for key, table in inputs.items()},
        history,
        policy(),
        days[1],
        days[2],
        initial_cash=D(1000),
    )
    assert short.portfolio.equity.equals(result.portfolio.equity.slice(0, 2))
    assert short.portfolio.trades.equals(result.portfolio.trades)


@pytest.mark.parametrize("gap", [False, True])
def test_protective_exits_use_gap_prices_and_conservative_intraday_order(gap: bool) -> None:
    from invest.backtest import simulate_signals

    updates: dict[int, dict[str, object]] = (
        {2: {"open": D(80), "high": D(85), "low": D(75), "close": D(80)}}
        if gap
        else {
            1: {"high": D(125), "low": D(85)},
        }
    )
    data = bars("ALPHA", [100] * 4, updates=updates)
    days = data["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(
        commission=D(0),
        stop_loss=D(".1"),
        take_profit=D(".2"),
        exit_mode="protective",
        cooldown_sessions=2,
    )
    result = simulate_signals(
        {"ALPHA": data}, history, settings, days[1], days[-1], initial_cash=D(1000)
    )
    trades = result.portfolio.trades.to_pylist()
    assert len(trades) == 2
    assert trades[1]["reason"] == "stop_loss"
    assert trades[1]["price"] == (D(80) if gap else D(90))
    assert trades[1]["phase"] == ("protective_open" if gap else "protective_intraday")
    assert result.final_account.cash == (D(800) if gap else D(900))
    assert not result.final_account.holdings and not result.final_account.pending
    assert result.actions.to_pylist()[-1]["reason"] == "reentry_cooldown"
    from invest.portfolio_audit import audit_backtest

    assert set(
        audit_backtest({"ALPHA": data}, result.portfolio, settings, D(1000))[0][
            "status"
        ].to_pylist()
    ) == {"pass"}
    altered = result.portfolio.trades.to_pylist()
    altered[-1]["price"] += 1
    corrupt = replace(
        result.portfolio,
        trades=pa.Table.from_pylist(altered, schema=result.portfolio.trades.schema),
    )
    assert (
        "error"
        in audit_backtest({"ALPHA": data}, corrupt, settings, D(1000))[0]["status"].to_pylist()
    )


def test_partial_exit_survives_price_recovery_and_uses_prior_volume() -> None:
    from invest.backtest import simulate_signals

    data = bars("ALPHA", [100, 100, 85, 100, 100], updates={2: {"volume": 3}})
    days = data["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(commission=D(0), stop_loss=D(".1"), rebalance_sessions=1)
    result = simulate_signals(
        {"ALPHA": data}, history, settings, days[1], days[-1], initial_cash=D(1000)
    )
    trades = result.portfolio.trades.to_pylist()
    assert [(row["side"], row["quantity"]) for row in trades] == [
        ("buy", 10),
        ("sell", 3),
        ("sell", 7),
    ]
    assert trades[1]["volume_limit"] == 3
    assert result.outcomes.to_pylist()[1]["status"] == "reduced"
    assert not result.final_account.holdings


@pytest.mark.parametrize("settlement", ["same_session", "next_session"])
def test_rotations_respect_sale_proceeds_and_reconcile(settlement: str) -> None:
    from invest.backtest import simulate_signals
    from invest.portfolio_audit import audit_backtest

    inputs = {instrument: bars(instrument, [100] * 5) for instrument in ("ALPHA", "BETA")}
    days = inputs["ALPHA"]["date"].to_pylist()
    rows = []
    for day in days:
        rows.extend(
            [
                {**row, "score": -1.0, "direction": 0}
                if row["instrument"] == "ALPHA" and day >= days[1]
                else row
                for row in signals(day).table.to_pylist()
            ]
        )
    history = SignalFrame(pa.Table.from_pylist(rows, schema=signals().table.schema))
    settings = policy(commission=D(0), rebalance_sessions=1, sale_proceeds=settlement)
    result = simulate_signals(inputs, history, settings, days[1], days[-1], initial_cash=D(1000))
    trades = result.portfolio.trades.to_pylist()
    bought = next(row for row in trades if row["symbol"] == "BETA")
    assert bought["date"] == (days[2] if settlement == "same_session" else days[4])
    assert set(
        audit_backtest(inputs, result.portfolio, settings, D(1000))[0]["status"].to_pylist()
    ) == {"pass"}


def test_zero_volume_cancels_fill_and_does_not_retry_an_expired_order() -> None:
    from invest.backtest import simulate_signals

    data = bars("ALPHA", [100] * 4, updates={1: {"volume": 0}})
    days = data["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    result = simulate_signals(
        {"ALPHA": data}, history, policy(commission=D(0)), days[1], days[-1], initial_cash=D(1000)
    )
    assert result.portfolio.trades.num_rows == 0
    assert result.outcomes.to_pylist()[0]["status"] == "rejected"


def test_split_and_dividend_reconcile_independently_and_full_cycle_is_one_trade() -> None:
    from invest.backtest import simulate_signals
    from invest.portfolio_audit import audit_backtest

    data = bars("ALPHA", [100, 100, 49, 49, 49])
    days = data["date"].to_pylist()
    data = bars(
        "ALPHA",
        [100, 100, 49, 49, 49],
        updates={
            2: {"split_ratio": 2, "dividend": D(1), "dividend_pay_date": days[-1], "volume": 6},
        },
    )
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(commission=D(0), max_holding_sessions=2, stop_loss=D(".1"))
    result = simulate_signals(
        {"ALPHA": data}, history, settings, days[1], days[-1], initial_cash=D(1000)
    )
    checks, attribution, cycles = audit_backtest(
        {"ALPHA": data}, result.portfolio, settings, D(1000)
    )
    assert set(checks["status"].to_pylist()) == {"pass"}
    assert result.portfolio.equity["equity"].to_pylist() == [D(1000)] * 4
    assert result.portfolio.equity["receivables"].to_pylist() == [D(0), D(20), D(20), D(0)]
    assert cycles.num_rows == 1 and cycles["realized_pnl"].to_pylist() == [D(0)]
    assert cycles["r_multiple"].to_pylist() == [0.0]
    assert attribution["total_pnl"][-1].as_py() == D(0)
    altered = result.portfolio.trades.to_pylist()
    altered[-1]["cash_after"] += 1
    corrupt = replace(
        result.portfolio,
        trades=pa.Table.from_pylist(altered, schema=result.portfolio.trades.schema),
    )
    assert (
        "error"
        in audit_backtest({"ALPHA": data}, corrupt, settings, D(1000))[0]["status"].to_pylist()
    )


def test_fractional_risk_budget_is_saved_at_money_precision() -> None:
    from invest.backtest import simulate_signals
    from invest.portfolio_audit import audit_backtest

    data = bars(
        "ALPHA", [100] * 4, updates={1: {"open": D("100.123456"), "close": D("100.123456")}}
    )
    days = data["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(max_holding_sessions=1, stop_loss=D(".08"), slippage_bps=D(5))
    result = simulate_signals(
        {"ALPHA": data}, history, settings, days[1], days[-1], initial_cash=D(1000)
    )
    checks, _, cycles = audit_backtest({"ALPHA": data}, result.portfolio, settings, D(1000))
    assert set(checks["status"].to_pylist()) == {"pass"}
    buy = result.portfolio.trades.to_pylist()[0]
    expected = (buy["quantity"] * buy["price"] * settings.stop_loss).quantize(D(".000001"))
    assert cycles["risk_budget"].to_pylist() == [expected]
    assert cycles["r_multiple"][0].as_py() == pytest.approx(
        float(cycles["realized_pnl"][0].as_py() / expected)
    )


def test_legacy_buy_hold_financial_paths_are_preserved() -> None:
    from invest.backtest import simulate_signals
    from invest.portfolio import simulate_portfolio
    from invest.strategies import Candidate
    from tests.test_portfolio import study_config

    days = bars("ALPHA", [100] * 9)["date"].to_pylist()
    inputs = {
        "ALPHA": bars(
            "ALPHA",
            [100] * 5 + [49] * 4,
            updates={
                5: {"split_ratio": 2, "dividend": D(1), "dividend_pay_date": days[8]},
            },
        ),
        "BETA": bars("BETA", [100] * 9),
    }
    old_config = replace(study_config(), symbols=("ALPHA", "BETA"))
    old = simulate_portfolio(inputs, old_config, Candidate("buy_hold"), days[4], days[8])
    settings = policy(
        top_k=2,
        allocation=old_config.allocation,
        position_cap=old_config.allocation,
        commission=old_config.commission,
        slippage_bps=old_config.slippage_bps,
        rebalance_sessions=1000,
    )
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    new = simulate_signals(inputs, history, settings, days[4], days[8]).portfolio
    assert old.equity.equals(new.equity) and old.positions.equals(new.positions)
    fields = [field for field in old.trades.column_names if field != "reason"]
    assert old.trades.select(fields).to_pylist() == new.trades.select(fields).to_pylist()


def test_audit_rejects_fills_linked_to_another_instrument_order() -> None:
    from invest.backtest import simulate_signals
    from invest.portfolio_audit import audit_backtest

    inputs = {name: bars(name, [100] * 4) for name in ("ALPHA", "BETA")}
    days = inputs["ALPHA"]["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(top_k=2, commission=D(0))
    result = simulate_signals(inputs, history, settings, days[1], days[-1], initial_cash=D(1000))
    rows = result.portfolio.trades.to_pylist()
    assert len(rows) == 2
    rows[0]["order_id"], rows[1]["order_id"] = rows[1]["order_id"], rows[0]["order_id"]
    corrupt = replace(
        result.portfolio, trades=pa.Table.from_pylist(rows, schema=result.portfolio.trades.schema)
    )
    checks = audit_backtest(inputs, corrupt, settings, D(1000))[0].to_pylist()
    errors = [row for row in checks if row["status"] == "error"]
    assert {row["check"].split(":")[0] for row in errors} == {"ALPHA", "BETA"}


@pytest.mark.parametrize(
    ("timing", "exploratory"),
    [("late", False), ("late", True), ("unknown", False), ("unknown", True), ("missing", True)],
)
def test_audit_respects_quote_availability_for_trailing_highs(
    timing: str, exploratory: bool
) -> None:
    from datetime import timedelta

    from invest.backtest import simulate_signals
    from invest.portfolio_audit import audit_backtest
    from invest.quality import regular_sessions

    data = bars("ALPHA", [100, 100, 150, 115, 100])
    days = data["date"].to_pylist()
    sessions = regular_sessions(days[0], days[-1]).to_pylist()
    rows = [
        {"date": day, "instrument": "ALPHA", "available_at": row["close_at"]}
        for day, row in zip(days, sessions, strict=True)
    ]
    if timing == "late":
        rows[2]["available_at"] += timedelta(days=1)
    elif timing == "unknown":
        rows[2]["available_at"] = None
    else:
        rows.pop(2)
    availability = pa.Table.from_pylist(rows)
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(
        commission=D(0),
        trailing_stop=D(".1"),
        exit_mode="protective",
        rebalance_sessions=100,
        allow_exploratory=exploratory,
    )
    result = simulate_signals(
        {"ALPHA": data},
        history,
        settings,
        days[1],
        days[-1],
        initial_cash=D(1000),
        availability=availability,
    )
    sale = result.portfolio.trades.to_pylist()[-1]
    assert sale["stop_price"] == (D(135) if timing == "unknown" and exploratory else D("103.5"))
    checks = audit_backtest(
        {"ALPHA": data}, result.portfolio, settings, D(1000), availability=availability
    )[0]
    assert set(checks["status"].to_pylist()) == {"pass"}


def test_frozen_pool_backtest_is_replayable_and_keeps_known_history(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    from invest.backtest_study import run_backtest, verify_backtest
    from invest.factor_mining import run_mining
    from invest.market import BAR_SCHEMA
    from invest.research_data import digest
    from tests.test_factor_mining import mining_config, research_snapshot

    snapshot = research_snapshot(tmp_path)
    mine = run_mining(
        mining_config(tmp_path, snapshot), tmp_path / "mine", cache_root=tmp_path / "cache"
    )
    days = snapshot.calendar["date"].to_pylist()
    mapping = []
    for instrument in snapshot.universe["instrument"].to_pylist():
        rows = [
            {
                "date": row["date"],
                "symbol": instrument,
                **{
                    field: row[field].quantize(D(".000001"))
                    for field in ("open", "high", "low", "close")
                },
                "volume": int(row["volume"]),
                "split_ratio": 1,
                "dividend": D(0),
                "dividend_pay_date": None,
            }
            for row in snapshot.bars.to_pylist()
            if row["instrument"] == instrument
        ]
        path = tmp_path / f"{instrument}.parquet"
        pq.write_table(
            pa.Table.from_pylist(
                rows,
                schema=BAR_SCHEMA.with_metadata(
                    {**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"}
                ),
            ),
            path,
            compression="zstd",
        )
        mapping.append(f'{instrument} = "{path}"')
    config = tmp_path / "backtest.toml"
    config.write_text(f'''snapshot = "{snapshot.directory}"
factor_pool = "{mine.directory / "factor_pool.parquet"}"
start = {days[120]}
end = {days[139]}
known_through = {days[139]}
initial_cash = "5000"
[execution]
{chr(10).join(mapping)}
[policy]
top_k = 2
allocation = "0.8"
position_cap = "0.4"
''')
    before = digest(mine.directory / "run.parquet")
    result = run_backtest(config, tmp_path / "study", cache_root=tmp_path / "cache")
    assert result.status == "completed" and result.history_status == "known_history"
    assert verify_backtest(result.directory, cache_root=tmp_path / "cache")["status"] == "verified"
    assert digest(mine.directory / "run.parquet") == before
    assert set(pq.read_table(result.directory / "checks.parquet")["status"].to_pylist()) == {"pass"}
    metrics = pq.read_table(result.directory / "metrics.parquet")
    assert set(metrics["scenario"].to_pylist()) == {
        "strategy",
        "cash",
        "equal_weight",
        "double_cost",
    }
    with pytest.raises(FileExistsError):
        run_backtest(config, result.directory, cache_root=tmp_path / "cache")
    early = tmp_path / "early.toml"
    early.write_text(config.read_text().replace(f"start = {days[120]}", f"start = {days[119]}"))
    with pytest.raises(ValueError, match="selection"):
        run_backtest(early, tmp_path / "early", cache_root=tmp_path / "cache")
    assert not (tmp_path / "early").exists()
    from invest.research_data import create_snapshot

    changed = snapshot.bars.to_pylist()
    for row in changed:
        if row["date"] > days[139]:
            row["available_at"] = None
    future = create_snapshot(
        pa.Table.from_pylist(changed, schema=snapshot.bars.schema),
        snapshot.universe,
        tmp_path / "future_unknown",
        snapshot.spec,
        allow_exploratory=True,
    )
    later = tmp_path / "future.toml"
    later.write_text(config.read_text().replace(str(snapshot.directory), str(future.directory)))
    repeated = run_backtest(later, tmp_path / "future_study", cache_root=tmp_path / "cache")
    registered = pq.read_table(repeated.directory / "run.parquet").to_pylist()[0]
    assert registered["scope"] == "synthetic"
    assert "historical_availability_unknown" in registered["source_limitations"]
    assert (
        pq.read_table(repeated.directory / "signals.parquet").to_pylist()
        == pq.read_table(result.directory / "signals.parquet").to_pylist()
    )
    altered = pq.read_table(result.directory / "fills.parquet").to_pylist()
    altered[0]["cash_after"] += 1
    pq.write_table(
        pa.Table.from_pylist(altered, schema=pq.read_schema(result.directory / "fills.parquet")),
        result.directory / "fills.parquet",
        compression="zstd",
    )
    with pytest.raises(ValueError, match="changed"):
        verify_backtest(result.directory, cache_root=tmp_path / "cache")
