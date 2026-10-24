"""P2 离线合成演示：模板搜索、因子筛选、冻结与排名，不代表策略收益。"""

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from invest.cli import main as invest_main
from invest.contracts import RESEARCH_BARS, UNIVERSE, SnapshotSpec
from invest.market import BAR_SCHEMA
from invest.quality import regular_sessions
from invest.research_data import create_snapshot


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args(argv).output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sessions = regular_sessions(date(2022, 1, 3), date(2022, 12, 30)).to_pylist()
    rows, members = [], []
    for number in range(1, 13):
        instrument = f"SYNTH{number:02d}"
        members.append(
            {
                "instrument": instrument,
                "symbol": instrument,
                "start": sessions[0]["date"],
                "end": sessions[-1]["date"],
                "available_at": sessions[0]["open_at"],
            }
        )
        for index, session in enumerate(sessions):
            price = (Decimal(40 + 5 * number) * (1 + Decimal(number) / 3000) ** index).quantize(
                Decimal("0.00000001")
            )
            rows.append(
                {
                    "date": session["date"],
                    "instrument": instrument,
                    "open": price,
                    "high": price + 2,
                    "low": price - 2,
                    "close": price,
                    "volume": Decimal(1000 * number + (index % 7) * 30),
                    "available_at": session["close_at"],
                    "captured_at": datetime(2023, 1, 1, tzinfo=UTC),
                }
            )
    create_snapshot(
        pa.Table.from_pylist(rows, schema=RESEARCH_BARS),
        pa.Table.from_pylist(members, schema=UNIVERSE),
        output / "snapshot",
        SnapshotSpec("synthetic", "quant_mine_demo_v1", "raw", "shares", "synthetic"),
    )
    (output / "execution").mkdir()
    mapping = []
    for member in members:
        instrument = member["instrument"]
        # 合成世界事先声明没有企业行动；真实数据不得据此补造零分红或拆股。
        execution = [
            {
                "date": row["date"],
                "symbol": instrument,
                **{
                    key: row[key].quantize(Decimal(".000001"))
                    for key in ("open", "high", "low", "close")
                },
                "volume": int(row["volume"]),
                "split_ratio": 1,
                "dividend": Decimal(0),
                "dividend_pay_date": None,
            }
            for row in rows
            if row["instrument"] == instrument
        ]
        pq.write_table(
            pa.Table.from_pylist(
                execution,
                schema=BAR_SCHEMA.with_metadata(
                    {
                        **(BAR_SCHEMA.metadata or {}),
                        b"source": b"synthetic",
                        b"volume_unit": b"shares",
                        b"corporate_actions": b"synthetic_none",
                    }
                ),
            ),
            output / "execution" / f"{instrument}.parquet",
            compression="zstd",
        )
        mapping.append(f'{instrument} = "execution/{instrument}.parquet"')
    config = output / "mine.toml"
    config.write_text("""snapshot = "snapshot"
train_start = 2022-02-01
train_end = 2022-05-31
validation_start = 2022-06-01
validation_end = 2022-10-31
test_start = 2022-11-01
test_end = 2022-12-30
known_through = 2022-10-31
families = ["momentum", "reversal", "volatility", "volume_trend", "range_position", "price_volume"]
windows = [5, 10, 20]
candidate_budget = 18
seed = 19
max_depth = 12
max_nodes = 80
horizon = 5
quantiles = 4
min_sessions = 10
min_coverage = 0.8
min_train_ic = 0.02
min_validation_ic = 0.02
max_correlation = 0.9
min_incremental_ic = 0.005
pool_size = 5
allow_exploratory = false
""")
    config.write_text(
        config.read_text()
        + """
[cost_screen]
initial_cash = "5000"
min_return = 0.0
min_excess_return = 0.0
max_drawdown = 0.15
min_fills = 2
[cost_screen.execution]
"""
        + "\n".join(mapping)
        + """
[cost_screen.policy]
top_k = 3
allocation = "0.8"
position_cap = "0.3"
commission = "1"
slippage_bps = "5"
rebalance_sessions = 5
stop_loss = "0.08"
trailing_stop = "0.12"
take_profit = "0.2"
max_holding_sessions = 30
cooldown_sessions = 5
account_drawdown = "0.15"
exit_mode = "protective"
sale_proceeds = "next_session"
participation = "0.05"
allow_exploratory = false
"""
    )
    return invest_main(["mine", "--config", str(config), "--output", str(output / "study")])


if __name__ == "__main__":
    raise SystemExit(main())
