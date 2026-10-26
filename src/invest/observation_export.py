"""只读导出既有现金观察的身份和历史状态，不映射为券商全账户。"""

from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa

from invest import ibkr_observation
from invest.ibkr_data import schema
from invest.ibkr_store import publish
from invest.market import MONEY
from invest.research_artifacts import protect_inputs, seal_artifacts

STATE_SCHEMA = schema(
    "cash-observation-export",
    [
        ("account_id", pa.string()),
        ("broker_account", pa.string()),
        ("source", pa.string()),
        ("capital_scope", pa.string()),
        ("source_ref", pa.string()),
        ("head", pa.string()),
        ("registration_engine_sha256", pa.string()),
        ("exported_at", pa.timestamp("us", tz="UTC")),
        ("initial_cash", MONEY),
        ("cash", MONEY),
        ("peak_equity", MONEY),
        ("risk_status", pa.string()),
        ("operations", pa.string()),
        ("last_session", pa.date32()),
        ("sessions", pa.int64()),
        ("missed_sessions", pa.int64()),
        ("registered_sessions", pa.int64()),
        ("observation_start_session", pa.date32()),
        ("observation_end_session", pa.date32()),
        ("broker_context_eligible", pa.bool_()),
    ],
)


def _files(account: Path) -> dict[str, bytes]:
    names = ["registration.parquet", "schedule.parquet", "config.toml"]
    names.extend(
        str(path.relative_to(account)) for path in sorted((account / "events").glob("*.parquet"))
    )
    return {name: (account / name).read_bytes() for name in names}


def export_observation(account: Path, output: Path) -> dict[str, Any]:
    """冻结已提交前缀后导出，不取得写锁、不修改注册、不运行日结或补造策略历史。"""
    protect_inputs((output,), (account,))
    if any((parent / "registration.parquet").is_file() for parent in output.resolve().parents):
        raise ValueError("Observation export cannot write inside a registered account or study")
    bodies = _files(account)
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "source_account"
    for name, body in bodies.items():
        path = frozen / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    # 读取冻结的前缀，避免导出过程中定时器推进使几张表来自不同状态。
    registration, days, _ = ibkr_observation._load(frozen)
    now = ibkr_observation.clock()
    status = ibkr_observation._status(frozen, now)
    if bodies != _files(account):
        raise ValueError("Observation changed during export; retry into a new directory")
    row = {
        "account_id": registration["account_id"],
        "broker_account": registration["broker_account"],
        "source": registration["source"],
        "capital_scope": "project_cash_observation",
        "source_ref": str(account.resolve()),
        "head": status["head"],
        "registration_engine_sha256": registration["engine_sha256"],
        "exported_at": now,
        "initial_cash": registration["initial_cash"],
        "cash": ibkr_observation.CASH,
        "peak_equity": ibkr_observation.CASH,
        **{
            key: status[key] for key in ("risk_status", "operations", "sessions", "missed_sessions")
        },
        "last_session": date.fromisoformat(status["last_session"]),
        "registered_sessions": registration["sessions"],
        "observation_start_session": days[0]["session"],
        "observation_end_session": days[-1]["session"],
        "broker_context_eligible": False,
    }
    table = pa.Table.from_pylist([row], schema=STATE_SCHEMA)
    publish(
        table.replace_schema_metadata(
            {**(table.schema.metadata or {}), b"context_kind": b"observation_state"}
        ),
        output / "observation_state.parquet",
    )
    seal_artifacts(output)
    return {
        "output": str(output),
        "capital_scope": "project_cash_observation",
        "broker_context_eligible": False,
        "sessions": row["sessions"],
        "missed_sessions": row["missed_sessions"],
    }
