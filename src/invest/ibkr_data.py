"""Typed IBKR capture batches; adjusted bars deliberately are not invest.bars.v1."""

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa

from invest.engine import engine_digest
from invest.ibkr_models import BrokerSnapshot, IBKRConfig, decimal, timestamp
from invest.ibkr_store import encode, publish
from invest.quality import latest_completed_session, regular_sessions

AMOUNT = pa.decimal128(38, 18)
TIME = pa.timestamp("us", tz="UTC")


def schema(name: str, fields: list[tuple[str, Any]]) -> pa.Schema:
    return pa.schema(fields, metadata={b"schema_version": f"invest.ibkr.{name}.v1".encode()})


SCHEMAS = {
    "raw": schema(
        "decoded-responses",
        [
            ("method", pa.string()),
            ("started_at", TIME),
            ("received_at", TIME),
            ("complete", pa.bool_()),
            ("payload", pa.binary()),
        ],
    ),
    "contracts": schema(
        "contracts",
        [
            ("con_id", pa.int64()),
            ("symbol", pa.string()),
            ("security_type", pa.string()),
            ("currency", pa.string()),
            ("exchange", pa.string()),
            ("primary_exchange", pa.string()),
            ("min_tick", AMOUNT),
        ],
    ),
    "account_values": schema(
        "account-values",
        [
            ("account", pa.string()),
            ("tag", pa.string()),
            ("value", pa.string()),
            ("currency", pa.string()),
            ("model_code", pa.string()),
        ],
    ),
    "positions": schema(
        "positions",
        [
            ("account", pa.string()),
            ("con_id", pa.int64()),
            ("symbol", pa.string()),
            ("currency", pa.string()),
            ("quantity", AMOUNT),
            ("average_cost", AMOUNT),
        ],
    ),
    "orders": schema(
        "orders",
        [
            ("account", pa.string()),
            ("client_id", pa.int64()),
            ("order_id", pa.int64()),
            ("perm_id", pa.int64()),
            ("order_ref", pa.string()),
            ("con_id", pa.int64()),
            ("symbol", pa.string()),
            ("currency", pa.string()),
            ("side", pa.string()),
            ("quantity", AMOUNT),
            ("limit_price", AMOUNT),
            ("order_type", pa.string()),
            ("status", pa.string()),
            ("filled", AMOUNT),
            ("remaining", AMOUNT),
            ("rejected", pa.bool_()),
        ],
    ),
    "executions": schema(
        "executions",
        [
            ("exec_id", pa.string()),
            ("account", pa.string()),
            ("client_id", pa.int64()),
            ("order_id", pa.int64()),
            ("perm_id", pa.int64()),
            ("order_ref", pa.string()),
            ("con_id", pa.int64()),
            ("symbol", pa.string()),
            ("currency", pa.string()),
            ("side", pa.string()),
            ("quantity", AMOUNT),
            ("price", AMOUNT),
            ("trade_at", TIME),
        ],
    ),
    "commissions": schema(
        "commissions",
        [
            ("exec_id", pa.string()),
            ("currency", pa.string()),
            ("commission", AMOUNT),
        ],
    ),
    "historical": schema(
        "historical-bars",
        [
            ("con_id", pa.int64()),
            ("symbol", pa.string()),
            ("session", pa.date32()),
            ("bar_at", TIME),
            ("bar_size", pa.string()),
            ("what_to_show", pa.string()),
            ("price_basis", pa.string()),
            ("use_rth", pa.bool_()),
            ("currency", pa.string()),
            ("open", AMOUNT),
            ("high", AMOUNT),
            ("low", AMOUNT),
            ("close", AMOUNT),
            ("volume", AMOUNT),
            ("volume_unit", pa.string()),
        ],
    ),
    "quotes": schema(
        "quotes",
        [
            ("con_id", pa.int64()),
            ("symbol", pa.string()),
            ("currency", pa.string()),
            ("requested_type", pa.int64()),
            ("actual_type", pa.int64()),
            ("sdk_updated_at", TIME),
            ("exchange_trade_at", TIME),
            ("received_at", TIME),
            ("bid", AMOUNT),
            ("ask", AMOUNT),
            ("last", AMOUNT),
            ("bid_size", AMOUNT),
            ("ask_size", AMOUNT),
            ("last_size", AMOUNT),
        ],
    ),
    "quality": schema(
        "capture-quality",
        [
            ("status", pa.string()),
            ("check", pa.string()),
            ("symbol", pa.string()),
            ("detail", pa.string()),
        ],
    ),
    "capture": schema(
        "capture",
        [
            ("source", pa.string()),
            ("environment", pa.string()),
            ("account", pa.string()),
            ("captured_at", TIME),
            ("client_id", pa.int64()),
            ("complete", pa.bool_()),
            ("sdk_version", pa.string()),
            ("server_version", pa.int64()),
            ("execution_scope", pa.string()),
            ("raw_level", pa.string()),
            ("legacy_engine_admitted", pa.bool_()),
            ("engine_sha256", pa.string()),
        ],
    ),
}


@dataclass
class Capture:
    snapshot: BrokerSnapshot
    config: IBKRConfig
    contracts: list[dict[str, Any]] = field(default_factory=list)
    historical: list[dict[str, Any]] = field(default_factory=list)
    quotes: list[dict[str, Any]] = field(default_factory=list)
    raw: list[dict[str, Any]] = field(default_factory=list)
    sdk_version: str = "synthetic"
    server_version: int = 0
    errors: list[str] = field(default_factory=list)


def quality(capture: Capture) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(status: str, check: str, symbol: str, detail: str) -> None:
        rows.append(dict(status=status, check=check, symbol=symbol, detail=detail))

    snap, config = capture.snapshot, capture.config
    if capture.errors:
        add("error", "capture_requests", "", "; ".join(capture.errors))
    if any(
        row["method"] == "errorEvent" and json.loads(row["payload"]).get("code") == 2119
        for row in capture.raw
    ):
        add(
            "warning",
            "market_data_farm_startup",
            "",
            "IBKR reported farm startup; returned quotes and history are checked independently",
        )
    if snap.source not in {"ibkr", "synthetic"} or not snap.account.startswith("DU"):
        raise ValueError("IBKR captures require a Paper account and explicit source")
    if not snap.complete:
        add("error", "snapshot_complete", "", "; ".join(snap.errors))
    if snap.cash() is None:
        add("error", "usd_cash", "", "No USD TotalCashValue response")
    for symbol in config.symbols:
        contracts = [r for r in capture.contracts if r["symbol"] == symbol]
        if (
            len(contracts) != 1
            or contracts[0]["currency"] != "USD"
            or (contracts[0]["security_type"] != "STK" or contracts[0]["con_id"] <= 0)
        ):
            add("error", "qualified_contract", symbol, "One qualified USD stock/ETF is required")
        quotes = [r for r in capture.quotes if r["symbol"] == symbol]
        if len(quotes) != 1 or quotes[0]["actual_type"] not in {1, 2, 3, 4}:
            add("error", "quote_type", symbol, "Actual callback market data type is missing")
        elif all(quotes[0][name] is None for name in ("bid", "ask", "last")):
            add("error", "quote_available", symbol, "No quote received; no price fallback used")
        elif quotes[0]["actual_type"] != 1:
            add(
                "warning",
                "quote_delayed_or_frozen",
                symbol,
                f"Actual data type {quotes[0]['actual_type']}; not live market data",
            )
        bars = [r for r in capture.historical if r["symbol"] == symbol]
        if not bars:
            add("error", "historical_available", symbol, "No historical bars received")
            continue
        if len(contracts) == 1 and any(
            row["con_id"] != contracts[0]["con_id"] for row in [*bars, *quotes]
        ):
            add(
                "error", "contract_identity", symbol, "Response contract differs from qualification"
            )
        seen: set[tuple[date, datetime | None]] = set()
        for bar in bars:
            key = (bar["session"], bar["bar_at"])
            if key in seen:
                add("error", "duplicate_bar", symbol, str(key))
            seen.add(key)
            low, high = decimal(bar["low"]), decimal(bar["high"])
            if (
                not 0
                < low
                <= min(decimal(bar["open"]), decimal(bar["close"]))
                <= max(decimal(bar["open"]), decimal(bar["close"]))
                <= high
                or decimal(bar["volume"]) < 0
            ):
                add("error", "ohlcv", symbol, str(key))
        if config.bar_size == "1 day":
            start, end = min(r["session"] for r in bars), max(r["session"] for r in bars)
            expected = {r["date"] for r in regular_sessions(start, end).to_pylist()}
            actual = {r["session"] for r in bars}
            if expected != actual:
                add("error", "daily_sessions", symbol, "Missing or unexpected XNYS sessions")
            latest = latest_completed_session(snap.captured_at)
            if end < latest:
                add("error", "stale_daily", symbol, f"Last {end}; latest completed {latest}")
            if any(
                r["close_at"] > snap.captured_at for r in regular_sessions(start, end).to_pylist()
            ):
                add("warning", "unfinished_daily", symbol, "Capture includes an unfinished session")
        else:
            minutes = {"1 min": 1, "5 mins": 5, "15 mins": 15, "1 hour": 60}[config.bar_size]
            start, end = min(r["session"] for r in bars), max(r["session"] for r in bars)
            sessions = {r["date"]: r for r in regular_sessions(start, end).to_pylist()}
            ends = []
            for bar in bars:
                at = bar["bar_at"]
                session = sessions.get(bar["session"])
                if (
                    at is None
                    or timestamp(at).astimezone(ZoneInfo("America/New_York")).date()
                    != bar["session"]
                ):
                    add(
                        "error",
                        "intraday_timestamp",
                        symbol,
                        "Missing or inconsistent UTC bar start",
                    )
                    continue
                at = timestamp(at)
                if config.use_rth and (
                    session is None or not session["open_at"] <= at < session["close_at"]
                ):
                    add("error", "intraday_session", symbol, str(at))
                    continue
                close_at = at + timedelta(minutes=minutes)
                if config.use_rth and session:
                    close_at = min(close_at, session["close_at"])
                ends.append(close_at)
                if close_at > snap.captured_at:
                    add("warning", "unfinished_intraday", symbol, str(at))
            latest = latest_completed_session(snap.captured_at)
            expected_close = regular_sessions(latest, latest).to_pylist()[0]["close_at"]
            if ends and max(ends) < expected_close:
                add("error", "stale_intraday", symbol, "Missing the latest completed session close")
    add("warning", "price_basis", "", "IBKR adjusted bars are not admitted as legacy raw bars")
    add("warning", "corporate_actions", "", "Ex/pay dates and complete split history not captured")
    add("warning", "volume_unit", "", "Provider-reported volume; gateway volume setting unverified")
    add(
        "warning",
        "snapshot_timing",
        "",
        "Account and position requests are not atomic broker reads",
    )
    return rows


def save_capture(capture: Capture, output: Path) -> Path:
    checks = quality(capture)
    snapshot = capture.snapshot
    now = timestamp(snapshot.captured_at)
    output.mkdir(parents=True, exist_ok=True)
    name = now.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
    staging, destination = output / ("." + name + ".tmp"), output / name
    staging.mkdir()
    metadata = {
        b"source": snapshot.source.encode(),
        b"environment": b"paper",
        b"account": snapshot.account.encode(),
        b"captured_at": now.isoformat().encode(),
    }
    values: dict[str, list[dict[str, Any]]] = {
        "raw": capture.raw,
        "contracts": capture.contracts,
        "account_values": snapshot.account_values,
        "positions": snapshot.positions,
        "orders": snapshot.orders,
        "executions": snapshot.executions,
        "commissions": snapshot.commissions,
        "historical": capture.historical,
        "quotes": capture.quotes,
        "quality": checks,
        "capture": [
            {
                "source": snapshot.source,
                "environment": "paper",
                "account": snapshot.account,
                "captured_at": now,
                "client_id": capture.config.client_id,
                "complete": not any(r["status"] == "error" for r in checks),
                "sdk_version": capture.sdk_version,
                "server_version": capture.server_version,
                "execution_scope": "IBKR API available execution history; absence is not proof",
                "raw_level": "SDK-decoded responses, not TCP wire frames",
                "legacy_engine_admitted": False,
                "engine_sha256": engine_digest(),
            }
        ],
    }
    try:
        for key, rows in values.items():
            spec = SCHEMAS[key].with_metadata({**(SCHEMAS[key].metadata or {}), **metadata})
            publish(pa.Table.from_pylist(rows, schema=spec), staging / f"{key}.parquet")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def decoded(method: str, started: datetime, body: Any, *, complete: bool = True) -> dict[str, Any]:
    return {
        "method": method,
        "started_at": timestamp(started),
        "received_at": datetime.now(UTC),
        "complete": complete,
        "payload": encode(body),
    }


def snapshot_payload(snapshot: BrokerSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def snapshot_from_payload(payload: dict[str, Any]) -> BrokerSnapshot:
    values = dict(payload)
    values["captured_at"] = timestamp(values["captured_at"])
    return BrokerSnapshot(**values)
