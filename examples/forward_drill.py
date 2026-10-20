"""Reproducible synthetic M3 operations drill; never forward investment evidence."""

import argparse
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from invest.forward import (
    control_forward,
    forward_status,
    init_forward,
    run_forward,
    verify_forward,
)
from invest.forward_ops import backup_forward, restore_forward
from invest.market import BAR_SCHEMA
from invest.quality import regular_sessions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    root = parser.parse_args().output
    if root.exists():
        raise ValueError("Drill output already exists; keep previous evidence")
    root.mkdir(parents=True)
    schedule = regular_sessions(date(2024, 1, 2), date(2024, 1, 19)).to_pylist()
    policy = root / "policy.toml"
    policy.write_text(
        Path("configs/m2.toml")
        .read_text()
        .replace("[40, 60, 80]", "[2, 3]")
        .replace("correlation_window = 60", "correlation_window = 3")
        .replace("rebalance_sessions = 21", "rebalance_sessions = 3")
    )
    observation = root / "observation.toml"
    observation.write_text(
        'name="m3-controlled-drill"\nmode="drill"\nsymbols=["SPY","XLF"]\n'
        'candidate="trend-2"\nstart_session=2024-01-08\nsessions=8\n'
        "minimum_fills=2\nmax_capture_age_minutes=120\n"
    )
    prices = {
        "SPY": [100, 101, 103, 102, 105, 104, 107, 108, 30, 31, 32, 33, 34],
        "XLF": [90, 93, 91, 94, 92, 95, 93, 96, 29, 30, 31, 32, 33],
    }
    sources = {s: root / f"{s}.parquet" for s in prices}
    tables = {}
    for symbol, values in prices.items():
        rows = [
            {
                "date": day["date"],
                "symbol": symbol,
                "open": Decimal(value),
                "close": Decimal(value),
                "high": Decimal(value + 1),
                "low": Decimal(value - 1),
                "volume": 1000,
                "split_ratio": 1,
                "dividend": Decimal(0),
                "dividend_pay_date": None,
            }
            for day, value in zip(schedule, values, strict=True)
        ]
        tables[symbol] = pa.Table.from_pylist(
            rows,
            schema=BAR_SCHEMA.with_metadata(
                {**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"}
            ),
        )
        pq.write_table(tables[symbol].slice(0, 4), sources[symbol], compression="zstd")
    account = root / "account"
    init_forward(
        account, observation, policy, sources, at=schedule[3]["close_at"] + timedelta(minutes=5)
    )
    for length in [5, 6, 8, 9, 10, 11, 12]:
        now = schedule[length - 1]["close_at"] + timedelta(minutes=5)
        for symbol, table in tables.items():
            pq.write_table(table.slice(0, length), sources[symbol], compression="zstd")
        result = run_forward(account, sources, at=now)
        if result["status"] == "paused":
            control_forward(account, "resume", "drill-operator", "Reviewed missed task", at=now)
        assert (
            run_forward(account, sources, at=now)["updated"] is False
            if result["status"] != "completed"
            else True
        )
        if length == 9:
            backup = backup_forward(account, root / "backup")
            restore_forward(
                root / "backup",
                root / "restored",
                backup["head"],
                "drill-operator",
                "Restore after simulated host loss",
                at=now,
            )
            assert verify_forward(root / "restored")["status"] == "verified"
    check = verify_forward(account)
    status = forward_status(account, at=schedule[11]["close_at"] + timedelta(minutes=5))
    assert status["operations"] == "completed"
    assert status["risk_status"] != "active"
    assert not status["coverage_met"]  # A missed task cannot be repaired into timely evidence.
    pq.write_table(
        pa.Table.from_pylist([{**status, **check}]), root / "summary.parquet", compression="zstd"
    )
    (root / "README.md").write_text(
        "# M3 合成故障演练\n\n演练包含先持久化决策、延迟核算、重复任务、漏跑、"
        "暂停复核、风险停用、备份和恢复。恢复副本保持同一资金账户与风险状态。\n\n"
        f"对账 {check['reconciliation_checks']} 项通过；"
        "因主动漏跑，观察覆盖率不通过。此目录不构成真实前向投资记录。\n",
        encoding="utf-8",
    )
    print(f"Drill verified: {root}; {check['reconciliation_checks']} reconciliation checks")


if __name__ == "__main__":
    main()
