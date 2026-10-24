"""P3 离线验收：合成因子挖掘、冻结信号、共享策略回测与只读重放。"""

import argparse
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from quant_mine import main as mining_demo

from invest.cli import main as invest_main
from invest.market import BAR_SCHEMA
from invest.research_data import load_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if mining_demo(["--output", str(output / "mining")]):
        raise ValueError("Synthetic mining did not select any factors")
    snapshot = load_snapshot(output / "mining" / "snapshot")
    (output / "execution").mkdir()
    mapping = []
    for instrument in snapshot.universe["instrument"].to_pylist():
        # 该合成世界事先定义没有企业行动；真实行情不能用此方式补造分红和拆股。
        rows = [
            {
                "date": row["date"],
                "symbol": instrument,
                **{
                    name: row[name].quantize(Decimal(".000001"))
                    for name in ("open", "high", "low", "close")
                },
                "volume": int(row["volume"]),
                "split_ratio": 1,
                "dividend": Decimal(0),
                "dividend_pay_date": None,
            }
            for row in snapshot.bars.to_pylist()
            if row["instrument"] == instrument
        ]
        table = pa.Table.from_pylist(
            rows,
            schema=BAR_SCHEMA.with_metadata(
                {
                    **(BAR_SCHEMA.metadata or {}),
                    b"source": b"synthetic",
                    b"corporate_actions": b"synthetic_none",
                    b"volume_unit": b"shares",
                }
            ),
        )
        pq.write_table(table, output / "execution" / f"{instrument}.parquet", compression="zstd")
        mapping.append(f'{instrument} = "execution/{instrument}.parquet"')
    config = output / "backtest.toml"
    config.write_text(
        """snapshot = "mining/snapshot"
factor_pool = "mining/study/factor_pool.parquet"
start = 2022-11-01
end = 2022-12-30
known_through = 2022-12-30
initial_cash = "5000"
[execution]
"""
        + "\n".join(mapping)
        + """
[policy]
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
    status = invest_main(
        ["backtest", "--config", str(config), "--output", str(output / "backtest")]
    )
    if status:
        return status
    return invest_main(["verify-backtest", "--study", str(output / "backtest")])


if __name__ == "__main__":
    raise SystemExit(main())
