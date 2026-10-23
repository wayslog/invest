"""Read-only IBKR socket/session probes in a separate Python runtime on the VPS.

The socket check stops after protocol negotiation. The SDK starts an API session
only. No order or account mutation requests are implemented. Private replies stay
in a host-local Parquet receipt.
"""

import importlib
import io
import json
import logging
import socket
import struct
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

CLIENT_ID = 71  # Same dedicated nonzero client as the M4 adapter.
PROTOCOL = b"v157..178"  # Same negotiated range as the selected ib_async 2.1.0.
SCHEMA = pa.schema(
    [
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("finished_at", pa.timestamp("us", tz="UTC")),
        ("host", pa.string()),
        ("port", pa.int32()),
        ("client_id", pa.int32()),
        ("method", pa.string()),
        ("tcp_connected", pa.bool_()),
        ("handshake_ok", pa.bool_()),
        ("api_ready", pa.bool_()),
        ("server_version", pa.int32()),
        ("server_connection_time", pa.string()),
        ("managed_accounts", pa.list_(pa.string())),
        ("paper_accounts_only", pa.bool_()),
        ("next_valid_id_received", pa.bool_()),
        ("error_codes", pa.list_(pa.int32())),
        ("outcome", pa.string()),
        ("error_type", pa.string()),
        ("messages", pa.list_(pa.struct([("direction", pa.string()), ("payload", pa.binary())]))),
    ],
    metadata={b"schema": b"invest.ibkr.connectivity-probe.v2", b"source": b"ibkr"},
)


def frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


def receive(connection: socket.socket, deadline: float) -> bytes:
    def exact(size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("IBKR probe deadline")
            connection.settimeout(remaining)
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise EOFError("IBKR peer closed the connection")
            data.extend(chunk)
        return bytes(data)

    size = struct.unpack(">I", exact(4))[0]
    if not 0 < size <= 2_000_000:
        raise ValueError("Not an IBKR API frame")
    return exact(size)


def new_row(host: str, port: int, client_id: int | None, method: str) -> dict[str, Any]:
    return {
        "observed_at": datetime.now(UTC),
        "host": host,
        "port": port,
        "client_id": client_id,
        "method": method,
        "tcp_connected": False,
        "handshake_ok": False,
        "api_ready": False,
        "server_version": None,
        "server_connection_time": None,
        "managed_accounts": [],
        "paper_accounts_only": False,
        "next_valid_id_received": False,
        "error_codes": [],
        "outcome": "tcp_connect_failed",
        "error_type": None,
        "messages": [],
    }


def probe(host: str = "127.0.0.1", port: int = 4002, timeout: float = 12) -> dict[str, Any]:
    row = new_row(host, port, None, "socket_handshake")
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            row["tcp_connected"] = True
            row["outcome"] = "handshake_failed"
            connection.sendall(b"API\0" + frame(PROTOCOL))
            row["messages"].append({"direction": "sent", "payload": b"API\0" + PROTOCOL})
            reply = receive(connection, deadline)
            row["messages"].append({"direction": "received", "payload": reply})
            fields = reply.decode().rstrip("\0").split("\0")
            if len(fields) != 2 or not 157 <= int(fields[0]) <= 178:
                raise ValueError("Unsupported IBKR handshake")
            row["server_version"], row["server_connection_time"] = int(fields[0]), fields[1]
            row["handshake_ok"] = True
            row["outcome"] = "handshake_ok"
    except (OSError, EOFError, ValueError) as error:
        row["error_type"] = type(error).__name__
    row["finished_at"] = datetime.now(UTC)
    return row


def save_receipt(row: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    observed_at: datetime = row["observed_at"]
    name = observed_at.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex
    temporary = directory / (name + ".tmp")
    path = directory / (name + ".parquet")
    pq.write_table(pa.Table.from_pylist([row], schema=SCHEMA), temporary, compression="zstd")
    temporary.chmod(0o600)
    temporary.rename(path)
    return path


def public_summary(row: dict[str, Any], receipt: Path) -> dict[str, Any]:
    fields = (
        "observed_at",
        "finished_at",
        "host",
        "port",
        "method",
        "tcp_connected",
        "handshake_ok",
        "api_ready",
        "server_version",
        "paper_accounts_only",
        "error_codes",
        "outcome",
        "error_type",
    )
    return {
        **{key: row[key] for key in fields},
        "account_count": len(row["managed_accounts"]),
        "receipt": str(receipt),
    }


def sdk_probe(host: str = "127.0.0.1", port: int = 4002, *, sdk: Any = None) -> dict[str, Any]:
    if sdk is None:
        sdk = importlib.import_module("ib_async")
    row = new_row(host, port, CLIENT_ID, "ib_async-2.1.0")
    output = io.StringIO()
    logger = logging.getLogger("ib_async")
    handler = logging.StreamHandler(output)
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    ib = sdk.IB()
    try:
        with socket.create_connection((host, port), timeout=10):
            row["tcp_connected"] = True
        row["outcome"] = "sdk_session_not_ready"
        # Client.connect starts the API session only. No account synchronization,
        # order queries or auto-binding occur; client 0 is never used.
        ib.client.connect(host, port, clientId=CLIENT_ID, timeout=10)
        row["api_ready"] = ib.client.isReady()
        if not row["api_ready"]:
            raise ConnectionError("SDK returned before the API session was ready")
        row["managed_accounts"] = ib.client.getAccounts()
        row["next_valid_id_received"] = ib.client.isReady()
        row["paper_accounts_only"] = bool(row["managed_accounts"]) and all(
            account.startswith("DU") for account in row["managed_accounts"]
        )
        row["server_version"] = ib.client.serverVersion()
        row["handshake_ok"] = bool(row["server_version"])
        row["outcome"] = "ok" if row["paper_accounts_only"] else "unexpected_account_type"
    except (OSError, EOFError, ValueError) as error:
        row["error_type"] = type(error).__name__
    finally:
        ib.disconnect()
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        row["messages"] = [{"direction": "sdk_debug", "payload": output.getvalue().encode()}]
    row["finished_at"] = datetime.now(UTC)
    return row


def main() -> None:
    directory = Path("/var/lib/invest/operations/ibkr-probes")
    row = probe()
    path = save_receipt(row, directory)
    sdk_row = sdk_probe()
    sdk_path = save_receipt(sdk_row, directory)
    print(
        json.dumps(
            {
                "outcome": sdk_row["outcome"],
                "socket": public_summary(row, path),
                "sdk": public_summary(sdk_row, sdk_path),
            },
            default=str,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
