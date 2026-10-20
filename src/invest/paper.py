"""Deterministic daily-bar paper ledger shared by replay and incremental runs."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, Decimal

import pyarrow as pa

from invest.config import PaperConfig
from invest.market import MONEY
from invest.quality import regular_sessions

ZERO = Decimal("0")
UNIT = Decimal("0.000001")


def money(value: Decimal) -> Decimal:
    return value.quantize(UNIT)


TRADE_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("decision_date", pa.date32()),
        ("symbol", pa.string()),
        ("side", pa.string()),
        ("quantity", pa.int64()),
        ("price", MONEY),
        ("commission", MONEY),
        ("cash_after", MONEY),
        ("reason", pa.string()),
    ]
)
EQUITY_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("cash", MONEY),
        ("shares", pa.int64()),
        ("market_value", MONEY),
        ("receivables", MONEY),
        ("equity", MONEY),
        ("benchmark_equity", MONEY),
        ("drawdown", pa.float64()),
        ("status", pa.string()),
        ("pending_side", pa.string()),
        ("pending_quantity", pa.int64()),
        ("pending_reason", pa.string()),
    ]
)
EVENT_SCHEMA = pa.schema(
    [("date", pa.date32()), ("kind", pa.string()), ("detail", pa.string()), ("amount", MONEY)]
)


@dataclass
class Order:
    decision_date: date
    side: str
    quantity: int
    reason: str


@dataclass
class Account:
    cash: Decimal
    shares: int = 0
    entry: Decimal = ZERO
    position_peak: Decimal = ZERO
    position_income: Decimal = ZERO
    signal_income: Decimal = ZERO
    peak: Decimal = ZERO
    status: str = "active"
    warning_breached: bool = False
    pending: Order | None = None
    receivables: list[tuple[date, Decimal]] = field(default_factory=list)
    trades: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)
    closes: list[Decimal] = field(default_factory=list)

    def equity(self, price: Decimal) -> Decimal:
        return money(self.cash + self.shares * price + sum((x[1] for x in self.receivables), ZERO))

    def event(self, session: date, kind: str, detail: str, amount: Decimal = ZERO) -> None:
        self.events.append(
            {"date": session, "kind": kind, "detail": detail, "amount": money(amount)}
        )

    def corporate_actions(self, row: dict[str, object]) -> None:
        session = row["date"]
        assert isinstance(session, date)
        ratio = row["split_ratio"]
        assert isinstance(ratio, int)
        if ratio != 1:
            self.shares *= ratio
            self.entry /= ratio
            self.position_peak /= ratio
            self.position_income /= ratio
            self.signal_income /= ratio
            self.closes = [value / ratio for value in self.closes]
            if self.pending is not None:
                self.pending.quantity *= ratio
            self.event(session, "split", f"{ratio}:1 forward split")
        dividend = row["dividend"]
        assert isinstance(dividend, Decimal)
        self.signal_income += dividend
        if dividend and self.shares:
            self.position_income += dividend
            payment = row["dividend_pay_date"]
            assert isinstance(payment, date)
            amount = money(dividend * self.shares)
            self.receivables.append((payment, amount))
            self.event(
                session, "dividend_entitlement", f"payment_date={payment.isoformat()}", amount
            )
        unpaid = []
        for payment, amount in self.receivables:
            if payment <= session:
                self.cash += amount
                self.event(session, "dividend_payment", "Receivable credited to cash", amount)
            else:
                unpaid.append((payment, amount))
        self.receivables = unpaid

    def execute(self, session: date, open_price: Decimal, config: PaperConfig) -> None:
        if self.pending is None:
            return
        order = self.pending
        self.pending = None
        if session <= order.decision_date:
            raise ValueError("An order cannot fill before the session after its decision")
        if regular_sessions(order.decision_date, session).num_rows != 2:
            self.event(session, "order_expired", "Order valid only at the next session open")
            return
        direction = Decimal("1") if order.side == "buy" else Decimal("-1")
        price = money(open_price * (1 + direction * config.slippage_bps / 10000))
        if price <= 0:
            raise ValueError("Slippage and price precision produce a non-positive fill")
        if order.side == "buy":
            available = min(self.cash, self.equity(open_price) * config.allocation)
            affordable = max(
                0,
                int(
                    ((available - config.commission) / price).to_integral_value(
                        rounding=ROUND_FLOOR
                    )
                ),
            )
            quantity = min(order.quantity, affordable)
            if quantity == 0:
                self.event(
                    session, "order_rejected", "Insufficient cash for one whole share and fee"
                )
                return
            if quantity < order.quantity:
                self.event(session, "order_reduced", "Opening gap reduced affordable whole shares")
            self.cash = money(self.cash - quantity * price - config.commission)
            self.shares += quantity
            self.entry = (quantity * price + config.commission) / quantity
            self.position_peak = price
            self.position_income = ZERO
        else:
            quantity = self.shares
            if not quantity:
                return
            self.cash = money(self.cash + quantity * price - config.commission)
            self.shares = 0
            self.entry = ZERO
            self.position_peak = ZERO
            self.position_income = ZERO
        self.trades.append(
            {
                "date": session,
                "decision_date": order.decision_date,
                "symbol": config.symbol,
                "side": order.side,
                "quantity": quantity,
                "price": price,
                "commission": money(config.commission),
                "cash_after": self.cash,
                "reason": order.reason,
            }
        )

    def decide(self, session: date, close: Decimal, config: PaperConfig, benchmark: bool) -> None:
        signal_close = close + self.signal_income
        self.closes.append(signal_close)
        self.peak = max(self.peak, self.equity(close))
        if benchmark:
            if not self.shares and self.pending is None and len(self.closes) >= config.lookback:
                self.queue_buy(session, close, config, "buy_and_hold")
            return
        equity = self.equity(close)
        previous_status = self.status
        if equity < config.initial_cash * Decimal("0.8") and not self.warning_breached:
            self.warning_breached = True
            self.event(session, "capital_warning", "Equity below 80% of initial capital", equity)
        if equity <= config.initial_cash * Decimal("0.5"):
            self.status = "terminated"
        elif self.status != "terminated" and equity <= self.peak * (1 - config.account_drawdown):
            self.status = "halted"
        elif self.status == "active" and equity < config.initial_cash * Decimal("0.8"):
            self.status = "warning"
        if self.status != previous_status:
            self.event(session, "risk_state", f"{previous_status} -> {self.status}", equity)
        if self.status != "active":
            if self.shares:
                self.pending = Order(session, "sell", self.shares, self.status)
            else:
                self.pending = None
            return
        if self.pending is not None:
            return
        if self.shares:
            economic_close = close + self.position_income
            self.position_peak = max(self.position_peak, economic_close)
            reason = ""
            if economic_close <= self.entry * (1 - config.stop_loss):
                reason = "stop_loss"
            elif economic_close <= self.position_peak * (1 - config.trailing_stop):
                reason = "trailing_stop"
            elif (
                len(self.closes) >= config.lookback
                and signal_close <= sum(self.closes[-config.lookback :], ZERO) / config.lookback
            ):
                reason = "trend_exit"
            if reason:
                self.pending = Order(session, "sell", self.shares, reason)
        elif (
            len(self.closes) >= config.lookback
            and signal_close > sum(self.closes[-config.lookback :], ZERO) / config.lookback
        ):
            self.queue_buy(session, close, config, "trend_entry")

    def queue_buy(self, session: date, close: Decimal, config: PaperConfig, reason: str) -> None:
        estimated_price = close * (1 + config.slippage_bps / 10000)
        budget = min(self.cash, self.equity(close) * config.allocation) - config.commission
        quantity = max(0, int((budget / estimated_price).to_integral_value(rounding=ROUND_FLOOR)))
        if quantity:
            self.pending = Order(session, "buy", quantity, reason)


@dataclass
class PaperResult:
    equity: pa.Table
    trades: pa.Table
    events: pa.Table
    benchmark_trades: pa.Table
    metrics: pa.Table


def simulate(bars: pa.Table, config: PaperConfig) -> PaperResult:
    # Reject an unusable history as a whole. Never condition an opening fill on
    # the volume learned at that session's close.
    if not bars.num_rows or any(value <= 0 for value in bars["volume"].to_pylist()):
        raise ValueError("Zero-volume history cannot support the daily-open fill proxy")
    dates = bars["date"].to_pylist()
    if dates != regular_sessions(dates[0], dates[-1])["date"].to_pylist():
        raise ValueError("Simulation requires complete XNYS sessions")
    account = Account(cash=money(config.initial_cash), peak=config.initial_cash)
    baseline = Account(cash=money(config.initial_cash), peak=config.initial_cash)
    snapshots: list[dict[str, object]] = []
    max_drawdown = 0.0
    for row in bars.to_pylist():
        session, close = row["date"], row["close"]
        for ledger, benchmark in [(account, False), (baseline, True)]:
            ledger.corporate_actions(row)
            ledger.execute(session, row["open"], config)
            ledger.decide(session, close, config, benchmark)
        equity = account.equity(close)
        drawdown = float(equity / account.peak - 1)
        max_drawdown = min(max_drawdown, drawdown)
        pending = account.pending
        snapshots.append(
            {
                "date": session,
                "cash": account.cash,
                "shares": account.shares,
                "market_value": money(account.shares * close),
                "receivables": money(sum((x[1] for x in account.receivables), ZERO)),
                "equity": equity,
                "benchmark_equity": baseline.equity(close),
                "drawdown": drawdown,
                "status": account.status,
                "pending_side": pending.side if pending else None,
                "pending_quantity": pending.quantity if pending else 0,
                "pending_reason": pending.reason if pending else None,
            }
        )
    final = snapshots[-1]
    metadata = bars.schema.metadata or {}
    metrics = pa.Table.from_pylist(
        [
            {
                "symbol": config.symbol,
                "data_source": metadata[b"source"].decode(),
                "observations": len(snapshots),
                "initial_cash": money(config.initial_cash),
                "final_equity": final["equity"],
                "total_return": float(account.equity(close) / config.initial_cash - 1),
                "benchmark_return": float(baseline.equity(close) / config.initial_cash - 1),
                "max_drawdown": max_drawdown,
                "trade_count": len(account.trades),
                "commissions": money(config.commission * len(account.trades)),
                "status": account.status,
                "pending_order": account.pending is not None,
                "fill_model": "provider_daily_open_proxy; next_session_only",
                "cash_model": "USD_no_external_flows; settlement_not_modeled",
            }
        ]
    )
    return PaperResult(
        equity=pa.Table.from_pylist(snapshots, schema=EQUITY_SCHEMA),
        trades=pa.Table.from_pylist(account.trades, schema=TRADE_SCHEMA),
        events=pa.Table.from_pylist(account.events, schema=EVENT_SCHEMA),
        benchmark_trades=pa.Table.from_pylist(baseline.trades, schema=TRADE_SCHEMA),
        metrics=metrics,
    )
