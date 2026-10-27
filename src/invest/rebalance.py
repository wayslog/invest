"""以既有周度漏斗生成不同调仓日程；未来名单不能改变此前交易计划。"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pyarrow as pa

from invest.contracts import SignalFrame
from invest.quality import regular_sessions
from invest.research_data import identity
from invest.strategies import Policy
from invest.weekly_selection import WeeklySelection

FREQUENCIES = ("weekly", "biweekly", "monthly", "quarterly")


def schedule_selections(
    selections: dict[date, WeeklySelection],
    frequency: str,
    mode: str,
) -> dict[date, WeeklySelection]:
    """月、季度按下一成交日归属；调仓后两个决策会话只补完入场，禁止重配旧仓。"""
    if frequency not in FREQUENCIES or mode not in {"rank_rotation", "hold_until_exit"}:
        raise ValueError("Unsupported rebalance frequency or selection mode")
    days = sorted(selections)
    if not days or not selections[days[0]].rebalance:
        raise ValueError("Rebalance schedule requires an initial weekly decision")
    calendar = regular_sessions(days[0], days[-1] + timedelta(days=14)).to_pylist()
    if days != [row["date"] for row in calendar if row["date"] <= days[-1]]:
        raise ValueError("Rebalance schedule requires consecutive decision sessions")
    following = {a["date"]: b["date"] for a, b in zip(calendar[:-1], calendar[1:], strict=True)}
    output = {}
    active = selections[days[0]]
    review_index, week_index = 0, -1
    last_period: tuple[int, int] | None = None
    for index, day in enumerate(days):
        current = selections[day]
        review = False
        if current.rebalance:
            week_index += 1
            execution_day = following[day]
            period = (
                execution_day.year,
                (execution_day.month - 1) // 3 if frequency == "quarterly" else execution_day.month,
            )
            review = (
                frequency == "weekly"
                or (frequency == "biweekly" and week_index % 2 == 0)
                or (frequency in {"monthly", "quarterly"} and period != last_period)
            )
            if review:
                active, review_index, last_period = current, index, period
        output[day] = replace(
            active,
            mode=mode,
            decision_at=current.decision_at,
            selection_id=identity(
                {"selection": active.selection_id, "frequency": frequency, "mode": mode}
            ),
            rebalance=review,
            allow_entries=index - review_index <= 2,
            resize_existing=review,
        )
    return output


def entry_exit_selections(
    selections: dict[date, WeeklySelection],
) -> dict[date, WeeklySelection]:
    """周度候选允许开仓；仅独立退出卖出，不因价格漂移加仓或减仓。"""
    return {
        day: replace(
            selection,
            mode="hold_until_exit",
            rebalance=False,
            allow_entries=True,
            resize_existing=False,
            enforce_exposure=False,
        )
        for day, selection in selections.items()
    }


def buy_hold_inputs(
    selections: dict[date, WeeklySelection],
    signals: SignalFrame,
    policy: Policy,
    *,
    instruments: tuple[str, ...] | None = None,
    fully_invested: bool = False,
) -> tuple[dict[date, WeeklySelection], SignalFrame, Policy]:
    """只在首日按当时名单提交买单；之后不换股、不重入、不重配，分红留现金。"""
    if not selections:
        raise ValueError("Buy and hold requires an initial decision")
    first_day = min(selections)
    initial = selections[first_day]
    basket = initial.candidates if instruments is None else instruments
    if len(set(basket)) != len(basket):
        raise ValueError("Duplicate buy and hold instrument")
    rows = [
        {**row, "score": 1.0, "direction": 1, "rank": basket.index(row["instrument"]) + 1}
        for row in signals.table.to_pylist()
        if row["instrument"] in basket
    ]
    frame = SignalFrame(pa.Table.from_pylist(rows, schema=signals.table.schema))
    settings = replace(
        policy,
        top_k=max(1, len(basket)),
        allocation=Decimal(1) if fully_invested else policy.allocation,
        position_cap=Decimal(1) if fully_invested else policy.position_cap,
        stop_loss=Decimal(0),
        trailing_stop=Decimal(0),
        take_profit=Decimal(0),
        max_holding_sessions=0,
        account_drawdown=Decimal(1),
    )
    contexts = {
        day: replace(
            initial,
            candidates=basket,
            mode="hold_until_exit",
            decision_at=current.decision_at,
            rebalance=day == first_day,
            allow_entries=day == first_day,
            resize_existing=False,
            enforce_exposure=False,
            enforce_account_risk=False,
        )
        for day, current in selections.items()
    }
    return contexts, frame, settings
