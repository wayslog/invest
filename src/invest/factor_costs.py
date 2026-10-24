"""用正式组合引擎筛选开发候选；验证段收益不授予独立样本外资格。"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.backtest import simulate_signals
from invest.contracts import SIGNAL_SCHEMA, DataSnapshot, SignalFrame, research_schema
from invest.evaluation import evaluate
from invest.mining_config import MiningConfig
from invest.portfolio_audit import audit_backtest
from invest.quality import regular_sessions
from invest.signals import freeze_factor_pool, generate_signal_history

COST_SCHEMA = research_schema(
    "factor_cost_screen",
    [
        ("scenario", pa.string()),
        ("policy_id", pa.string()),
        ("net_return", pa.float64()),
        ("max_drawdown", pa.float64()),
        ("fills", pa.int64()),
        ("closed_cycles", pa.int64()),
    ],
)


def screen_pool(
    selected: list[dict[str, Any]],
    snapshot: DataSnapshot,
    inputs: dict[str, pa.Table],
    config: MiningConfig,
    output: Path,
    cache_root: Path,
) -> dict[str, Any]:
    settings = config.cost_screen
    assert settings is not None
    output.mkdir(parents=True, exist_ok=False)
    pool = freeze_factor_pool(
        [
            {key: row[key] for key in ("factor", "expression", "direction", "trial_id")}
            | {"weight": 1 / len(selected)}
            for row in selected
        ],
        {
            "snapshot_id": snapshot.snapshot_id,
            "source": snapshot.spec.source,
            "price_basis": snapshot.spec.price_basis,
            "volume_unit": snapshot.spec.volume_unit,
            "currency": snapshot.spec.currency,
            "scope": snapshot.scope,
            "knowledge_through": config.train_end.isoformat(),
            "horizon": str(config.horizon),
            "run_id": "development_cost_screen",
            "evidence_status": "development_selection_only",
        },
    )
    pq.write_table(pool.table, output / "pool.parquet", compression="zstd")
    first = inputs[next(iter(inputs))]["date"][0].as_py()
    signals = generate_signal_history(
        pool,
        snapshot,
        first,
        config.validation_end,
        allow_exploratory=config.allow_exploratory,
        cache_root=cache_root,
    )
    pq.write_table(signals.table, output / "signals.parquet", compression="zstd")
    calendar = regular_sessions(first, config.test_end).to_pylist()
    bars = {(row["date"], row["instrument"]): row for row in snapshot.bars.to_pylist()}
    members = snapshot.universe.to_pylist()
    reference_rows: list[dict[str, Any]] = []
    for day, following in zip(calendar[:-1], calendar[1:], strict=True):
        if day["date"] > config.validation_end:
            break
        eligible = sorted(
            {
                member["instrument"]
                for member in members
                if member["start"] <= day["date"] <= member["end"]
                and (
                    (member["available_at"] is None and config.allow_exploratory)
                    or (
                        member["available_at"] is not None
                        and member["available_at"] <= day["close_at"]
                    )
                )
                and (row := bars.get((day["date"], member["instrument"]))) is not None
                and (
                    (row["available_at"] is None and config.allow_exploratory)
                    or (row["available_at"] is not None and row["available_at"] <= day["close_at"])
                )
            }
        )
        reference_rows.extend(
            {
                "date": day["date"],
                "instrument": instrument,
                "score": 1.0,
                "rank": rank + 1,
                "direction": 1,
                "horizon": config.horizon,
                "available_at": day["close_at"],
                "expires_at": following["close_at"],
                "pool_id": pool.metadata["pool_id"],
            }
            for rank, instrument in enumerate(eligible)
        )
    reference = SignalFrame(
        pa.Table.from_pylist(
            reference_rows, schema=SIGNAL_SCHEMA.with_metadata(signals.table.schema.metadata)
        )
    )
    scenarios = {
        "strategy": (signals, settings.policy),
        "equal_weight": (reference, replace(settings.policy, top_k=len(inputs), min_score=0.0)),
        "double_cost": (
            signals,
            replace(
                settings.policy,
                commission=settings.policy.commission * 2,
                slippage_bps=settings.policy.slippage_bps * 2,
            ),
        ),
    }
    records = []
    for name, (frame, policy) in scenarios.items():
        simulation = simulate_signals(
            inputs,
            frame,
            policy,
            config.validation_start,
            config.validation_end,
            initial_cash=settings.initial_cash,
            universe=snapshot.universe,
            availability=snapshot.bars,
        )
        checks, attribution, cycles = audit_backtest(
            inputs, simulation.portfolio, policy, settings.initial_cash, availability=snapshot.bars
        )
        for table_name, table in {
            "actions": simulation.actions,
            "orders": simulation.portfolio.orders,
            "fills": simulation.portfolio.trades,
            "equity": simulation.portfolio.equity,
            "positions": simulation.portfolio.positions,
            "events": simulation.portfolio.events,
            "checks": checks,
            "attribution": attribution,
            "round_trips": cycles,
        }.items():
            pq.write_table(table, output / f"{name}_{table_name}.parquet", compression="zstd")
        if "error" in checks["status"].to_pylist():
            raise ValueError(
                f"Independent accounting failed in cost scenario {name}; "
                "inspect the saved check tables"
            )
        metric = evaluate(simulation.portfolio, settings.initial_cash, cycles).to_pylist()[0]
        records.append(
            {
                "scenario": name,
                "policy_id": policy.policy_id,
                "net_return": metric["total_return"],
                "max_drawdown": metric["max_drawdown"],
                "fills": simulation.portfolio.trades.num_rows,
                "closed_cycles": cycles.num_rows,
            }
        )
    pq.write_table(
        pa.Table.from_pylist(records, schema=COST_SCHEMA),
        output / "metrics.parquet",
        compression="zstd",
    )
    strategy, benchmark, stress = records
    reason = "passed"
    if strategy["fills"] < settings.min_fills or stress["fills"] < settings.min_fills:
        reason = "insufficient_cost_evidence"
    elif (
        strategy["net_return"] <= settings.min_return or stress["net_return"] <= settings.min_return
    ):
        reason = "nonpositive_net_return"
    elif strategy["net_return"] - benchmark["net_return"] < settings.min_excess_return:
        reason = "insufficient_net_excess"
    elif max(abs(strategy["max_drawdown"]), abs(stress["max_drawdown"])) > settings.max_drawdown:
        reason = "cost_drawdown_limit"
    return {
        "cost_status": "passed" if reason == "passed" else "rejected",
        "cost_reason": reason,
        "net_return": strategy["net_return"],
        "stress_return": stress["net_return"],
        "net_excess": strategy["net_return"] - benchmark["net_return"],
        "cost_drawdown": strategy["max_drawdown"],
    }
