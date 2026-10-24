"""P4 完整离线演示：挖掘、回测、同规则当前决策与不可变结果重放。"""

import argparse
from pathlib import Path

import pyarrow.parquet as pq
from quant_backtest import main as backtest_demo

from invest.cli import main as invest_main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if backtest_demo(["--output", str(output / "research")]):
        return 1
    study = output / "research" / "backtest"
    day = pq.read_table(study / "decision_contexts.parquet")["date"][-1].as_py()
    config = output / "decide.toml"
    config.write_text(f"""strategy = "research/backtest"
snapshot = "research/backtest/inference"
context = "research/backtest/decision_contexts.parquet"
known_through = {day}
""")
    status = invest_main(
        [
            "decide",
            "--config",
            str(config),
            "--output",
            str(output / "decision"),
            "--as-of",
            str(day),
        ]
    )
    if status:
        return status
    expected = [
        row for row in pq.read_table(study / "actions.parquet").to_pylist() if row["date"] == day
    ]
    if pq.read_table(output / "decision" / "actions.parquet").to_pylist() != expected:
        raise ValueError("Current actions differ from the same backtest decision context")
    return invest_main(["verify-decision", "--study", str(output / "decision")])


if __name__ == "__main__":
    raise SystemExit(main())
