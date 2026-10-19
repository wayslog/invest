from datetime import date, timedelta
from decimal import Decimal

import pyarrow as pa

from invest.config import PaperConfig
from invest.market import BAR_SCHEMA

BASE = PaperConfig(
    lookback=2,
    allocation=Decimal("1"),
    commission=Decimal("0"),
    slippage_bps=Decimal("0"),
    stop_loss=Decimal("1"),
    trailing_stop=Decimal("1"),
    account_drawdown=Decimal("1"),
)


def make_bars(
    closes: list[int],
    opens: list[int] | None = None,
    updates: dict[int, dict[str, object]] | None = None,
) -> pa.Table:
    rows = []
    session = date(2024, 1, 2)
    for i, value in enumerate(closes):
        while session.weekday() >= 5:
            session += timedelta(days=1)
        opening = Decimal(opens[i] if opens else closes[max(0, i - 1)])
        closing = Decimal(value)
        row: dict[str, object] = {
            "date": session,
            "symbol": "DEMO",
            "open": opening,
            "close": closing,
            "high": max(opening, closing) + 1,
            "low": min(opening, closing) - 1,
            "volume": 1000,
            "split_ratio": 1,
            "dividend": Decimal("0"),
            "dividend_pay_date": None,
        }
        row.update((updates or {}).get(i, {}))
        rows.append(row)
        session += timedelta(days=1)
    schema = BAR_SCHEMA.with_metadata({**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"})
    return pa.Table.from_pylist(rows, schema=schema)
