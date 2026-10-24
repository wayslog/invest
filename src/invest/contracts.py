"""研究快照、因子和标签的统一表格契约。"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa

from invest.market import MONEY

AMOUNT = pa.decimal128(38, 18)
TIME = pa.timestamp("us", tz="UTC")


def research_schema(name: str, fields: list[tuple[str, pa.DataType]]) -> pa.Schema:
    return pa.schema(fields, metadata={b"schema_version": f"invest.research.{name}.v1".encode()})


RESEARCH_BARS = research_schema(
    "bars",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        *[(name, AMOUNT) for name in ("open", "high", "low", "close", "volume")],
        ("available_at", TIME),
        ("captured_at", TIME),
    ],
)
UNIVERSE = research_schema(
    "universe",
    [
        ("instrument", pa.string()),
        ("symbol", pa.string()),
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("available_at", TIME),
    ],
)
FACTOR_SCHEMA = research_schema(
    "factors",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("factor", pa.string()),
        ("expression", pa.string()),
        ("value", pa.float64()),
        ("available_at", TIME),
    ],
)
LABEL_SCHEMA = research_schema(
    "labels",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("horizon", pa.int32()),
        ("entry_at", TIME),
        ("exit_at", TIME),
        ("value", pa.float64()),
    ],
)
SIGNAL_SCHEMA = research_schema(
    "signals",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("score", pa.float64()),
        ("rank", pa.int32()),
        ("direction", pa.int8()),
        ("horizon", pa.int32()),
        ("available_at", TIME),
        ("expires_at", TIME),
        ("pool_id", pa.string()),
    ],
)


@dataclass(frozen=True)
class SnapshotSpec:
    source: str
    source_ref: str
    price_basis: str
    volume_unit: str
    universe_basis: str
    currency: str = "USD"


@dataclass(frozen=True)
class DataSnapshot:
    directory: Path
    snapshot_id: str
    spec: SnapshotSpec
    scope: str
    limitations: tuple[str, ...]
    bars: pa.Table
    universe: pa.Table
    calendar: pa.Table

    def metadata(self, schema: pa.Schema) -> dict[bytes, bytes]:
        return {
            **(schema.metadata or {}),
            b"snapshot_id": self.snapshot_id.encode(),
            b"source": self.spec.source.encode(),
            b"price_basis": self.spec.price_basis.encode(),
            b"scope": self.scope.encode(),
        }


def validate_frame(
    table: pa.Table, schema: pa.Schema, keys: list[str], value_column: str = "value"
) -> None:
    if not table.schema.equals(schema, check_metadata=False):
        raise ValueError("Research frame schema mismatch")
    metadata = table.schema.metadata or {}
    if any(metadata.get(k) != v for k, v in (schema.metadata or {}).items()) or not all(
        metadata.get(k) for k in (b"snapshot_id", b"source", b"price_basis", b"scope")
    ):
        raise ValueError("Research frame requires schema and snapshot provenance")
    frame = table.to_pandas()
    if frame[keys].isna().any().any() or frame.duplicated(keys).any():
        raise ValueError("Research frame keys must be non-null and unique")
    if frame[value_column].isin([float("inf"), float("-inf")]).any():
        raise ValueError("Research frame values must be finite or missing")


@dataclass(frozen=True)
class FactorFrame:
    table: pa.Table

    def __post_init__(self) -> None:
        validate_frame(self.table, FACTOR_SCHEMA, ["date", "instrument", "factor"])


@dataclass(frozen=True)
class LabelFrame:
    table: pa.Table

    def __post_init__(self) -> None:
        validate_frame(self.table, LABEL_SCHEMA, ["date", "instrument", "horizon"])
        for row in self.table.to_pylist():
            if (
                row["horizon"] < 1
                or row["entry_at"] is None
                or row["exit_at"] is None
                or row["entry_at"].date() <= row["date"]
                or row["exit_at"] <= row["entry_at"]
            ):
                raise ValueError("Labels must start after the decision session and end after entry")


@dataclass(frozen=True)
class SignalFrame:
    table: pa.Table

    def __post_init__(self) -> None:
        validate_frame(self.table, SIGNAL_SCHEMA, ["date", "instrument"], "score")
        if any(column.null_count for column in self.table.columns):
            raise ValueError("Signals must have complete values and provenance")
        ranks = set()
        for row in self.table.to_pylist():
            if (
                not -1 <= row["score"] <= 1
                or row["rank"] < 1
                or row["horizon"] < 1
                or row["direction"] not in {0, 1}
                or not row["pool_id"]
                or row["available_at"].date() != row["date"]
                or row["expires_at"] <= row["available_at"]
                or (row["date"], row["rank"]) in ranks
            ):
                raise ValueError("Invalid signal score, rank, direction or validity interval")
            ranks.add((row["date"], row["rank"]))


ACTION_SCHEMA = research_schema(
    "actions",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("action", pa.string()),
        ("current_quantity", pa.int64()),
        ("target_quantity", pa.int64()),
        ("quantity", pa.int64()),
        ("reference_price", MONEY),
        ("target_weight", MONEY),
        ("stop_price", MONEY),
        ("take_profit_price", MONEY),
        ("score", pa.float64()),
        ("reason", pa.string()),
        ("exit_reason", pa.string()),
        ("available_at", TIME),
        ("effective_at", TIME),
        ("expires_at", TIME),
        ("action_id", pa.string()),
        ("policy_id", pa.string()),
        ("pool_id", pa.string()),
        ("cancel_pending", pa.bool_()),
    ],
)


@dataclass(frozen=True)
class Quote:
    instrument: str
    close: Decimal
    active: bool = True
    available: bool = True


@dataclass(frozen=True)
class Holding:
    instrument: str
    shares: int
    entry: Decimal
    income: Decimal = Decimal(0)


@dataclass(frozen=True)
class PendingOrder:
    instrument: str
    side: str
    quantity: int
    reference_price: Decimal


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    snapshot_id: str
    source: str
    as_of: date
    initial_cash: Decimal
    cash: Decimal
    quotes: tuple[Quote, ...]
    holdings: tuple[Holding, ...] = ()
    pending: tuple[PendingOrder, ...] = ()
    receivables: Decimal = Decimal(0)
    unsettled_cash: Decimal = Decimal(0)
    operations: str = "active"

    def __post_init__(self) -> None:
        amounts = (self.initial_cash, self.cash, self.receivables, self.unsettled_cash)
        if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in amounts):
            raise ValueError("Account amounts must be finite nonnegative USD Decimals")
        if any(v >= Decimal("1e18") or v != v.quantize(Decimal(".000001")) for v in amounts):
            raise ValueError("Account amounts exceed the declared money precision")
        if self.initial_cash <= 0 or self.unsettled_cash > self.cash:
            raise ValueError("Invalid account capital or unsettled cash")
        if not all((self.account_id, self.snapshot_id, self.source)) or self.operations not in {
            "active",
            "paused",
        }:
            raise ValueError("Account requires identity, source and operational state")
        for items in (self.quotes, self.holdings, self.pending):
            if len({item.instrument for item in items}) != len(items):
                raise ValueError("Account instruments must be unique within each table")
        for quote in self.quotes:
            if (
                not quote.instrument
                or not isinstance(quote.close, Decimal)
                or not quote.close.is_finite()
                or quote.close <= 0
            ):
                raise ValueError("Quotes require positive raw USD Decimal prices")
            if quote.close >= Decimal("1e18") or quote.close != quote.close.quantize(
                Decimal(".000001")
            ):
                raise ValueError("Quote exceeds the declared money precision")
        known = {quote.instrument for quote in self.quotes}
        for holding in self.holdings:
            if (
                holding.instrument not in known
                or type(holding.shares) is not int
                or holding.shares <= 0
                or not holding.entry.is_finite()
                or holding.entry <= 0
                or not holding.income.is_finite()
                or holding.income < 0
            ):
                raise ValueError("Holdings require whole shares, cost anchors and quotes")
        for order in self.pending:
            if (
                order.instrument not in known
                or order.side not in {"buy", "sell"}
                or type(order.quantity) is not int
                or order.quantity < 1
                or not order.reference_price.is_finite()
                or order.reference_price <= 0
            ):
                raise ValueError("Invalid pending order")
            if order.reference_price >= Decimal(
                "1e18"
            ) or order.reference_price != order.reference_price.quantize(Decimal(".000001")):
                raise ValueError("Pending reference price exceeds the declared money precision")


@dataclass(frozen=True)
class PositionState:
    instrument: str
    entered_on: date
    peak: Decimal
    exit_reason: str = ""


@dataclass(frozen=True)
class StrategyState:
    peak_equity: Decimal
    risk_status: str = "active"
    last_session: date | None = None
    last_rebalance: date | None = None
    positions: tuple[PositionState, ...] = ()
    last_exits: tuple[tuple[str, date], ...] = ()


@dataclass(frozen=True)
class DecisionPlan:
    actions: pa.Table
    state: StrategyState

    def __post_init__(self) -> None:
        validate_frame(self.actions, ACTION_SCHEMA, ["date", "instrument"], "reference_price")
        for row in self.actions.to_pylist():
            if (
                row["action"] not in {"BUY", "ADD", "TRIM", "SELL", "HOLD", "WAIT"}
                or min(row["quantity"], row["current_quantity"], row["target_quantity"]) < 0
                or row["available_at"] >= row["effective_at"]
                or row["effective_at"] >= row["expires_at"]
            ):
                raise ValueError("Invalid decision action, quantity or timing")
