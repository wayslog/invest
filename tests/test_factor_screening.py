"""检验搜索校正和真实组合成本门槛，不把合成成功解释为策略资格。"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.factor_mining import run_mining
from invest.factor_statistics import corrected_ic_test
from invest.market import BAR_SCHEMA
from invest.research_data import digest
from tests.test_factor_mining import mining_config, research_snapshot


def test_block_sign_test_and_full_family_correction_match_exact_counts() -> None:
    values = pd.Series([1.0] * 10)
    raw, adjusted, blocks = corrected_ic_test(
        values, direction=1, block_size=1, family_size=20, resamples=9999, seed=0
    )
    assert (raw, adjusted, blocks) == (1 / 1024, 20 / 1024, 10)
    raw, adjusted, blocks = corrected_ic_test(
        values, direction=1, block_size=2, family_size=20, resamples=9999, seed=0
    )
    assert (raw, adjusted, blocks) == (1 / 32, 20 / 32, 5)
    assert corrected_ic_test(
        values, direction=-1, block_size=2, family_size=20, resamples=999, seed=0
    )[:2] == (1, 1)


def test_randomized_pvalues_never_zero_and_missing_dates_keep_block_boundaries() -> None:
    values = pd.Series([1.0] * 100)
    args = dict(direction=1, block_size=2, family_size=5, resamples=999, seed=0)
    result = corrected_ic_test(values, **args)
    assert result == corrected_ic_test(values, **args)
    assert result[0] >= 1 / 1000
    assert corrected_ic_test(values, **{**args, "seed": -1}) == corrected_ic_test(
        values, **{**args, "seed": 1}
    )
    assert corrected_ic_test(pd.Series([1.0, float("nan"), float("nan"), 1.0]), **args)[2] == 2


def screened_case(root: Path, commission: int = 1, changed_after: int = 1000) -> Path:
    data = research_snapshot(root, changed_after=changed_after)
    config = mining_config(root, data)
    folder = root / "execution"
    folder.mkdir()
    mapping = []
    for instrument in data.universe["instrument"].to_pylist():
        rows = [
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
            for row in data.bars.to_pylist()
            if row["instrument"] == instrument
        ]
        pq.write_table(
            pa.Table.from_pylist(
                rows,
                schema=BAR_SCHEMA.with_metadata(
                    {**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"}
                ),
            ),
            folder / f"{instrument}.parquet",
            compression="zstd",
        )
        mapping.append(f'{instrument} = "execution/{instrument}.parquet"')
    config.write_text(
        config.read_text()
        + f'''
[cost_screen]
initial_cash = "5000"
min_fills = 1
[cost_screen.execution]
{chr(10).join(mapping)}
[cost_screen.policy]
top_k = 2
position_cap = "0.4"
commission = "{commission}"
'''
    )
    return config


def test_cost_selection_uses_shared_engine_and_preserves_heldout_prices(tmp_path: Path) -> None:
    results = []
    for label, changed in (("original", 1000), ("changed", 120)):
        root = tmp_path / label
        root.mkdir()
        config = screened_case(root, changed_after=changed)
        before = {path: digest(path) for path in root.rglob("*.parquet")}
        result = run_mining(config, root / "study", cache_root=root / "cache")
        assert result.selected == 1
        assert all(digest(path) == value for path, value in before.items())
        selected = [
            row
            for row in pq.read_table(result.directory / "trials.parquet").to_pylist()
            if row["status"] == "selected"
        ][0]
        assert selected["cost_status"] == "passed" and selected["stress_return"] > 0
        checks = pq.read_table(
            result.directory
            / "cost_screen"
            / f"trial_{selected['trial_id']:04d}"
            / "strategy_checks.parquet"
        )
        assert checks.num_rows > 0 and set(checks["status"].to_pylist()) == {"pass"}
        results.append(pq.read_table(result.directory / "trials.parquet"))
    assert results[0].equals(results[1], check_metadata=False)
    from invest.backtest_study import run_backtest

    bad = tmp_path / "original" / "changed_policy.toml"
    bad.write_text("""snapshot = "snapshot"
factor_pool = "study/factor_pool.parquet"
start = 2022-06-27
end = 2022-07-01
known_through = 2022-07-01
initial_cash = "5000"
[execution]
SYNTH1 = "execution/SYNTH1.parquet"
[policy]
commission = "2"
""")
    with pytest.raises(ValueError, match="match the mining cost screen"):
        run_backtest(bad, tmp_path / "wrong_policy", cache_root=tmp_path / "cache")
    assert not (tmp_path / "wrong_policy").exists()


def test_expensive_strategy_is_rejected_despite_perfect_rank_ic(tmp_path: Path) -> None:
    config = screened_case(tmp_path, commission=400)
    result = run_mining(config, tmp_path / "study", cache_root=tmp_path / "cache")
    assert result.selected == 0 and result.status == "rejected"
    rows = pq.read_table(result.directory / "trials.parquet").to_pylist()
    assert all(row["adjusted_pvalue"] <= 0.05 for row in rows)
    assert all(row["cost_status"] == "rejected" for row in rows)
    assert all(
        row["reason"]
        in {
            "nonpositive_net_return",
            "insufficient_cost_evidence",
            "insufficient_net_excess",
            "cost_drawdown_limit",
        }
        for row in rows
    )


@pytest.mark.parametrize("scenario", ["strategy", "equal_weight", "double_cost"])
def test_cost_audit_failure_preserves_evidence_and_prevents_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    import invest.factor_costs as costs
    from invest.backtest import BacktestResult, simulate_signals

    config = screened_case(tmp_path)
    calls = 0

    def mismatched_order(*args: Any, **kwargs: Any) -> BacktestResult:
        nonlocal calls
        simulation = simulate_signals(*args, **kwargs)
        name = ("strategy", "equal_weight", "double_cost")[calls % 3]
        calls += 1
        if name != scenario:
            return simulation
        # 只破坏订单关联，保留收益和金额，让真实独立审计发现错误。
        fills = simulation.portfolio.trades
        rows = fills.to_pylist()
        assert rows
        rows[0]["order_id"] = "missing_order"
        return replace(
            simulation,
            portfolio=replace(
                simulation.portfolio, trades=pa.Table.from_pylist(rows, schema=fills.schema)
            ),
        )

    monkeypatch.setattr(costs, "simulate_signals", mismatched_order)
    output = tmp_path / "study"
    with pytest.raises(ValueError, match=f"Independent accounting failed.*{scenario}"):
        run_mining(config, output, cache_root=tmp_path / "cache")
    trials = pq.read_table(output / "trials.parquet").to_pylist()
    assert len(trials) == 1 and trials[0]["status"] == "error"
    assert trials[0]["cost_status"] != "passed"
    folder = output / "cost_screen" / f"trial_{trials[0]['trial_id']:04d}"
    checks = pq.read_table(folder / f"{scenario}_checks.parquet").to_pylist()
    assert any(
        row["check"].endswith("order_timing_quantity") and row["status"] == "error"
        for row in checks
    )
    assert (
        "missing_order"
        in pq.read_table(folder / f"{scenario}_fills.parquet")["order_id"].to_pylist()
    )
    assert not (output / "factor_pool.parquet").exists()
    assert not (output / "run.parquet").exists()


def test_larger_declared_search_family_rejects_the_same_ic(tmp_path: Path) -> None:
    data = research_snapshot(tmp_path)
    path = mining_config(tmp_path, data)
    path.write_text(path.read_text() + "test_family_size = 1000\n")
    result = run_mining(path, tmp_path / "study", cache_root=tmp_path / "cache")
    assert result.selected == 0
    assert {
        row["reason"] for row in pq.read_table(result.directory / "trials.parquet").to_pylist()
    } == {"multiple_testing_rejected"}


@pytest.mark.parametrize(
    "setting",
    ["test_alpha = 0", "test_block_size = 0", "test_family_size = 2", "test_resamples = 2"],
)
def test_invalid_statistical_budget_is_rejected_before_registration(
    tmp_path: Path, setting: str
) -> None:
    from invest.mining_config import load_mining_config

    path = mining_config(tmp_path, research_snapshot(tmp_path))
    path.write_text(path.read_text().replace("test_block_size = 1\n", "") + setting)
    with pytest.raises(ValueError, match="configuration"):
        load_mining_config(path)
