"""P1 离线演示：合成行情到缓存、因子、标签和 RankIC，不读写资金账户。"""

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from invest.contracts import RESEARCH_BARS, UNIVERSE, SnapshotSpec
from invest.factor_diagnostics import diagnose_factor, forward_labels, qlib_dataset_frame
from invest.qlib_adapter import calculate_factors
from invest.quality import regular_sessions
from invest.research_data import create_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output: Path = args.output
    if output.exists():
        raise FileExistsError("Use a new output directory; existing research is immutable")
    sessions = regular_sessions(date(2024, 1, 2), date(2024, 2, 2)).to_pylist()
    rows, members = [], []
    captured = datetime(2024, 2, 3, tzinfo=UTC)
    for number in range(1, 6):
        instrument = f"SYNTH{number}"
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
            price = Decimal(100 + number * index)
            rows.append(
                {
                    "date": session["date"],
                    "instrument": instrument,
                    "open": price,
                    "high": price + 2,
                    "low": price - 2,
                    "close": price + 1,
                    "volume": Decimal(1000 * number),
                    "available_at": session["close_at"],
                    "captured_at": captured,
                }
            )
    snapshot = create_snapshot(
        pa.Table.from_pylist(rows, schema=RESEARCH_BARS),
        pa.Table.from_pylist(members, schema=UNIVERSE),
        output / "snapshot",
        SnapshotSpec("synthetic", "quant_data_demo_v1", "raw", "shares", "synthetic"),
    )
    factors = calculate_factors(
        snapshot, {"momentum": "$close/Ref($close,2)-1", "mean_close": "Mean($close,3)"}
    )
    labels = forward_labels(snapshot, (1, 5))
    result = diagnose_factor(factors, labels, "momentum", quantiles=5, max_loss=0.4)
    for name, table in (("factors", factors.table), ("labels", labels.table)):
        pq.write_table(table, output / f"{name}.parquet", compression="zstd")
    qlib_dataset_frame(factors, labels).to_parquet(
        output / "qlib_dataset.parquet", compression="zstd"
    )
    result.rank_ic.to_parquet(output / "rank_ic.parquet", compression="zstd")
    summary = {
        **result.clean.attrs["invest"],
        "input_rows": result.input_rows,
        "retained_rows": result.retained_rows,
        "loss_fraction": result.loss_fraction,
        "timing_rejected_rows": result.timing_rejected_rows,
    }
    pq.write_table(
        pa.Table.from_pylist([summary]), output / "diagnostics.parquet", compression="zstd"
    )
    print(f"P1 synthetic data pipeline completed: {output}")
    print(
        f"Factor rows: {result.input_rows}; retained: {result.retained_rows}; "
        f"loss: {result.loss_fraction:.3f}"
    )


if __name__ == "__main__":
    main()
