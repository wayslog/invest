"""Actual socket framing/session readiness and private host-local probe receipts."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from tests.test_deployment import ROOT, load_tool

probe_tool = load_tool("ibkr_probe")


@contextmanager
def gateway(replies: list[bytes]) -> Iterator[tuple[int, list[bytes]]]:
    sent: list[bytes] = []
    errors: list[BaseException] = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)

        def serve() -> None:
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(2)
                    assert connection.recv(4) == b"API\0"
                    sent.append(probe_tool.receive(connection, time.monotonic() + 2))
                    handshake = probe_tool.frame(b"178\0" + b"20261023 15:00:00 CST\0")
                    # Exercise fragmented length and payload reads.
                    connection.sendall(handshake[:2])
                    connection.sendall(handshake[2:])
                    for _ in range(2):
                        sent.append(probe_tool.receive(connection, time.monotonic() + 2))
                    for reply in replies:
                        connection.sendall(probe_tool.frame(reply))
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield listener.getsockname()[1], sent
        finally:
            thread.join(timeout=3)
            assert not thread.is_alive()
            if errors:
                raise errors[0]


def test_probe_requires_ibkr_api_readiness_and_never_sends_order_messages(tmp_path: Path) -> None:
    with gateway([b"15\0" + b"1\0DU1234567,\0", b"9\0" + b"1\0" + b"42\0"]) as (port, sent):
        row = probe_tool.probe(port=port, timeout=2)
    assert row["outcome"] == "ok"
    assert row["tcp_connected"] and row["handshake_ok"] and row["api_ready"]
    assert row["paper_accounts_only"]
    assert sent == [b"v157..178", f"71\0{2}\0{probe_tool.CLIENT_ID}\0\0".encode(), b"17\0" + b"1\0"]
    receipt = probe_tool.save_receipt(row, tmp_path / "private")
    restored = pq.read_table(receipt).to_pylist()[0]
    assert restored["managed_accounts"] == ["DU1234567"]
    assert restored["messages"] == row["messages"]
    assert pq.ParquetFile(receipt).metadata.row_group(0).column(0).compression == "ZSTD"
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert "DU1234567" not in str(probe_tool.public_summary(row, receipt))
    assert probe_tool.public_summary(row, receipt)["account_count"] == 1


@pytest.mark.parametrize(
    ("replies", "outcome", "codes"),
    [
        ([b"15\0" + b"1\0U1234567,\0", b"9\0" + b"1\0" + b"42\0"], "unexpected_account_type", []),
        ([b"15\0" + b"1\0DU1234567,\0"], "api_session_not_ready", []),
        (
            [b"4\0" + b"2\0-1\0" + b"326\0Client id already in use\0"],
            "api_session_not_ready",
            [326],
        ),
    ],
)
def test_open_port_or_partial_handshake_is_not_a_usable_paper_session(
    replies: list[bytes], outcome: str, codes: list[int]
) -> None:
    with gateway(replies) as (port, _):
        row = probe_tool.probe(port=port, timeout=2)
    assert row["tcp_connected"] and row["handshake_ok"]
    assert row["outcome"] == outcome
    assert row["error_codes"] == codes


def test_refused_port_is_reported_without_raising() -> None:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        port = connection.getsockname()[1]
        row = probe_tool.probe(port=port, timeout=0.2)
    assert row["outcome"] == "tcp_connect_failed"
    assert row["error_type"] == "ConnectionRefusedError"
    assert not row["tcp_connected"]


def test_runner_uses_host_python_without_deploying_an_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_tool("github_actions")
    monkeypatch.setenv("INVEST_SSH_HOST", "host.example")
    monkeypatch.setenv("INVEST_SSH_PRIVATE_KEY", "private-key")
    calls = []

    def run(command: list[str], label: str, **kwargs: Any) -> bytes:
        calls.append(label)
        if label == "Probe IBKR Paper API":
            assert command[-1].endswith('"$current/.venv/bin/python" -')
            assert kwargs["data"] == (ROOT / "deploy/ibkr_probe.py").read_bytes()
            return b'{"outcome":"ok","api_ready":true}\n'
        return b""

    monkeypatch.setattr(runner, "run_quiet", run)
    runner.execute("ibkr-probe", None)
    assert calls == ["Host preflight", "Probe IBKR Paper API"]
    assert "private-key" not in capsys.readouterr().out
