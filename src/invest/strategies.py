"""信号驱动的统一只读决策与组合风险规则。"""

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import numpy as np
import pyarrow as pa

from invest.contracts import (
    ACTION_SCHEMA,
    AccountSnapshot,
    DecisionPlan,
    SignalFrame,
    StrategyState,
)
from invest.legacy_strategies import (
    Candidate as Candidate,
)
from invest.legacy_strategies import (
    History as History,
)
from invest.legacy_strategies import (
    RotationSignal as RotationSignal,
)
from invest.legacy_strategies import (
    Signal as Signal,
)
from invest.legacy_strategies import (
    TrendSignal as TrendSignal,
)
from invest.legacy_strategies import (
    candidates as candidates,
)
from invest.legacy_strategies import (
    correlation as correlation,
)
from invest.legacy_strategies import (
    target_weights as target_weights,
)
from invest.quality import regular_sessions
from invest.research_data import identity
from invest.risk import exit_levels, liquidates, principal_status, risk_status
from invest.weekly_selection import WeeklySelection


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
    # peak_drawdown 为原规则（回撤锁定与 80%/50% 本金线，非正常状态均清仓）；
    # principal_ladder 不使用 account_drawdown，见 risk.principal_status。
    account_risk: str = "peak_drawdown"

    def __post_init__(self) -> None:
        if self.account_risk not in {"peak_drawdown", "principal_ladder"}:
            raise ValueError("Unsupported account risk policy")
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
        # 新增字段取默认值时不进入身份，已冻结策略的 policy_id 与动作身份保持不变。
        return identity(
            {
                key: str(value.normalize()) if isinstance(value, Decimal) else value
                for key, value in asdict(self).items()
                if not (key == "account_risk" and value == "peak_drawdown")
            }
        )


def decide(
    signals: SignalFrame,
    account: AccountSnapshot,
    state: StrategyState,
    policy: Policy,
    *,
    selection: WeeklySelection | None = None,
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
    if selection is not None:
        if not closing <= selection.decision_at < following["open_at"]:
            raise ValueError("Weekly decision must follow its price close and precede execution")
        closing = selection.decision_at
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
    unpriced = any(not quotes[instrument].available for instrument in holdings)
    # 未准入价格不能作为组合估值；缺价时保留独立退出，但暂停依赖净值的目标仓位计算。
    nav = (
        None
        if unpriced
        else account.cash
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
    peak = state.peak_equity if nav is None else max(state.peak_equity, nav)
    status = (
        state.risk_status
        if nav is None or (selection is not None and not selection.enforce_account_risk)
        else principal_status(state.risk_status, nav, account.initial_cash)
        if policy.account_risk == "principal_ladder"
        else risk_status(
            state.risk_status, nav, peak, account.initial_cash, policy.account_drawdown
        )
    )
    liquidating = liquidates(status, policy.account_risk)
    # 本金警戒：保留现有个股及其独立退出，不新开、不加仓；只允许降低风险的减仓。
    hold_only = status != "active" and not liquidating
    scheduled = (
        state.last_rebalance is None
        or state.last_rebalance == account.as_of
        or regular_sessions(state.last_rebalance, account.as_of).num_rows - 1
        >= policy.rebalance_sessions
    )
    if selection is not None:
        scheduled = selection.rebalance
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
        if liquidating:
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
        if (
            not reason
            and selection is not None
            and selection.mode == "rank_rotation"
            and instrument not in selection.candidates
        ):
            reason = "rank_exit"
        if reason:
            exits[instrument] = reason
            updated_positions[-1] = replace(updated_positions[-1], exit_reason=reason)
    eligible_buys = (
        {
            key
            for key, row in values.items()
            if row["direction"] == 1
            and row["score"] > policy.min_score
            and quotes[key].active
            and key not in exits
            and key not in blocked
        }
        if status == "active" and not unpriced and account.operations == "active"
        else set()
    )
    ranked = sorted(eligible_buys, key=lambda key: (values[key]["rank"], key))[: policy.top_k]
    entry_blocks: dict[str, str] = {}
    retained: set[str] = set()
    if selection is not None:
        eligible_buys &= set(selection.candidates)
        ranked, entry_blocks = selection.targets(
            eligible_buys,
            set(holdings),
            set(exits),
            {key for key, order in pending.items() if order.side == "buy"},
            policy.top_k,
        )
        retained = set(holdings) - set(selection.candidates) - set(exits)
        # 当周未完成的入场在名额、交收和冷却允许后继续评估，不重置账户或等待新一周。
        scheduled = scheduled or (selection.allow_entries and bool(set(ranked) - set(holdings)))
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
            if instrument in ranked and nav is not None
            else 0
        )
        reason = "rank_selection" if instrument in ranked else "not_selected"
        if unpriced:
            desired, reason = current, "unpriced_position"
        elif not scheduled:
            desired, reason = current, "not_scheduled"
        if selection is not None and not unpriced:
            if current and not selection.resize_existing:
                desired, reason = current, "scheduled_resize_disabled"
            elif not current and not selection.allow_entries:
                desired, reason = 0, "entry_window_closed"
        if not unpriced:
            if instrument in entry_blocks and not current:
                reason = entry_blocks[instrument]
            if (
                selection is not None
                and selection.mode == "hold_until_exit"
                and instrument in retained
            ):
                desired, reason = current, "retained_until_exit"
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
        elif hold_only and desired != current:
            desired, reason = current, "principal_warning"
        # 仓位自然漂移按下一会话减仓处理，不声称盘中硬上限。
        if (
            current
            and nav is not None
            and instrument not in pending
            and quote.available
            and account.operations == "active"
            and instrument not in exits
            and (selection is None or selection.enforce_exposure)
        ):
            market = nav - account.cash - account.receivables
            cap = min(
                policy.position_cap,
                policy.allocation * current * quote.close / max(market, Decimal(1)),
            )
            maximum = int((nav * cap / quote.close).to_integral_value(rounding=ROUND_FLOOR))
            if current > maximum:
                desired, reason = min(desired, maximum), "exposure_reduction"
        if (
            reason in {"not_selected", "not_scheduled"}
            and current == desired == 0
            and metadata.get(b"selection_status") == b"no_selected_factors"
        ):
            reason = "no_selected_factors"
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
            if quotes[holding.instrument].available
        ),
        Decimal(0),
    )
    committed += sum(
        (
            order.quantity
            * (
                quotes[order.instrument].close
                if quotes[order.instrument].available
                else order.reference_price
            )
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
            assert nav is not None
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
        row: dict[str, Any] = {
            "date": account.as_of,
            "instrument": instrument,
            "action": action,
            "current_quantity": current,
            "target_quantity": desired,
            "quantity": abs(delta),
            "reference_price": quote.close.quantize(Decimal(".000001"))
            if quote.available
            else None,
            "target_weight": None
            if nav is None or not quote.available
            else (desired * quote.close / nav if nav else Decimal(0)).quantize(Decimal(".000001")),
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
            and (
                liquidating
                or (hold_only and pending[instrument].side == "buy")
                or instrument in exits
                or account.operations != "active"
                or (pending[instrument].side == "buy" and instrument not in eligible_buys)
            ),
            "price_type": "next_session_open",
            "exit_mode": policy.exit_mode,
            "max_holding_sessions": policy.max_holding_sessions,
            "cooldown_sessions": policy.cooldown_sessions,
        }
        # 对最终保存的动作语义生成身份，包含取消需求、退出原因和有效期；等值 Decimal 同编码。
        row["action_id"] = identity(
            {
                **(
                    {"selection_id": selection.selection_id, "mode": selection.mode}
                    if selection is not None
                    else {}
                ),
                "account": account.account_id,
                "snapshot": account.snapshot_id,
                "source": account.source,
                "cash": str(account.cash.normalize()),
                "action": {
                    key: str(value.normalize())
                    if isinstance(value, Decimal)
                    else value.isoformat()
                    if isinstance(value, date)
                    else value
                    for key, value in row.items()
                },
            }
        )
        rows.append(row)
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
                    **({b"selection_mode": selection.mode.encode()} if selection else {}),
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
