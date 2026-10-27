"""周度时点成员、连续换股和保留策略，以及缺数据时的诚实失败。"""

import hashlib
import json
import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.backtest import simulate_signals
from invest.contracts import (
    RESEARCH_BARS,
    UNIVERSE,
    AccountSnapshot,
    Holding,
    PositionState,
    Quote,
    SignalFrame,
    SnapshotSpec,
    StrategyState,
)
from invest.market import BAR_SCHEMA
from invest.portfolio_audit import audit_backtest
from invest.quality import regular_sessions
from invest.research_data import create_snapshot, load_snapshot
from invest.strategies import decide
from invest.weekly_features import adjusted_snapshot, weekly_frames
from invest.weekly_selection import WeeklySelection
from invest.weekly_study import load_config, run_weekly_study, verify_weekly_study
from invest.weekly_universe import (
    CATALOG_SCHEMA,
    FundSnapshot,
    membership_coverage,
    read_membership_catalog,
    weekly_schedule,
)
from tests.test_backtest import policy
from tests.test_decisions import DAY, signals
from tests.test_portfolio import bars

D = Decimal


def test_membership_requires_both_funds_and_never_uses_future_publications() -> None:
    start, end = date(2025, 7, 7), date(2026, 10, 23)
    weeks = weekly_schedule(start, end)
    assert len(weeks) == 68
    assert weeks[0]["price_as_of"] == date(2025, 7, 3)
    cutoff = weeks[0]["decision_at"]
    good = FundSnapshot("SPY", date(2025, 7, 3), cutoff, "source", (("ALPHA", "ALPHA"),))
    late = replace(good, fund="QQQ", known_by=cutoff + timedelta(seconds=1))
    coverage, members = membership_coverage([good, late], start, end)
    assert coverage.num_rows == 136
    assert [r["status"] for r in coverage.to_pylist()[:2]] == ["ready", "blocked"]
    assert coverage.to_pylist()[2]["reason"] == "historical_membership_stale"
    assert members.num_rows == 1
    assert members["membership_as_of"].to_pylist() == [date(2025, 7, 3)]
    future = replace(good, known_by=datetime(2026, 10, 26, tzinfo=UTC))
    changed, _ = membership_coverage([good, late, future], start, end)
    assert changed.equals(coverage)


def test_rank_exit_and_retention_are_separate_from_independent_signals() -> None:
    account = AccountSnapshot(
        "weekly",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(500),
        (Quote("ALPHA", D(100)), Quote("BETA", D(100))),
        (Holding("ALPHA", 5, D(100)),),
    )
    state = StrategyState(D(1000), positions=(PositionState("ALPHA", DAY, D(100)),))
    selection = WeeklySelection(
        ("BETA",),
        "rank_rotation",
        signals().table["available_at"][0].as_py(),
        "week_one",
        True,
        (("ALPHA", "BETA", 0.2),),
    )
    settings = policy(sale_proceeds="next_session")
    a = {
        r["instrument"]: r
        for r in decide(
            signals(), account, state, settings, selection=selection
        ).actions.to_pylist()
    }
    b = {
        r["instrument"]: r
        for r in decide(
            signals(),
            account,
            state,
            settings,
            selection=replace(selection, mode="hold_until_exit"),
        ).actions.to_pylist()
    }
    assert a["ALPHA"]["action"] == "SELL" and a["ALPHA"]["reason"] == "rank_exit"
    assert b["ALPHA"]["action"] == "HOLD" and b["ALPHA"]["reason"] == "retained_until_exit"
    assert a["BETA"]["reason"] == b["BETA"]["reason"] == "position_slots_occupied"
    # 下一日不再周调仓，落选仓位也不能增加，原因继续可见。
    retained = decide(
        signals(),
        account,
        state,
        settings,
        selection=replace(selection, mode="hold_until_exit", rebalance=False),
    ).actions.to_pylist()
    assert next(r for r in retained if r["instrument"] == "ALPHA")["target_quantity"] == 5
    rows = signals().table.to_pylist()
    rows[0].update(direction=0, score=0.0)
    failed = SignalFrame(pa.Table.from_pylist(rows, schema=signals().table.schema))
    for mode in ("rank_rotation", "hold_until_exit"):
        plan = decide(failed, account, state, settings, selection=replace(selection, mode=mode))
        assert plan.actions.to_pylist()[0]["exit_reason"] == "signal_exit"


def test_actual_slots_correlation_and_pending_buys_constrain_new_positions() -> None:
    selection = WeeklySelection(
        ("BETA", "GAMMA"),
        "hold_until_exit",
        datetime(2024, 1, 3, 22, tzinfo=UTC),
        "week",
        True,
        (("ALPHA", "BETA", 0.9), ("ALPHA", "GAMMA", None)),
    )
    chosen, reasons = selection.targets({"BETA", "GAMMA"}, {"ALPHA"}, set(), set(), 3)
    assert chosen == ["ALPHA"]
    assert reasons == {"BETA": "portfolio_correlation_limit", "GAMMA": "correlation_unavailable"}
    chosen, reasons = selection.targets({"BETA", "GAMMA"}, set(), set(), {"BETA"}, 1)
    assert chosen == ["BETA"] and reasons["GAMMA"] == "position_slots_occupied"


def test_continuous_rotation_reuses_settled_cash_and_same_inputs_keep_equal_paths() -> None:
    inputs = {s: bars(s, [100] * 6) for s in ("ALPHA", "BETA")}
    days = inputs["ALPHA"]["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    choices = {
        d: WeeklySelection(
            ("ALPHA",) if i < 2 else ("BETA",),
            "rank_rotation",
            signals(d).table["available_at"][0].as_py(),
            str(i // 2),
            i in (0, 2),
            (("ALPHA", "BETA", 0.2),),
        )
        for i, d in enumerate(days)
    }
    settings = policy(sale_proceeds="next_session")
    results = {}
    for mode in ("rank_rotation", "hold_until_exit"):
        contexts = {d: replace(c, mode=mode) for d, c in choices.items()}
        result = simulate_signals(
            inputs, history, settings, days[1], days[-1], initial_cash=D(1000), selections=contexts
        )
        results[mode] = result
        assert set(
            audit_backtest(inputs, result.portfolio, settings, D(1000))[0]["status"].to_pylist()
        ) == {"pass"}
        assert min(result.portfolio.equity["cash"].to_pylist()) >= 0
    trades = results["rank_rotation"].portfolio.trades.to_pylist()
    assert [(r["symbol"], r["side"]) for r in trades] == [
        ("ALPHA", "buy"),
        ("ALPHA", "sell"),
        ("BETA", "buy"),
    ]
    assert trades[2]["date"] > trades[1]["date"]
    assert results["hold_until_exit"].final_account.holdings[0].instrument == "ALPHA"
    assert len(results["hold_until_exit"].portfolio.trades) == 1
    # 没有成员变化时，两种规则的账户路径应一致。
    same = {d: replace(c, candidates=("ALPHA",)) for d, c in choices.items()}
    a = simulate_signals(
        inputs, history, settings, days[1], days[-1], initial_cash=D(1000), selections=same
    )
    b = simulate_signals(
        inputs,
        history,
        settings,
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections={d: replace(c, mode="hold_until_exit") for d, c in same.items()},
    )
    assert a.portfolio.equity.equals(b.portfolio.equity)


def test_weekend_available_signal_needs_explicit_pre_open_decision() -> None:
    friday = date(2024, 1, 5)
    frame = signals(friday)
    rows = frame.table.to_pylist()
    cutoff = datetime(2024, 1, 7, 2, tzinfo=UTC)
    for row in rows:
        row["available_at"] = cutoff
    frame = SignalFrame(pa.Table.from_pylist(rows, schema=frame.table.schema))
    account = AccountSnapshot(
        "weekly", "snapshot", "synthetic", friday, D(1000), D(1000), (Quote("ALPHA", D(100)),)
    )
    state = StrategyState(D(1000))
    choice = WeeklySelection(("ALPHA",), "rank_rotation", cutoff, "week", True)
    assert decide(frame, account, state, policy()).actions.to_pylist()[0]["quantity"] == 0
    assert (
        decide(frame, account, state, policy(), selection=choice).actions.to_pylist()[0]["action"]
        == "BUY"
    )
    with pytest.raises(ValueError, match="precede execution"):
        decide(
            frame,
            account,
            state,
            policy(),
            selection=replace(choice, decision_at=datetime(2024, 1, 8, 15, tzinfo=UTC)),
        )


def weekly_inputs(root: Path, *, missing: bool = False) -> Path:
    root.mkdir(parents=True)
    start, end = date(2025, 1, 6), date(2025, 1, 31)
    sessions = regular_sessions(date(2024, 1, 2), end).to_pylist()
    symbols = ("ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "SPY", "QQQ")
    captures = []
    for i, week in enumerate(weekly_schedule(start, end)):
        for fund in ("SPY", "QQQ"):
            if missing and fund == "QQQ":
                continue
            members = ["ALPHA", "BETA", "GAMMA"] if i < 2 else ["DELTA", "EPSILON", "BETA"]
            body = json.dumps(
                {"fund": fund, "as_of": week["price_as_of"].isoformat(), "members": members}
            ).encode()
            captures.append(
                {
                    "fund": fund,
                    "source_kind": "synthetic",
                    "url": "synthetic:weekly_test",
                    "known_by": week["decision_at"],
                    "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
                    "archive_sha1": None,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "body": body,
                }
            )
    pq.write_table(
        pa.Table.from_pylist(captures, schema=CATALOG_SCHEMA),
        root / "catalog.parquet",
        compression="zstd",
    )
    source_rows = []
    for j, symbol in enumerate(symbols):
        rows = []
        previous = 30.0 + j * 10
        for i, session in enumerate(sessions):
            previous *= (
                1
                + (0.0002 if symbol in {"SPY", "QQQ"} else 0.002 + j * 0.0001)
                + 0.001 * math.sin(i * (0.3 + j * 0.4))
            )
            factor = 2 if symbol == "ALPHA" and session["date"] >= date(2025, 1, 13) else 1
            price = D(str(previous / factor)).quantize(D(".000001"))
            values = {
                "date": session["date"],
                "open": price,
                "close": price,
                "high": price + D(".1"),
                "low": price - D(".1"),
                "volume": 10000000,
            }
            rows.append(
                {
                    **values,
                    "symbol": symbol,
                    "split_ratio": 2
                    if symbol == "ALPHA" and session["date"] == date(2025, 1, 13)
                    else 1,
                    "dividend": D(0),
                    "dividend_pay_date": None,
                }
            )
            source_rows.append(
                {
                    **values,
                    "instrument": symbol,
                    "available_at": session["close_at"],
                    "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
                }
            )
        pq.write_table(
            pa.Table.from_pylist(
                rows,
                schema=BAR_SCHEMA.with_metadata(
                    {**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"}
                ),
            ),
            root / f"{symbol}.parquet",
            compression="zstd",
        )
    create_snapshot(
        pa.Table.from_pylist(source_rows, schema=RESEARCH_BARS),
        pa.Table.from_pylist(
            [
                {
                    "instrument": s,
                    "symbol": s,
                    "start": sessions[0]["date"],
                    "end": end,
                    "available_at": sessions[0]["open_at"],
                }
                for s in symbols
            ],
            schema=UNIVERSE,
        ),
        root / "snapshot",
        SnapshotSpec("synthetic", "weekly_test", "raw", "shares", "synthetic"),
        allow_exploratory=True,
    )
    funnel = (
        Path("configs/spy-funnel.toml").read_text().replace("min_score = 70.0", "min_score = 1.0")
    )
    (root / "funnel.toml").write_text(funnel)
    config = root / "config.toml"
    config.write_text(
        f"""catalog = "catalog.parquet"
funnel = "funnel.toml"
start = {start}
end = {end}
initial_cash = "5000"
synthetic = true
free_only = true
history_status = "known_history"
max_membership_age = 3
snapshot = "snapshot"
[policy]
allow_exploratory = true
allocation = "0.75"
position_cap = "0.25"
commission = "1"
slippage_bps = "5"
exit_mode = "protective"
sale_proceeds = "next_session"
participation = "0.01"
[execution]
"""
        + "\n".join(f'{s} = "{s}.parquet"' for s in symbols)
        + "\n"
    )
    return config


def test_missing_membership_produces_no_returns_or_mutation(tmp_path: Path) -> None:
    path = weekly_inputs(tmp_path / "inputs", missing=True)
    before = {p: p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    output = tmp_path / "blocked"
    result = run_weekly_study(path, output)
    assert result["status"] == "blocked" and result["ready_weeks"] == 0
    assert not (output / "metrics.parquet").exists()
    assert result["executed_paths"] == 0
    assert verify_weekly_study(output)["study_status"] == "blocked"
    assert all(p.read_bytes() == body for p, body in before.items())
    with pytest.raises(FileExistsError):
        run_weekly_study(path, output)
    with pytest.raises(ValueError, match="scope"):
        read_membership_catalog(path.parent / "catalog.parquet")


def test_weekly_pipeline_replays_splits_and_continuous_accounts(tmp_path: Path) -> None:
    path = weekly_inputs(tmp_path / "inputs")
    output = tmp_path / "study"
    result = run_weekly_study(path, output)
    assert result["status"] == "completed" and result["executed_paths"] == 6
    assert verify_weekly_study(output)["tables"] > 70
    assert not (output / "factor_pool.parquet").exists()
    ranks = pq.read_table(output / "weekly_rankings.parquet").to_pylist()
    assert len({r["week"] for r in ranks}) == 4 and not any(r["trade_eligible"] for r in ranks)
    a = pq.read_table(output / "rank_rotation_fills.parquet").to_pylist()
    b = pq.read_table(output / "hold_until_exit_fills.parquet").to_pylist()
    assert any(r["reason"] == "rank_exit" for r in a)
    assert not any(r["reason"] == "rank_exit" for r in b)
    assert all(r["date"] > r["decision_date"] for r in [*a, *b])
    assert all(r["cash_after"] >= 0 for r in [*a, *b])
    costs = pq.read_table(output / "costs.parquet").to_pylist()
    assert all(r["commission"] > 0 and r["slippage_cost"] > 0 for r in costs)


def test_split_features_are_causal_and_future_members_do_not_change_past(tmp_path: Path) -> None:
    config = load_config(weekly_inputs(tmp_path / "inputs"))
    assert config.snapshot is not None
    raw = load_snapshot(config.snapshot)
    execution = {s: pq.read_table(p) for s, p in config.execution.items()}
    adjusted = adjusted_snapshot(raw, execution, tmp_path / "adjusted")
    rows = [r for r in adjusted.bars.to_pylist() if r["instrument"] == "ALPHA"]
    split = next(i for i, r in enumerate(rows) if r["date"] == date(2025, 1, 13))
    assert 0.99 < float(rows[split]["close"] / rows[split - 1]["close"]) < 1.01
    assert adjusted.bars.to_pylist()[0]["close"] == raw.bars.to_pylist()[0]["close"]
    _, members = membership_coverage(
        read_membership_catalog(config.catalog, synthetic=True), config.start, config.end
    )
    from invest.stock_funnel import load_funnel_config

    original, _, tables = weekly_frames(
        raw, adjusted, members, config.start, config.end, load_funnel_config(config.funnel)
    )
    altered = [
        {**r, "instrument": "GAMMA", "symbol": "GAMMA"} if r["instrument"] == "DELTA" else r
        for r in members.to_pylist()
    ]
    changed, _, newer = weekly_frames(
        raw,
        adjusted,
        pa.Table.from_pylist(altered, schema=members.schema),
        config.start,
        config.end,
        load_funnel_config(config.funnel),
    )
    assert original.table.equals(changed.table)
    assert [r for r in tables["weekly_rankings"].to_pylist() if r["week"] <= "2025-W03"] == [
        r for r in newer["weekly_rankings"].to_pylist() if r["week"] <= "2025-W03"
    ]


def test_missing_member_and_unresolved_event_remain_explicit_exclusions(tmp_path: Path) -> None:
    config = load_config(weekly_inputs(tmp_path / "inputs"))
    assert config.snapshot is not None
    raw = load_snapshot(config.snapshot)
    execution = {s: pq.read_table(p) for s, p in config.execution.items()}
    adjusted = adjusted_snapshot(raw, execution, tmp_path / "adjusted")
    _, members = membership_coverage(
        read_membership_catalog(config.catalog, synthetic=True), config.start, config.end
    )
    missing = [
        {**row, "instrument": "MISSING", "symbol": "MISSING"}
        for row in members.to_pylist()
        if row["instrument"] == "ALPHA"
    ]
    extended = pa.Table.from_pylist([*members.to_pylist(), *missing], schema=members.schema)
    from invest.stock_funnel import load_funnel_config

    frame, _, output = weekly_frames(
        raw,
        adjusted,
        extended,
        config.start,
        config.end,
        load_funnel_config(config.funnel),
        allow_missing_members=True,
        blocked_history={"ALPHA": {date(2024, 12, 31)}},
    )
    assert "ALPHA" not in frame.table["instrument"].to_pylist()
    excluded = [
        row
        for row in output["weekly_rankings"].to_pylist()
        if row["instrument"] in {"ALPHA", "MISSING"}
    ]
    assert excluded and all(
        row["reason"] == "missing_or_unavailable_features" and not row["focus"] for row in excluded
    )


def test_freezing_parses_quoted_paths_and_replay_does_not_read_originals(tmp_path: Path) -> None:
    path = weekly_inputs(tmp_path / "inputs", missing=True)
    body = path.read_text()
    for key in ("catalog", "funnel", "snapshot", "ALPHA"):
        body = body.replace(f"{key} =", f'  "{key}" =')
    path.write_text(body)
    output = tmp_path / "study"
    run_weekly_study(path, output)
    frozen = load_config(output / "config.toml")
    assert frozen.snapshot is not None and frozen.snapshot.is_relative_to(output)
    assert all(
        p.is_relative_to(output)
        for p in (frozen.catalog, frozen.funnel, *frozen.execution.values())
    )
    path.parent.rename(tmp_path / "moved_inputs")
    assert verify_weekly_study(output)["study_status"] == "blocked"


def test_direct_capture_cannot_backdate_and_archive_digest_must_match(tmp_path: Path) -> None:
    path = weekly_inputs(tmp_path / "inputs", missing=True)
    catalog = path.parent / "catalog.parquet"
    row = pq.read_table(catalog).to_pylist()[0]
    row.update(source_kind="issuer_capture", url="https://www.ssga.com/example.xlsx")
    pq.write_table(pa.Table.from_pylist([row], schema=CATALOG_SCHEMA), catalog, compression="zstd")
    with pytest.raises(ValueError, match="backdate"):
        read_membership_catalog(catalog)
    row.update(
        source_kind="issuer_archive",
        archive_sha1="incorrect",
        url="https://web.archive.org/web/20250105020000if_/https://www.ssga.com/example.xlsx",
    )
    pq.write_table(pa.Table.from_pylist([row], schema=CATALOG_SCHEMA), catalog, compression="zstd")
    with pytest.raises(ValueError, match="capture evidence disagree"):
        read_membership_catalog(catalog)
