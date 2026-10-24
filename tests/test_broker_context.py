"""IBKR 只读账户桥接的合成证据；不联系券商，不写历史状态。"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.broker_context import adapt_broker_context
from invest.contracts import (
    AccountSnapshot,
    Holding,
    PendingOrder,
    PositionState,
    Quote,
    StrategyState,
)
from invest.decision_io import decision_contexts, read_decision_contexts
from invest.ibkr_data import SCHEMAS
from invest.quality import regular_sessions
from invest.research_data import digest
from tests.test_factor_mining import research_snapshot


def broker_evidence(
    root: Path, account: AccountSnapshot, state: StrategyState, metadata: dict[bytes, bytes]
) -> tuple[Path, Path]:
    capture = root / "capture"
    capture.mkdir()
    at = regular_sessions(account.as_of, account.as_of)["close_at"][0].as_py() + timedelta(
        minutes=30
    )
    broker = "DU_SYNTHETIC_TEST"
    identifiers = {
        int(quote.instrument.removeprefix("IBKR")): quote.instrument for quote in account.quotes
    }
    values = [
        {
            "account": broker,
            "tag": tag,
            "value": str(value),
            "currency": "USD" if tag != "AccountType" else "",
            "model_code": "",
        }
        for tag, value in (
            ("AccountType", "CASH"),
            ("TotalCashValue", account.cash),
            ("SettledCash", account.cash - account.unsettled_cash),
            ("AccruedDividend", account.receivables),
        )
    ]
    rows: dict[str, list[dict[str, Any]]] = {
        "raw": [
            {
                "method": method,
                "started_at": at - timedelta(minutes=10),
                "received_at": at - timedelta(minutes=5),
                "complete": True,
                "payload": b"[]",
            }
            for method in ("reqAccountUpdates", "reqPositions", "reqAllOpenOrders", "reqExecutions")
        ],
        "capture": [
            {
                "source": "synthetic",
                "environment": "paper",
                "account": broker,
                "captured_at": at,
                "complete": True,
            }
        ],
        "contracts": [
            {
                "con_id": number,
                "symbol": symbol,
                "security_type": "STK",
                "currency": "USD",
                "exchange": "SMART",
                "primary_exchange": "NYSE",
                "min_tick": Decimal(".01"),
            }
            for number, symbol in identifiers.items()
        ],
        "account_values": values,
        "positions": [
            {
                "account": broker,
                "con_id": int(h.instrument.removeprefix("IBKR")),
                "symbol": h.instrument,
                "currency": "USD",
                "quantity": h.shares,
                "average_cost": h.entry,
            }
            for h in account.holdings
        ],
        "orders": [
            {
                "account": broker,
                "con_id": int(p.instrument.removeprefix("IBKR")),
                "symbol": p.instrument,
                "currency": "USD",
                "client_id": 70,
                "order_id": index,
                "perm_id": index,
                "order_ref": f"pending_{index}",
                "side": p.side.upper(),
                "quantity": p.quantity + 2,
                "filled": 2,
                "remaining": p.quantity,
                "limit_price": p.reference_price,
                "order_type": "LMT",
                "status": "PendingCancel",
                "rejected": False,
            }
            for index, p in enumerate(account.pending, 1)
        ],
    }
    for name, schema in SCHEMAS.items():
        table = pa.Table.from_pylist(
            rows.get(name, []),
            schema=schema.with_metadata(
                {
                    **(schema.metadata or {}),
                    b"source": b"synthetic",
                    b"environment": b"paper",
                    b"account": broker.encode(),
                    b"captured_at": at.isoformat().encode(),
                }
            ),
        )
        pq.write_table(table, capture / f"{name}.parquet", compression="zstd")
    path = root / "state.parquet"
    table = decision_contexts(((account, state),))
    pq.write_table(
        table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                **metadata,
                b"context_kind": b"account_state",
                b"broker_account": broker.encode(),
                b"environment": b"paper",
                b"source_ref": b"synthetic_persistent_state_fixture",
            }
        ),
        path,
        compression="zstd",
    )
    return capture, path


def broker_case(root: Path) -> tuple[Path, Path, Path, date]:
    data = research_snapshot(root, instrument_prefix="IBKR")
    day = data.calendar["date"][120].as_py()
    quotes = tuple(
        Quote(instrument, Decimal(100)) for instrument in data.universe["instrument"].to_pylist()
    )
    account = AccountSnapshot(
        "existing_identity",
        data.snapshot_id,
        "synthetic",
        day,
        Decimal(5000),
        Decimal(4200),
        quotes,
        (Holding("IBKR1", 8, Decimal(100), Decimal("1.25")),),
        (PendingOrder("IBKR2", "buy", 3, Decimal(100)),),
        Decimal(10),
        Decimal(200),
        "paused",
    )
    state = StrategyState(
        Decimal(7000),
        "halted",
        day,
        data.calendar["date"][119].as_py(),
        (PositionState("IBKR1", data.calendar["date"][90].as_py(), Decimal(130), "trailing_stop"),),
        (("IBKR3", data.calendar["date"][118].as_py()),),
    )
    capture, path = broker_evidence(
        root,
        account,
        state,
        {b"policy_id": b"fixed_policy", b"pool_id": b"fixed_pool", b"price_basis": b"raw"},
    )
    return capture, path, data.directory, day


def test_broker_context_preserves_decimal_capital_risk_and_uncancelled_budget(
    tmp_path: Path,
) -> None:
    capture, path, snapshot, day = broker_case(tmp_path)
    before = {p: digest(p) for p in tmp_path.rglob("*.parquet")}
    original, original_state = read_decision_contexts(pq.read_table(path))[0]
    table = adapt_broker_context(capture, path, snapshot, day)
    adapted, state = read_decision_contexts(table)[0]
    assert state == original_state
    assert replace(adapted, quotes=original.quotes) == original
    assert adapted.pending[0].quantity == 3
    assert adapted.unsettled_cash == Decimal(200) and adapted.receivables == Decimal(10)
    assert (table.schema.metadata or {})[b"context_kind"] == b"broker_capture"
    assert all(digest(p) == value for p, value in before.items())


@pytest.mark.parametrize("entry", [Decimal(301) / 3, Decimal("100.1234567890123456789012345")])
def test_broker_average_cost_rounding_preserves_exact_ledger_entry(
    tmp_path: Path, entry: Decimal
) -> None:
    capture, path, snapshot, day = broker_case(tmp_path)
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["holdings"][0]["entry"] = str(entry)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path, compression="zstd")
    positions = pq.read_table(capture / "positions.parquet")
    rows = positions.to_pylist()
    # 模拟 SDK 的二进制浮点均价；权威账本仍保存未舍入的 Decimal。
    rows[0]["average_cost"] = Decimal(str(float(entry)))
    pq.write_table(
        pa.Table.from_pylist(rows, schema=positions.schema),
        capture / "positions.parquet",
        compression="zstd",
    )
    before = {p: digest(p) for p in (path, *capture.glob("*.parquet"))}
    original, original_state = read_decision_contexts(pq.read_table(path))[0]
    adapted, state = read_decision_contexts(adapt_broker_context(capture, path, snapshot, day))[0]
    assert adapted.holdings[0].entry == entry
    assert replace(adapted, quotes=original.quotes) == original and state == original_state
    assert all(digest(p) == value for p, value in before.items())


@pytest.mark.parametrize(
    "difference,accepted",
    [
        (Decimal(".000001"), True),
        (Decimal("-.000001"), True),
        (Decimal(".000001000000001"), False),
        (Decimal("-.000001000000001"), False),
    ],
)
def test_broker_cost_tolerance_has_fixed_absolute_boundary(
    tmp_path: Path, difference: Decimal, accepted: bool
) -> None:
    capture, path, snapshot, day = broker_case(tmp_path)
    positions = pq.read_table(capture / "positions.parquet")
    rows = positions.to_pylist()
    rows[0]["average_cost"] += difference
    pq.write_table(
        pa.Table.from_pylist(rows, schema=positions.schema),
        capture / "positions.parquet",
        compression="zstd",
    )
    if accepted:
        account, _ = read_decision_contexts(adapt_broker_context(capture, path, snapshot, day))[0]
        assert account.holdings[0].entry == Decimal(100)
    else:
        with pytest.raises(ValueError, match="cost anchors disagree"):
            adapt_broker_context(capture, path, snapshot, day)


@pytest.mark.parametrize("average_cost", [Decimal(0), Decimal("-.0000001")])
def test_cost_tolerance_does_not_admit_nonpositive_broker_cost(
    tmp_path: Path, average_cost: Decimal
) -> None:
    capture, path, snapshot, day = broker_case(tmp_path)
    saved = pq.read_table(path)
    rows = saved.to_pylist()
    rows[0]["holdings"][0]["entry"] = "0.0000001"
    pq.write_table(pa.Table.from_pylist(rows, schema=saved.schema), path, compression="zstd")
    positions = pq.read_table(capture / "positions.parquet")
    rows = positions.to_pylist()
    rows[0]["average_cost"] = average_cost
    pq.write_table(
        pa.Table.from_pylist(rows, schema=positions.schema),
        capture / "positions.parquet",
        compression="zstd",
    )
    with pytest.raises(ValueError, match="cost anchors disagree"):
        adapt_broker_context(capture, path, snapshot, day)


@pytest.mark.parametrize("status", ["Filled", "Cancelled", "ApiCancelled"])
def test_terminal_order_outside_current_universe_does_not_block_context(
    tmp_path: Path, status: str
) -> None:
    capture, path, snapshot, day = broker_case(tmp_path)
    expected = adapt_broker_context(capture, path, snapshot, day)
    orders = pq.read_table(capture / "orders.parquet")
    rows = orders.to_pylist()
    rows.append(
        {
            **rows[0],
            "con_id": 999,
            "symbol": "OLD",
            "order_id": 999,
            "perm_id": 999,
            "status": status,
            "filled": Decimal(5) if status == "Filled" else Decimal(2),
            "remaining": Decimal(0) if status == "Filled" else Decimal(3),
        }
    )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=orders.schema),
        capture / "orders.parquet",
        compression="zstd",
    )
    before = {p: digest(p) for p in (path, *capture.glob("*.parquet"))}
    adapted = adapt_broker_context(capture, path, snapshot, day)
    assert read_decision_contexts(adapted) == read_decision_contexts(expected)
    assert (adapted.schema.metadata or {})[b"broker_capture_id"] != (
        expected.schema.metadata or {}
    )[b"broker_capture_id"]
    assert all(digest(p) == value for p, value in before.items())


@pytest.mark.parametrize("status", ["Filled", "Submitted", "PendingCancel", "Inactive"])
def test_unresolved_order_outside_current_universe_is_still_rejected(
    tmp_path: Path, status: str
) -> None:
    capture, path, snapshot, day = broker_case(tmp_path)
    orders = pq.read_table(capture / "orders.parquet")
    rows = orders.to_pylist()
    rows[0].update(con_id=999, symbol="OLD", status=status)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=orders.schema),
        capture / "orders.parquet",
        compression="zstd",
    )
    message = "Filled broker order has remaining" if status == "Filled" else "qualified USD stock"
    with pytest.raises(ValueError, match=message):
        adapt_broker_context(capture, path, snapshot, day)


@pytest.mark.parametrize(
    "failure",
    [
        "cash",
        "settlement",
        "dividend",
        "account",
        "currency",
        "quantity",
        "cost",
        "pending",
        "duplicate",
        "order_type",
        "stale",
        "incomplete",
        "preview",
        "unknown_state",
        "source",
        "metadata",
        "missing_query",
        "late_query",
        "after_close_fill",
    ],
)
def test_broker_context_rejects_unreconciled_or_unsupported_evidence(
    tmp_path: Path, failure: str
) -> None:
    capture, path, snapshot, day = broker_case(tmp_path)
    name = {
        "quantity": "positions",
        "cost": "positions",
        "currency": "positions",
        "pending": "orders",
        "duplicate": "orders",
        "order_type": "orders",
        "stale": "capture",
        "incomplete": "capture",
        "source": "capture",
        "metadata": "capture",
        "missing_query": "raw",
        "late_query": "raw",
        "after_close_fill": "executions",
    }.get(failure, "account_values")
    target = path if failure in {"preview", "unknown_state"} else capture / f"{name}.parquet"
    table = pq.read_table(target)
    rows = table.to_pylist()
    if failure in {"cash", "settlement", "dividend"}:
        tag = {
            "cash": "TotalCashValue",
            "settlement": "SettledCash",
            "dividend": "AccruedDividend",
        }[failure]
        rows = [r for r in rows if r["tag"] != tag]
    elif failure == "account":
        rows[0]["account"] = "DU_OTHER"
    elif failure == "currency":
        rows[0]["currency"] = "EUR"
    elif failure == "quantity":
        rows[0]["quantity"] = Decimal("1.5")
    elif failure == "cost":
        rows[0]["average_cost"] = Decimal(99)
    elif failure == "pending":
        rows[0]["remaining"] = Decimal(2)
    elif failure == "duplicate":
        rows.append(rows[0])
    elif failure == "order_type":
        rows[0]["order_type"] = "MKT"
    elif failure == "stale":
        rows[0]["captured_at"] -= timedelta(days=1)
    elif failure == "incomplete":
        rows[0]["complete"] = False
    elif failure == "source":
        rows[0]["source"] = "ibkr"
    elif failure == "unknown_state":
        rows[0]["positions"] = []
    elif failure == "missing_query":
        rows = rows[1:]
    elif failure == "late_query":
        rows[0]["received_at"] += timedelta(days=1)
    elif failure == "after_close_fill":
        rows = [
            {
                "account": "DU_SYNTHETIC_TEST",
                "trade_at": regular_sessions(day, day)["close_at"][0].as_py()
                + timedelta(seconds=1),
            }
        ]
    schema = table.schema
    if failure in {"preview", "metadata"}:
        schema = schema.with_metadata(
            {
                **(schema.metadata or {}),
                b"context_kind" if failure == "preview" else b"source": b"decision_preview",
            }
        )
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), target, compression="zstd")
    with pytest.raises(ValueError):
        adapt_broker_context(capture, path, snapshot, day)


def test_decide_freezes_and_replays_broker_evidence_without_writing_account(tmp_path: Path) -> None:
    from invest.decision_study import run_decision, verify_decision
    from tests.test_decision_study import decision_case

    study, config = decision_case(tmp_path, broker=True)
    context = pq.read_table(study / "decision_contexts.parquet")
    account, state = read_decision_contexts(context)[0]
    capture, state_path = broker_evidence(
        tmp_path, account, replace(state, last_session=account.as_of), context.schema.metadata or {}
    )
    config.write_text(
        config.read_text().replace(
            'context = "backtest/decision_contexts.parquet"', f'context = "{state_path.name}"'
        )
        + f'broker_capture = "{capture.name}"\n'
    )
    before = {p: digest(p) for p in (state_path, *capture.glob("*.parquet"))}
    result = run_decision(
        config, tmp_path / "decision", account.as_of, cache_root=tmp_path / "cache"
    )
    assert result.status == "completed"
    record = pq.read_table(result.directory / "run.parquet").to_pylist()[0]
    assert record["context_kind"] == "broker_capture" and record["broker_capture_id"]
    assert record["account_id"] == account.account_id and not record["account_eligible"]
    assert verify_decision(result.directory, cache_root=tmp_path / "cache")["status"] == "verified"
    assert all(digest(p) == value for p, value in before.items())
    from invest.research_artifacts import seal_artifacts

    run_table = pq.read_table(result.directory / "run.parquet")
    records = run_table.to_pylist()
    records[0]["source_ref"] = "unrelated_state"
    pq.write_table(
        pa.Table.from_pylist(records, schema=run_table.schema),
        result.directory / "run.parquet",
        compression="zstd",
    )
    seal_artifacts(result.directory)
    with pytest.raises(ValueError, match="context changed"):
        verify_decision(result.directory, cache_root=tmp_path / "cache")
    pq.write_table(run_table, result.directory / "run.parquet", compression="zstd")
    seal_artifacts(result.directory)
    table = pq.read_table(result.directory / "broker_capture" / "account_values.parquet")
    pq.write_table(
        table.slice(1),
        result.directory / "broker_capture" / "account_values.parquet",
        compression="zstd",
    )
    with pytest.raises(ValueError, match="artifact"):
        verify_decision(result.directory, cache_root=tmp_path / "cache")


def test_decision_registration_rejects_mixed_account_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import invest.decision_study as module
    from tests.test_decision_study import decision_case

    _, config = decision_case(tmp_path)
    spec = module.load_decision_config(config)
    original = pq.read_table(spec.context)
    exported = tmp_path / "exported-context.parquet"
    pq.write_table(original, exported, compression="zstd")
    config.write_text(
        config.read_text().replace(
            'context = "backtest/decision_contexts.parquet"',
            'context = "exported-context.parquet"',
        )
    )
    day = original["date"][0].as_py()
    read_context = module._context_table
    calls = 0

    def replace_after_first_read(settings: module.DecisionConfig, as_of: date) -> pa.Table:
        nonlocal calls
        table = read_context(settings, as_of)
        calls += 1
        if calls == 1:
            rows = table.to_pylist()
            for row in rows:
                row["account_id"] = "replaced_account"
            pq.write_table(
                pa.Table.from_pylist(rows, schema=table.schema),
                settings.context,
                compression="zstd",
            )
        return table

    monkeypatch.setattr(module, "_context_table", replace_after_first_read)
    with pytest.raises(ValueError, match="changed during freezing"):
        module.run_decision(config, tmp_path / "mixed", day, cache_root=tmp_path / "cache")
    assert pq.read_table(tmp_path / "mixed/run.parquet")["status"].to_pylist() == ["failed"]
    assert not (tmp_path / "mixed/actions.parquet").exists()
