"""Close-only, point-in-time strategy targets and correlation screening."""

from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Protocol

import numpy as np
import pyarrow as pa

from invest.contracts import (
    ACTION_SCHEMA,
    AccountSnapshot,
    DecisionPlan,
    SignalFrame,
    StrategyState,
)
from invest.quality import regular_sessions
from invest.research_data import identity
from invest.risk import exit_levels, risk_status
from invest.study_config import StudyConfig

History = dict[str, list[Decimal]]


class Signal(Protocol):
    def rank(self, history: History, lookback: int) -> list[str]: ...


class TrendSignal:
    def rank(self, history: History, lookback: int) -> list[str]:
        return sorted(
            symbol
            for symbol, values in history.items()
            if len(values) >= lookback and values[-1] > sum(values[-lookback:]) / lookback
        )


class RotationSignal:
    def rank(self, history: History, lookback: int) -> list[str]:
        scores = {
            symbol: values[-1] / values[-lookback - 1] - 1
            for symbol, values in history.items()
            if len(values) > lookback
        }
        return sorted(
            (symbol for symbol in scores if scores[symbol] > 0),
            key=lambda symbol: (-scores[symbol], symbol),
        )


@dataclass(frozen=True)
class Candidate:
    kind: str
    lookback: int = 0

    def __post_init__(self) -> None:
        if self.kind not in {"trend", "rotation", "equal_weight", "buy_hold", "market", "cash"}:
            raise ValueError("Unknown strategy")
        if self.kind in {"trend", "rotation"} and self.lookback < 2:
            raise ValueError("Candidate lookback must be >= 2")

    @property
    def name(self) -> str:
        return f"{self.kind}-{self.lookback}" if self.lookback else self.kind

    @property
    def is_strategy(self) -> bool:
        return self.kind in {"trend", "rotation"}


def candidates(config: StudyConfig) -> list[Candidate]:
    return [
        Candidate(kind, window) for kind in config.candidate_kinds for window in config.lookbacks
    ]


def correlation(left: list[Decimal], right: list[Decimal], window: int) -> float | None:
    if min(len(left), len(right)) <= window:
        return None
    a, b = (
        np.asarray(left[-window - 1 :], dtype=float),
        np.asarray(right[-window - 1 :], dtype=float),
    )
    a, b = a[1:] / a[:-1] - 1, b[1:] / b[:-1] - 1
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def target_weights(
    candidate: Candidate, history: History, config: StudyConfig
) -> tuple[dict[str, Decimal], list[dict[str, object]]]:
    if candidate.kind == "cash":
        return {}, []
    if candidate.kind == "market":
        if "SPY" not in history:
            raise ValueError("The declared market benchmark requires SPY")
        return {"SPY": Decimal(1)}, []
    if not candidate.is_strategy:
        return {symbol: config.allocation / len(history) for symbol in sorted(history)}, []
    signal: Signal = TrendSignal() if candidate.kind == "trend" else RotationSignal()
    ranked = signal.rank(history, candidate.lookback)
    selected: list[str] = []
    checks: list[dict[str, object]] = []
    for symbol in ranked:
        allowed = True
        for other in selected:
            rho = correlation(history[symbol], history[other], config.correlation_window)
            accepted = rho is not None and rho <= config.correlation_limit
            checks.append(
                {"symbol": symbol, "other": other, "correlation": rho, "accepted": accepted}
            )
            allowed = allowed and accepted
        if allowed:
            selected.append(symbol)
        if candidate.kind == "rotation" and len(selected) >= config.rotation_count:
            break
    weight = min(config.position_cap, config.allocation / len(selected)) if selected else Decimal(0)
    return {symbol: weight for symbol in selected}, checks


@dataclass(frozen=True)
class Policy:
    top_k: int = 5
    allocation: Decimal = Decimal("0.8")
    position_cap: Decimal = Decimal("0.25")
    commission: Decimal = Decimal(1)
    slippage_bps: Decimal = Decimal(5)
    rebalance_sessions: int = 5
    min_score: float = 0.0
    allow_exploratory: bool = False
    stop_loss: Decimal = Decimal("0.08")
    trailing_stop: Decimal = Decimal("0.12")
    take_profit: Decimal = Decimal("0.2")
    account_drawdown: Decimal = Decimal("0.15")
    max_holding_sessions: int = 60
    cooldown_sessions: int = 5
    exit_mode: str = "close"
    sale_proceeds: str = "same_session"
    participation: Decimal = Decimal(1)

    def __post_init__(self) -> None:
        if type(self.allow_exploratory) is not bool:
            raise ValueError("allow_exploratory must be boolean")
        if (
            type(self.top_k) is not int
            or self.top_k < 1
            or type(self.rebalance_sessions) is not int
            or self.rebalance_sessions < 1
        ):
            raise ValueError("Selection and rebalance counts must be positive integers")
        for name in (
            "allocation",
            "position_cap",
            "commission",
            "slippage_bps",
            "stop_loss",
            "trailing_stop",
            "take_profit",
            "account_drawdown",
            "participation",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("Policy amounts and ratios must be nonnegative finite Decimals")
        if (
            not 0 < self.position_cap <= self.allocation <= 1
            or self.slippage_bps >= 10000
            or not np.isfinite(self.min_score)
        ):
            raise ValueError("Invalid policy exposure, slippage or signal threshold")
        if (
            any(
                type(v) is not int or v < 0
                for v in (self.max_holding_sessions, self.cooldown_sessions)
            )
            or any(not 0 <= v <= 1 for v in (self.stop_loss, self.trailing_stop))
            or not 0 < self.account_drawdown <= 1
            or not 0 < self.participation <= 1
        ):
            raise ValueError("Invalid exit, cooldown or participation policy")
        if self.exit_mode not in {"close", "protective"} or self.sale_proceeds not in {
            "same_session",
            "next_session",
        }:
            raise ValueError("Unsupported exit or sale proceeds policy")

    @property
    def policy_id(self) -> str:
        return identity(
            {
                key: str(value.normalize()) if isinstance(value, Decimal) else value
                for key, value in asdict(self).items()
            }
        )


def decide(
    signals: SignalFrame, account: AccountSnapshot, state: StrategyState, policy: Policy
) -> DecisionPlan:
    """以实际收盘截点生成下一会话动作；只返回新状态，不改动输入账户。"""
    metadata = signals.table.schema.metadata or {}
    if not metadata.get(b"pool_id") or any(
        row["pool_id"].encode() != metadata[b"pool_id"] for row in signals.table.to_pylist()
    ):
        raise ValueError("Signals require one matching frozen factor pool")
    if (
        metadata[b"snapshot_id"].decode() != account.snapshot_id
        or metadata[b"source"].decode() != account.source
    ):
        raise ValueError("Signals and account quotes require matching snapshot provenance")
    if metadata[b"scope"] == b"exploratory" and not policy.allow_exploratory:
        raise ValueError("Exploratory signals require explicit opt-in")
    calendar = regular_sessions(account.as_of, account.as_of + timedelta(days=14)).to_pylist()
    if not calendar or calendar[0]["date"] != account.as_of:
        raise ValueError("Decision cutoff must be an XNYS session")
    if any(
        value is not None and value > account.as_of
        for value in (state.last_session, state.last_rebalance)
    ):
        raise ValueError("Strategy state cannot come from a future session")
    if (
        not state.peak_equity.is_finite()
        or state.peak_equity < 0
        or state.risk_status not in {"active", "warning", "halted", "terminated"}
    ):
        raise ValueError("Invalid persistent strategy risk state")
    closing, following = calendar[0]["close_at"], calendar[1]
    quotes = {q.instrument: q for q in account.quotes}
    holdings = {h.instrument: h for h in account.holdings}
    pending = {order.instrument: order for order in account.pending}
    values = {
        row["instrument"]: row
        for row in signals.table.to_pylist()
        if row["date"] == account.as_of
        and row["available_at"] <= closing < row["expires_at"]
        and row["instrument"] in quotes
        and quotes[row["instrument"]].available
    }
    nav = (
        account.cash
        + account.receivables
        + sum((h.shares * quotes[h.instrument].close for h in account.holdings), Decimal(0))
    )
    anchors = {position.instrument: position for position in state.positions}
    if set(anchors) != set(holdings) or len(anchors) != len(state.positions):
        raise ValueError("Strategy positions must match current holdings")
    if any(
        position.entered_on > account.as_of or not position.peak.is_finite() or position.peak <= 0
        for position in anchors.values()
    ):
        raise ValueError("Invalid position entry date or peak")
    unpriced = any(not quotes[instrument].available for instrument in holdings)
    peak = state.peak_equity if unpriced else max(state.peak_equity, nav)
    status = (
        state.risk_status
        if unpriced
        else risk_status(
            state.risk_status, nav, peak, account.initial_cash, policy.account_drawdown
        )
    )
    scheduled = (
        state.last_rebalance is None
        or state.last_rebalance == account.as_of
        or regular_sessions(state.last_rebalance, account.as_of).num_rows - 1
        >= policy.rebalance_sessions
    )
    blocked = {}
    for instrument, exited in state.last_exits:
        if exited > account.as_of:
            raise ValueError("Exit history cannot come from a future session")
        if regular_sessions(exited, account.as_of).num_rows - 1 <= policy.cooldown_sessions:
            blocked[instrument] = "reentry_cooldown"
    exits: dict[str, str] = {}
    levels: dict[str, tuple[Decimal | None, Decimal | None, str]] = {}
    updated_positions = []
    for instrument, holding in holdings.items():
        quote, anchor = quotes[instrument], anchors[instrument]
        position_peak = (
            max(anchor.peak, quote.close + holding.income) if quote.available else anchor.peak
        )
        updated_positions.append(replace(anchor, peak=position_peak))
        stop, profit, stop_reason = exit_levels(
            holding.entry,
            holding.income,
            position_peak,
            policy.stop_loss,
            policy.trailing_stop,
            policy.take_profit,
        )
        levels[instrument] = stop, profit, stop_reason
        reason = anchor.exit_reason
        if status != "active":
            reason = status
        elif not quote.active:
            reason = "universe_exit"
        elif not reason and quote.available:
            if stop is not None and quote.close <= stop:
                reason = stop_reason
            elif profit is not None and quote.close >= profit:
                reason = "take_profit"
            elif (
                policy.max_holding_sessions
                and regular_sessions(anchor.entered_on, account.as_of).num_rows
                >= policy.max_holding_sessions
            ):
                reason = "holding_limit"
            elif instrument in values and (
                values[instrument]["direction"] == 0
                or values[instrument]["score"] <= policy.min_score
            ):
                reason = "signal_exit"
        if reason:
            exits[instrument] = reason
            updated_positions[-1] = replace(updated_positions[-1], exit_reason=reason)
    ranked = (
        sorted(
            (
                key
                for key, row in values.items()
                if row["direction"] == 1
                and row["score"] > policy.min_score
                and quotes[key].active
                and key not in exits
                and key not in blocked
            ),
            key=lambda key: (values[key]["rank"], key),
        )[: policy.top_k]
        if status == "active" and not unpriced
        else []
    )
    weight = min(policy.position_cap, policy.allocation / len(ranked)) if ranked else Decimal(0)
    reserve = sum(
        (
            p.quantity * p.reference_price * (1 + policy.slippage_bps / 10000) + policy.commission
            for p in account.pending
            if p.side == "buy"
        ),
        Decimal(0),
    )
    available = max(Decimal(0), account.cash - account.unsettled_cash - reserve)
    targets = {}
    reasons = {}
    for instrument, quote in quotes.items():
        current = holdings[instrument].shares if instrument in holdings else 0
        desired = (
            int((nav * weight / quote.close).to_integral_value(rounding=ROUND_FLOOR))
            if instrument in ranked
            else 0
        )
        reason = "rank_selection" if instrument in ranked else "not_selected"
        if not scheduled:
            desired, reason = current, "not_scheduled"
        if instrument in exits:
            desired, reason = 0, exits[instrument]
        elif instrument in blocked:
            desired, reason = current, blocked[instrument]
        elif current and instrument not in values:
            desired, reason = current, "signal_unavailable"
        if instrument in pending or not quote.available or account.operations != "active":
            desired, reason = (
                current,
                "pending_order"
                if instrument in pending
                else "price_unavailable"
                if not quote.available
                else "operations_paused",
            )
        elif status != "active" and not current:
            desired, reason = 0, status
        elif unpriced and desired > current:
            desired, reason = current, "unpriced_position"
        # 仓位自然漂移按下一会话减仓处理，不声称盘中硬上限。
        if (
            current
            and instrument not in pending
            and quote.available
            and account.operations == "active"
            and instrument not in exits
        ):
            market = nav - account.cash - account.receivables
            cap = min(
                policy.position_cap,
                policy.allocation * current * quote.close / max(market, Decimal(1)),
            )
            maximum = int((nav * cap / quote.close).to_integral_value(rounding=ROUND_FLOOR))
            if current > maximum:
                desired, reason = min(desired, maximum), "exposure_reduction"
        targets[instrument], reasons[instrument] = desired, reason
    selling = sorted(
        key for key in quotes if targets[key] < (holdings[key].shares if key in holdings else 0)
    )
    if policy.sale_proceeds == "same_session":
        available += sum(
            (
                max(
                    Decimal(0),
                    (holdings[key].shares - targets[key])
                    * quotes[key].close
                    * (1 - policy.slippage_bps / 10000)
                    - policy.commission,
                )
                for key in selling
            ),
            Decimal(0),
        )
    committed = sum(
        (
            min(holding.shares, targets[holding.instrument]) * quotes[holding.instrument].close
            for holding in account.holdings
        ),
        Decimal(0),
    )
    committed += sum(
        (
            order.quantity * quotes[order.instrument].close
            for order in account.pending
            if order.side == "buy"
        ),
        Decimal(0),
    )
    rows = []
    for instrument in [
        *selling,
        *[key for key in ranked if key not in selling],
        *sorted(set(quotes) - set(selling) - set(ranked)),
    ]:
        quote = quotes[instrument]
        current = holdings[instrument].shares if instrument in holdings else 0
        desired, reason = targets[instrument], reasons[instrument]
        if desired > current:
            price = quote.close * (1 + policy.slippage_bps / 10000)
            affordable = max(
                0,
                int(
                    ((available - policy.commission) / price).to_integral_value(
                        rounding=ROUND_FLOOR
                    )
                ),
            )
            exposure_room = max(
                0,
                int(
                    ((nav * policy.allocation - committed) / quote.close).to_integral_value(
                        rounding=ROUND_FLOOR
                    )
                ),
            )
            affordable = min(affordable, exposure_room)
            desired = current + min(desired - current, affordable)
            if desired > current:
                available -= (desired - current) * price + policy.commission
                committed += (desired - current) * quote.close
            else:
                reason = "insufficient_cash"
        delta = desired - current
        action = (
            "BUY"
            if delta > 0 and not current
            else "ADD"
            if delta > 0
            else "SELL"
            if delta < 0 and not desired
            else "TRIM"
            if delta < 0
            else "HOLD"
            if current
            else "WAIT"
        )
        if (
            reason
            in {
                "pending_order",
                "price_unavailable",
                "operations_paused",
                "unpriced_position",
                "signal_unavailable",
            }
            and delta == 0
        ):
            action = "WAIT"
        if action == "SELL":
            updated_positions = [
                replace(position, exit_reason=reason)
                if position.instrument == instrument
                else position
                for position in updated_positions
            ]
        stop, profit, _ = levels.get(instrument, (None, None, ""))
        if desired > current:
            estimated_entry = (
                (current * holdings[instrument].entry if current else Decimal(0))
                + delta * quote.close * (1 + policy.slippage_bps / 10000)
                + policy.commission
            )
            entry = estimated_entry / desired
            income = holdings[instrument].income * current / desired if current else Decimal(0)
            stop, profit, _ = exit_levels(
                entry,
                income,
                max(entry, anchors[instrument].peak) if current else entry,
                policy.stop_loss,
                policy.trailing_stop,
                policy.take_profit,
            )
        rows.append(
            {
                "date": account.as_of,
                "instrument": instrument,
                "action": action,
                "current_quantity": current,
                "target_quantity": desired,
                "quantity": abs(delta),
                "reference_price": quote.close.quantize(Decimal(".000001")),
                "target_weight": (desired * quote.close / nav if nav else Decimal(0)).quantize(
                    Decimal(".000001")
                ),
                "stop_price": stop.quantize(Decimal(".000001")) if stop is not None else None,
                "take_profit_price": profit.quantize(Decimal(".000001"))
                if profit is not None
                else None,
                "score": values[instrument]["score"] if instrument in values else None,
                "reason": reason,
                "exit_reason": exits.get(instrument, reason if action == "SELL" else ""),
                "available_at": closing,
                "effective_at": following["open_at"],
                "expires_at": following["close_at"],
                "policy_id": policy.policy_id,
                "pool_id": metadata.get(b"pool_id", b"").decode(),
                "cancel_pending": instrument in pending
                and (status != "active" or instrument in exits or account.operations != "active"),
                "action_id": identity(
                    {
                        "account": account.account_id,
                        "date": account.as_of.isoformat(),
                        "instrument": instrument,
                        "policy": policy.policy_id,
                        "snapshot": account.snapshot_id,
                        "pool": metadata.get(b"pool_id", b"").decode(),
                        "reason": reason,
                        "price": str(quote.close.normalize()),
                        "stop": str(stop.normalize()) if stop is not None else None,
                        "profit": str(profit.normalize()) if profit is not None else None,
                        "cash": str(account.cash.normalize()),
                        "current": current,
                        "target": desired,
                    }
                ),
            }
        )
    return DecisionPlan(
        pa.Table.from_pylist(
            rows,
            schema=ACTION_SCHEMA.with_metadata(
                {
                    **metadata,
                    **(ACTION_SCHEMA.metadata or {}),
                    b"price_basis": b"raw",
                    b"signal_price_basis": metadata[b"price_basis"],
                    b"evidence_status": b"research_only",
                    b"policy_id": policy.policy_id.encode(),
                }
            ),
        ),
        replace(
            state,
            peak_equity=peak,
            risk_status=status,
            last_session=account.as_of,
            last_rebalance=account.as_of
            if scheduled and account.operations == "active" and not unpriced and values
            else state.last_rebalance,
            positions=tuple(updated_positions),
        ),
    )
