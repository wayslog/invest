"""IBKR Paper contracts. Prices/cash are USD Decimal; event times are UTC."""

import math
import re
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from invest.quality import regular_sessions


def timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("IBKR timestamps must include a timezone")
    return result.astimezone(UTC)


def number(value: Any, *, optional: bool = False) -> Decimal | None:
    """Preserve SDK decimal/string precision; unset/nonfinite SDK values stay missing."""
    if value is None or isinstance(value, bool):
        if optional:
            return None
        raise ValueError("Missing or invalid IBKR numeric value")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid IBKR numeric value") from exc
    if not result.is_finite() or abs(result) >= Decimal("1e20"):
        if optional:
            return None
        raise ValueError("Nonfinite/unset/out-of-range IBKR numeric value")
    if int(result.normalize(context=Context(prec=50)).as_tuple().exponent) < -18:
        raise ValueError("IBKR value exceeds the supported 18 decimal places; no rounding")
    return result


def decimal(value: Any) -> Decimal:
    result = number(value)
    assert result is not None
    return result


@dataclass(frozen=True)
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 72
    account: str = ""
    timeout: float = 15
    symbols: tuple[str, ...] = ("SPY", "XLF")
    duration: str = "1 Y"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = True
    market_data_type: int = 3
    quote_wait: float = 3
    max_order_notional: Decimal = Decimal("1000")
    max_total_notional: Decimal = Decimal("5000")

    def __post_init__(self) -> None:
        if not self.host.strip() or not 1 <= self.port <= 65535 or self.client_id < 1:
            raise ValueError("Set a valid gateway host/port and a nonzero dedicated client_id")
        if self.account and not self.account.startswith("DU"):
            raise ValueError("M4 supports IBKR Paper accounts only")
        if not all(math.isfinite(v) and 0 < v <= 120 for v in (self.timeout, self.quote_wait)):
            raise ValueError("Timeout and quote_wait must be finite and in (0, 120]")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Provide unique IBKR symbols")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9.]{0,14}", s) for s in self.symbols):
            raise ValueError("Invalid stock/ETF symbol")
        if not re.fullmatch(r"[1-9][0-9]* [DWMY]", self.duration):
            raise ValueError("Historical duration must use D/W/M/Y, e.g. '1 Y'")
        if self.bar_size not in {"1 day", "1 min", "5 mins", "15 mins", "1 hour"}:
            raise ValueError("Unsupported IBKR historical bar size")
        if self.what_to_show not in {"TRADES", "ADJUSTED_LAST"}:
            raise ValueError("Explicit TRADES or ADJUSTED_LAST price basis required")
        if self.market_data_type not in {1, 2, 3, 4} or not isinstance(self.use_rth, bool):
            raise ValueError("Invalid market_data_type or use_rth")
        order_cap, total_cap = decimal(self.max_order_notional), decimal(self.max_total_notional)
        if not Decimal(0) < order_cap <= total_cap:
            raise ValueError("Invalid Paper execution notional limits")
        decimal(self.max_order_notional)
        decimal(self.max_total_notional)


def read_config(path: Path) -> IBKRConfig:
    values = tomllib.loads(path.read_text(encoding="utf-8"))
    allowed = set(IBKRConfig.__dataclass_fields__)
    if set(values) - allowed:
        raise ValueError("Unknown IBKR configuration fields")
    if "symbols" in values:
        values["symbols"] = tuple(values["symbols"])
    for key in ("max_order_notional", "max_total_notional"):
        if key in values:
            values[key] = decimal(values[key])
    return IBKRConfig(**values)


@dataclass(frozen=True)
class Intent:
    intent_id: str
    account: str
    client_id: int
    con_id: int
    symbol: str
    side: str
    quantity: int
    limit_price: Decimal
    decision_session: date
    decision_at: datetime
    valid_from: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", self.intent_id):
            raise ValueError("intent_id must be 1-40 letters, digits, underscores or hyphens")
        if not self.account.startswith("DU") or self.client_id < 1 or self.con_id <= 0:
            raise ValueError("Paper account, client and qualified contract are required")
        if self.side not in {"BUY", "SELL"} or type(self.quantity) is not int or self.quantity < 1:
            raise ValueError("Only positive whole-share BUY/SELL limit orders are supported")
        if decimal(self.limit_price) <= 0:
            raise ValueError("Limit price must be positive")
        times = tuple(timestamp(v) for v in (self.decision_at, self.valid_from, self.valid_until))
        if not times[0] < times[1] < times[2]:
            raise ValueError("A decision must precede the next session's execution window")
        schedule = regular_sessions(
            self.decision_session, self.decision_session + timedelta(days=10)
        )
        rows = schedule.to_pylist()
        if len(rows) < 2 or rows[0]["date"] != self.decision_session:
            raise ValueError("decision_session must be an XNYS trading session")
        if times[0] < rows[0]["close_at"] or times[1:] != (rows[1]["open_at"], rows[1]["close_at"]):
            raise ValueError("Use a completed decision session and the next XNYS regular session")

    @property
    def order_ref(self) -> str:
        return "invest-" + self.intent_id

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "Intent":
        row = dict(value)
        row["limit_price"] = decimal(row["limit_price"])
        row["decision_session"] = date.fromisoformat(str(row["decision_session"]))
        for key in ("decision_at", "valid_from", "valid_until"):
            row[key] = timestamp(row[key])
        return cls(**row)


def create_intent(
    intent_id: str,
    account: str,
    client_id: int,
    con_id: int,
    symbol: str,
    side: str,
    quantity: int,
    limit_price: Decimal,
    decision_session: date,
    at: datetime,
) -> Intent:
    rows = regular_sessions(decision_session, decision_session + timedelta(days=10)).to_pylist()
    if len(rows) < 2:
        raise ValueError("No next XNYS execution session")
    return Intent(
        intent_id,
        account,
        client_id,
        con_id,
        symbol,
        side,
        quantity,
        limit_price,
        decision_session,
        timestamp(at),
        rows[1]["open_at"],
        rows[1]["close_at"],
    )


@dataclass
class BrokerSnapshot:
    source: str
    account: str
    captured_at: datetime
    account_values: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    commissions: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = True
    errors: list[str] = field(default_factory=list)

    def cash(self, tag: str = "TotalCashValue") -> Decimal | None:
        matches = [
            r
            for r in self.account_values
            if r["account"] == self.account
            and r["tag"] == tag
            and r["currency"] == "USD"
            and not r.get("model_code")
        ]
        values = {decimal(r["value"]) for r in matches}
        if len(values) > 1:
            raise ValueError("Conflicting IBKR account cash values")
        return next(iter(values), None)

    def position_quantities(self) -> dict[int, Decimal]:
        result: dict[int, Decimal] = {}
        for row in self.positions:
            if row["account"] == self.account:
                con_id = int(row["con_id"])
                if con_id in result:
                    raise ValueError("Duplicate IBKR account position")
                result[con_id] = decimal(row["quantity"])
        return result


class PaperBroker(Protocol):
    source: str
    account: str
    client_id: int

    def snapshot(self) -> BrokerSnapshot: ...
    def reserve_order_id(self) -> int: ...
    def submit(self, intent: Intent, order_id: int) -> None: ...
    def cancel(self, intent: Intent, order_id: int) -> None: ...
