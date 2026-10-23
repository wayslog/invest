"""Lazy ib_async adapter. No login credentials; connect to an already logged-in Paper gateway."""

import importlib
import math
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.metadata import version
from typing import Any
from zoneinfo import ZoneInfo

from invest.ibkr_data import Capture, decoded
from invest.ibkr_models import BrokerSnapshot, IBKRConfig, Intent, decimal, number, timestamp

# Farm startup is informational; quote/history completeness is checked separately.
INFORMATIONAL_CODES = {2104, 2106, 2107, 2108, 2119, 2158, 10167}


def serializable(value: Any) -> Any:
    """Keep decoded SDK objects in the raw Parquet payload without JSON NaN or repr parsing."""
    if is_dataclass(value) and not isinstance(value, type):
        return serializable(asdict(value))
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if hasattr(value, "_asdict"):
            return serializable(value._asdict())
        return [serializable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, float):
        return str(value)
    if value is None or isinstance(value, (str, bool, int, Decimal, datetime, date)):
        return value
    raise ValueError(f"Unsupported decoded SDK object {type(value).__name__}")


class IBKRGateway:
    source = "ibkr"

    def __init__(self, config: IBKRConfig, sdk: Any = None) -> None:
        if sdk is None:
            try:
                sdk = importlib.import_module("ib_async")
            except ImportError as exc:
                raise ValueError(
                    "IBKR SDK missing: run 'make ibkr-install'; use the isolated runtime"
                ) from exc
        self.sdk, self.config = sdk, config
        self.ib = sdk.IB()
        self.ib.RequestTimeout = config.timeout
        self.ib.RaiseRequestErrors = True
        self.account = ""
        self.client_id = config.client_id
        self.raw: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.snapshot_error_cursor = 0
        self.account_subscription_active = False
        self.expect_unsubscribe = False
        self.collecting_account_values = False
        self.fresh_account_values: dict[tuple[str, str, str, str], Any] = {}
        self.actual_types: dict[int, int] = {}
        self.ib.errorEvent += self._error
        self.ib.accountValueEvent += self._account_value

    def __enter__(self) -> "IBKRGateway":
        try:
            self.ib.wrapper.clientId = self.client_id
            self.ib.client.connect(
                self.config.host,
                self.config.port,
                clientId=self.client_id,
                timeout=self.config.timeout,
            )
            accounts = list(self.ib.managedAccounts())
            if self.config.account:
                if self.config.account not in accounts:
                    raise ValueError("Configured Paper account not available on this gateway")
                self.account = self.config.account
            elif len(accounts) == 1:
                self.account = accounts[0]
            else:
                raise ValueError(
                    "Select one Paper account when the gateway exposes multiple accounts"
                )
            if not self.account.startswith("DU"):
                raise ValueError("M4 refuses live accounts; connect a Paper Trading session")
            original = self.ib.wrapper.marketDataType

            def market_data_type(req_id: int, actual_type: int) -> None:
                original(req_id, actual_type)
                ticker = self.ib.wrapper.reqId2Ticker.get(req_id)
                if ticker is not None:
                    self.actual_types[int(ticker.contract.conId)] = actual_type

            # Ticker.marketDataType defaults to 1 even before a callback; record observed callbacks.
            self.ib.wrapper.marketDataType = market_data_type
            return self
        except BaseException:
            self.ib.disconnect()
            raise

    def __exit__(self, *args: Any) -> None:
        self.ib.disconnect()

    def _error(self, req_id: int, code: int, message: str, *args: Any) -> None:
        expected_unsubscribe = code == 2100 and self.expect_unsubscribe
        if expected_unsubscribe:
            self.expect_unsubscribe = False
        self.raw.append(
            decoded(
                "errorEvent",
                datetime.now(UTC),
                {
                    "request_id": req_id,
                    "code": code,
                    "message": message,
                },
                complete=code in INFORMATIONAL_CODES or expected_unsubscribe,
            )
        )
        if code not in INFORMATIONAL_CODES and not expected_unsubscribe:
            self.errors.append(f"request={req_id} code={code}: {message}")

    def _account_value(self, value: Any) -> None:
        if self.collecting_account_values and value.account == self.account:
            key = (value.account, value.tag, value.currency, value.modelCode)
            self.fresh_account_values[key] = value

    def _query(self, method: str, *args: Any, **kwargs: Any) -> Any:
        started = datetime.now(UTC)
        try:
            result = getattr(self.ib, method)(*args, **kwargs)
            self.raw.append(
                decoded(
                    method,
                    started,
                    {
                        "args": serializable(args),
                        "kwargs": serializable(kwargs),
                        "result": serializable(result),
                    },
                )
            )
            return result
        except Exception as exc:
            self.raw.append(
                decoded(
                    method,
                    started,
                    {
                        "args": serializable(args),
                        "kwargs": serializable(kwargs),
                        "error_type": type(exc).__name__,
                    },
                    complete=False,
                )
            )
            raise

    def _attempt(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._query(method, *args, **kwargs)
        except Exception as exc:
            self.errors.append(f"{method}: {type(exc).__name__}")
            return []

    @staticmethod
    def _order(trade: Any) -> dict[str, Any]:
        order, status, contract = trade.order, trade.orderStatus, trade.contract
        return {
            "account": order.account,
            "client_id": int(status.clientId or order.clientId),
            "order_id": int(order.orderId),
            "perm_id": int(status.permId or order.permId),
            "order_ref": order.orderRef,
            "con_id": int(contract.conId),
            "symbol": contract.symbol,
            "currency": contract.currency,
            "side": order.action,
            "quantity": decimal(order.totalQuantity),
            "limit_price": number(order.lmtPrice, optional=True),
            "order_type": order.orderType,
            "status": status.status,
            "filled": decimal(status.filled),
            "remaining": decimal(status.remaining),
            "rejected": any(entry.errorCode == 201 for entry in trade.log),
        }

    def snapshot(self) -> BrokerSnapshot:
        errors_start = self.snapshot_error_cursor
        # Wait for each explicit end-of-query response instead of trusting startup caches.
        if self.account_subscription_active:
            self.expect_unsubscribe = True
            self.ib.client.reqAccountUpdates(False, self.account)
        self.fresh_account_values.clear()
        self.collecting_account_values = True
        try:
            self._attempt("reqAccountUpdates", self.account)
            self.account_subscription_active = True
        finally:
            self.collecting_account_values = False
            self.expect_unsubscribe = False
        values = list(self.fresh_account_values.values())
        positions = self._attempt("reqPositions")
        opened = self._attempt("reqAllOpenOrders")
        completed = self._attempt("reqCompletedOrders", False)
        fills = self._attempt("reqExecutions", self.sdk.ExecutionFilter(acctCode=self.account))
        self.ib.sleep(0.2)  # Allow already-requested commission reports to arrive.
        self.raw.append(
            decoded("fresh_account_value_callbacks", datetime.now(UTC), serializable(values))
        )
        orders: dict[tuple[int, int, str], dict[str, Any]] = {}
        cached = self.ib.trades()
        self.raw.append(decoded("trades_cache", datetime.now(UTC), serializable(cached)))
        for trade in [*completed, *opened, *cached]:
            row = self._order(trade)
            if row["account"] == self.account:
                orders[(row["client_id"], row["order_id"], row["status"])] = row
        executions, commissions = [], []
        for fill in fills:
            execution, contract = fill.execution, fill.contract
            executions.append(
                {
                    "exec_id": execution.execId,
                    "account": execution.acctNumber,
                    "client_id": int(execution.clientId),
                    "order_id": int(execution.orderId),
                    "perm_id": int(execution.permId),
                    "order_ref": execution.orderRef,
                    "con_id": int(contract.conId),
                    "symbol": contract.symbol,
                    "currency": contract.currency,
                    "side": execution.side,
                    "quantity": decimal(execution.shares),
                    "price": decimal(execution.price),
                    "trade_at": timestamp(execution.time),
                }
            )
            report = fill.commissionReport
            if report.execId:
                commissions.append(
                    {
                        "exec_id": report.execId,
                        "currency": report.currency,
                        "commission": number(report.commission, optional=True),
                    }
                )
        self.snapshot_error_cursor = len(self.errors)
        return BrokerSnapshot(
            self.source,
            self.account,
            datetime.now(UTC),
            [
                {
                    "account": v.account,
                    "tag": v.tag,
                    "value": v.value,
                    "currency": v.currency,
                    "model_code": v.modelCode,
                }
                for v in values
            ],
            [
                {
                    "account": p.account,
                    "con_id": int(p.contract.conId),
                    "symbol": p.contract.symbol,
                    "currency": p.contract.currency,
                    "quantity": decimal(p.position),
                    "average_cost": number(p.avgCost, optional=True),
                }
                for p in positions
                if p.account == self.account
            ],
            list(orders.values()),
            executions,
            commissions,
            complete=len(self.errors) == errors_start,
            errors=self.errors[errors_start:],
        )

    def capture(self) -> Capture:
        snapshot = self.snapshot()
        result = Capture(
            snapshot,
            self.config,
            sdk_version=version("ib_async"),
            server_version=int(self.ib.client.serverVersion()),
        )
        market_error_start = len(self.errors)
        for symbol in self.config.symbols:
            try:
                contracts = self._query("qualifyContracts", self.sdk.Stock(symbol, "SMART", "USD"))
                if len(contracts) != 1:
                    raise ValueError("IBKR did not return one qualified contract")
                contract = contracts[0]
                details = self._query("reqContractDetails", contract)
                if len(details) != 1 or contract.secType != "STK" or contract.currency != "USD":
                    raise ValueError("Only qualified USD stocks/ETFs are supported")
                result.contracts.append(
                    {
                        "con_id": int(contract.conId),
                        "symbol": symbol,
                        "security_type": contract.secType,
                        "currency": contract.currency,
                        "exchange": contract.exchange,
                        "primary_exchange": contract.primaryExchange,
                        "min_tick": decimal(details[0].minTick),
                    }
                )
                bars = self._attempt(
                    "reqHistoricalData",
                    contract,
                    endDateTime="",
                    durationStr=self.config.duration,
                    barSizeSetting=self.config.bar_size,
                    whatToShow=self.config.what_to_show,
                    useRTH=self.config.use_rth,
                    formatDate=2,
                    keepUpToDate=False,
                    timeout=self.config.timeout,
                )
                for bar in bars:
                    when = bar.date
                    bar_at = timestamp(when) if isinstance(when, datetime) else None
                    session = (
                        bar_at.astimezone(ZoneInfo("America/New_York")).date()
                        if bar_at
                        else when
                        if isinstance(when, date)
                        else date.fromisoformat(when)
                    )
                    result.historical.append(
                        {
                            "con_id": int(contract.conId),
                            "symbol": symbol,
                            "session": session,
                            "bar_at": bar_at,
                            "bar_size": self.config.bar_size,
                            "what_to_show": self.config.what_to_show,
                            "price_basis": "split_adjusted"
                            if self.config.what_to_show == "TRADES"
                            else "split_dividend_adjusted",
                            "use_rth": self.config.use_rth,
                            "currency": "USD",
                            **{
                                key: decimal(getattr(bar, key))
                                for key in ("open", "high", "low", "close", "volume")
                            },
                            "volume_unit": "provider_reported_unverified",
                        }
                    )
                self.ib.reqMarketDataType(self.config.market_data_type)
                self.actual_types.pop(int(contract.conId), None)
                quote_started = datetime.now(UTC)
                ticker = self.ib.reqMktData(contract, "", False, False)
                try:
                    self.ib.sleep(self.config.quote_wait)
                    self.raw.append(
                        decoded(
                            "reqMktData",
                            quote_started,
                            {
                                "symbol": symbol,
                                "requested_type": self.config.market_data_type,
                                **{
                                    key: serializable(getattr(ticker, key, None))
                                    for key in (
                                        "marketDataType",
                                        "time",
                                        "rtTime",
                                        "bid",
                                        "ask",
                                        "last",
                                        "bidSize",
                                        "askSize",
                                        "lastSize",
                                    )
                                },
                            },
                        )
                    )
                    row: dict[str, Any] = {
                        "con_id": int(contract.conId),
                        "symbol": symbol,
                        "currency": "USD",
                        "requested_type": self.config.market_data_type,
                        "actual_type": self.actual_types.get(int(contract.conId)),
                        "sdk_updated_at": timestamp(ticker.time) if ticker.time else None,
                        "exchange_trade_at": timestamp(ticker.rtTime) if ticker.rtTime else None,
                        "received_at": datetime.now(UTC),
                    }
                    for key, sdk_key in (
                        ("bid", "bid"),
                        ("ask", "ask"),
                        ("last", "last"),
                        ("bid_size", "bidSize"),
                        ("ask_size", "askSize"),
                        ("last_size", "lastSize"),
                    ):
                        amount = number(getattr(ticker, sdk_key), optional=True)
                        row[key] = amount if amount is not None and amount >= 0 else None
                    result.quotes.append(row)
                finally:
                    self.ib.cancelMktData(contract)
            except Exception as exc:
                result.errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
        snapshot.captured_at = datetime.now(UTC)
        result.errors.extend(self.errors[market_error_start:])
        result.raw = self.raw
        return result

    def reserve_order_id(self) -> int:
        return int(self.ib.client.getReqId())

    def submit(self, intent: Intent, order_id: int) -> None:
        if (intent.account, intent.client_id) != (self.account, self.client_id):
            raise ValueError("Order intent does not belong to the connected Paper account/client")
        contract = self.sdk.Stock(intent.symbol, "SMART", "USD", conId=intent.con_id)
        order = self.sdk.LimitOrder(
            intent.side,
            intent.quantity,
            intent.limit_price,
            orderId=order_id,
            clientId=self.client_id,
            account=self.account,
            orderRef=intent.order_ref,
            tif="DAY",
            outsideRth=False,
        )
        self.ib.placeOrder(contract, order)
        self.ib.sleep(0.5)

    def cancel(self, intent: Intent, order_id: int) -> None:
        if (intent.account, intent.client_id) != (self.account, self.client_id):
            raise ValueError("Cancellation intent differs from the connected Paper account/client")
        trades = self._query("reqAllOpenOrders")
        matches = [
            t
            for t in trades
            if t.order.account == self.account
            and t.order.clientId == self.client_id
            and t.order.orderId == order_id
            and t.order.orderRef == intent.order_ref
            and t.contract.conId == intent.con_id
        ]
        if len(matches) != 1:
            raise ValueError("Cancellation target not positively identified; reconcile first")
        self.ib.cancelOrder(matches[0].order)
        self.ib.sleep(0.5)
