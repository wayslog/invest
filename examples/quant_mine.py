"""P2 离线合成演示：模板搜索、因子筛选、冻结与排名，不代表策略收益。"""

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa

from invest.cli import main as invest_main
from invest.contracts import RESEARCH_BARS, UNIVERSE, SnapshotSpec
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
    config = output / "mine.toml"
    config.write_text("""snapshot = "snapshot"
train_start = 2022-02-01
train_end = 2022-06-30
validation_start = 2022-07-01
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
    return invest_main(["mine", "--config", str(config), "--output", str(output / "study")])


if __name__ == "__main__":
    raise SystemExit(main())
