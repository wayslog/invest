"""只读取得 IBKR/WSH 企业行动回执；查询成功不代表历史覆盖完整。"""

import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.engine import engine_digest
from invest.ibkr_data import SCHEMAS, decoded, schema
from invest.ibkr_gateway import IBKRGateway
from invest.ibkr_models import IBKRConfig
from invest.ibkr_store import publish
from invest.research_artifacts import protect_inputs, seal_artifacts

EVENT_TYPES = ("wshe_div", "wshe_splits")
REQUEST_SCHEMA = schema(
    "corporate-action-requests",
    [
        ("con_id", pa.int64()),
        ("event_type", pa.string()),
        ("status", pa.string()),
        ("error_type", pa.string()),
        ("coverage_status", pa.string()),
    ],
)
MANIFEST_SCHEMA = schema(
    "corporate-action-capture",
    [
        ("source", pa.string()),
        ("upstream_provider", pa.string()),
        ("environment", pa.string()),
        ("started_at", pa.timestamp("us", tz="UTC")),
        ("finished_at", pa.timestamp("us", tz="UTC")),
        ("client_id", pa.int64()),
        ("source_ref", pa.string()),
        ("status", pa.string()),
        ("error_type", pa.string()),
        ("engine_sha256", pa.string()),
        ("sdk_version", pa.string()),
        ("corporate_actions_complete", pa.bool_()),
    ],
)


def _tags(value: Any) -> set[str]:
    """只识别元数据明确返回的标签，不从文字说明猜测事件类型。"""
    if isinstance(value, dict):
        return set(value) | set().union(*(_tags(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_tags(item) for item in value))
    return {value} if isinstance(value, str) else set()


def capture_events(config: IBKRConfig, capture: Path, output: Path) -> dict[str, Any]:
    """读取已采集的稳定合约身份，分别请求分红和拆股；不请求或变更订单。"""
    protect_inputs((output,), (capture,))
    if any((parent / "registration.parquet").is_file() for parent in output.resolve().parents):
        raise ValueError("Corporate-action output cannot be inside a registered account or study")
    bodies = {name: (capture / f"{name}.parquet").read_bytes() for name in SCHEMAS}
    tables = {name: pq.read_table(pa.BufferReader(body)) for name, body in bodies.items()}
    for name, table in tables.items():
        metadata = table.schema.metadata or {}
        if not table.schema.equals(SCHEMAS[name], check_metadata=False) or any(
            metadata.get(key) != value for key, value in (SCHEMAS[name].metadata or {}).items()
        ):
            raise ValueError("Invalid source capture schema")
    rows = tables["capture"].to_pylist()
    if len(rows) != 1:
        raise ValueError("Corporate actions require one identified market capture")
    manifest = rows[0]
    if (
        manifest["source"] != "ibkr"
        or manifest["environment"] != "paper"
        or not manifest["account"]
        or not manifest["account"].startswith("DU")
        or manifest["captured_at"] is None
        or not manifest["complete"]
        or "error" in tables["quality"]["status"].to_pylist()
    ):
        raise ValueError("Corporate actions require a complete IBKR Paper market capture")
    expected = {
        b"source": b"ibkr",
        b"environment": b"paper",
        b"account": manifest["account"].encode(),
        b"captured_at": manifest["captured_at"].isoformat().encode(),
    }
    if any(
        (table.schema.metadata or {}).get(key) != value
        for table in tables.values()
        for key, value in expected.items()
    ):
        raise ValueError("Market capture provenance differs between tables")
    contracts = tables["contracts"].to_pylist()
    if (
        not contracts
        or len({row["con_id"] for row in contracts}) != len(contracts)
        or any(
            row["con_id"] is None
            or row["con_id"] <= 0
            or row["currency"] != "USD"
            or row["security_type"] != "STK"
            for row in contracts
        )
    ):
        raise ValueError("Corporate actions require unique qualified USD stock identities")
    if config.client_id in {71, 72, 73}:
        raise ValueError(
            "Use a separate corporate-action client, not diagnostics or account clients"
        )
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "market_capture"
    frozen.mkdir()
    # 只冻结用于选定证券和确认来源的表；不另存账户余额、持仓和订单。
    for name in ("capture", "contracts", "historical"):
        (frozen / f"{name}.parquet").write_bytes(bodies[name])
    started = datetime.now(UTC)
    broker = IBKRGateway(config)
    requests = [
        {
            "con_id": row["con_id"],
            "event_type": kind,
            "status": "not_requested",
            "error_type": "",
            "coverage_status": "unverified",
        }
        for row in sorted(contracts, key=lambda row: row["con_id"])
        for kind in EVENT_TYPES
    ]
    error_type = ""
    try:
        with broker:
            if broker.account != manifest["account"]:
                raise ValueError("Corporate-action session differs from the source Paper account")
            metadata_response = json.loads(broker._query("getWshMetaData"))
            if not isinstance(metadata_response, (list, dict)):
                raise ValueError("WSH metadata must contain a JSON collection")
            tags = _tags(metadata_response)
            for row in requests:
                if row["event_type"] not in tags:
                    row["status"] = "unsupported"
                    continue
                try:
                    # 当前协议每次只允许一个事件标签；filter 不能与 conId/日期参数混用。
                    request = broker.sdk.WshEventData(
                        filter=json.dumps(
                            {
                                "country": "All",
                                "watchlist": [str(row["con_id"])],
                                row["event_type"]: True,
                            }
                        ),
                        totalLimit=100,
                    )
                    received = json.loads(broker._query("getWshEventData", request))
                    if not isinstance(received, (list, dict)):
                        raise ValueError("WSH event response must contain a JSON collection")
                    row["status"] = "received"
                except (OSError, ValueError, TimeoutError) as exc:
                    row["status"], row["error_type"] = "failed", type(exc).__name__
                    # SDK 超时不会自动清除请求编号；下一次查询前取消本客户端的事件订阅。
                    broker.ib.cancelWshEventData()
    except Exception as exc:
        error_type = type(exc).__name__
        broker.raw.append(
            decoded("corporate_action_capture", started, {"error_type": error_type}, complete=False)
        )
    status = (
        "captured"
        if not error_type and not broker.errors and all(r["status"] == "received" for r in requests)
        else "blocked"
    )
    result = {
        "source": "ibkr",
        "upstream_provider": "wall_street_horizon",
        "environment": "paper",
        "started_at": started,
        "finished_at": datetime.now(UTC),
        "client_id": config.client_id,
        "source_ref": str(capture.resolve()),
        "status": status,
        "error_type": error_type,
        "engine_sha256": engine_digest(),
        "sdk_version": version("ib_async"),
        "corporate_actions_complete": False,
    }
    metadata = {
        b"source": b"ibkr",
        b"upstream_provider": b"wall_street_horizon",
        b"environment": b"paper",
        b"coverage_status": b"unverified",
    }
    for name, table in (
        ("raw", pa.Table.from_pylist(broker.raw, schema=SCHEMAS["raw"])),
        ("requests", pa.Table.from_pylist(requests, schema=REQUEST_SCHEMA)),
        ("capture", pa.Table.from_pylist([result], schema=MANIFEST_SCHEMA)),
    ):
        publish(
            table.replace_schema_metadata({**(table.schema.metadata or {}), **metadata}),
            output / f"{name}.parquet",
        )
    seal_artifacts(output)
    return {
        "capture": str(output),
        "status": status,
        "received_requests": sum(row["status"] == "received" for row in requests),
        "total_requests": len(requests),
        "corporate_actions_complete": False,
    }
