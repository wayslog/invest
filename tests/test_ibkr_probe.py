"""Socket negotiation, SDK readiness and private host-local probe receipts."""

import logging
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow.parquet as pq
import pytest

from tests.test_deployment import ROOT, load_tool

probe_tool = load_tool("ibkr_probe")


@contextmanager
def gateway(reply: bytes) -> Iterator[tuple[int, list[bytes]]]:
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
                    message = probe_tool.frame(reply)
                    connection.sendall(message[:2])
                    connection.sendall(message[2:])
                    assert connection.recv(1) == b""
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


@pytest.mark.parametrize("version", [100, 178])
def test_wire_handshake_is_not_account_session_readiness(version: int) -> None:
    with gateway(f"{version}\0server-time\0".encode()) as (port, sent):
        row = probe_tool.probe(port=port, timeout=2)
    assert row["tcp_connected"] and not row["api_ready"]
    assert row["handshake_ok"] == (version == 178)
    assert sent == [b"v157..178"]


@pytest.mark.parametrize(
    ("accounts", "ready", "outcome"),
    [
        (["DU1234567"], True, "ok"),
        (["U1234567"], True, "unexpected_account_type"),
        ([], False, "sdk_session_not_ready"),
    ],
)
def test_sdk_session_requires_readiness_and_paper_account_with_private_receipt(
    tmp_path: Path, accounts: list[str], ready: bool, outcome: str
) -> None:
    calls: list[str] = []

    class Client:
        def connect(self, host: str, port: int, *, clientId: int, timeout: int) -> None:
            assert host == "127.0.0.1" and clientId == 71 and timeout == 10
            calls.append("connect")
            logging.getLogger("ib_async.client").debug("Private accounts: %s", accounts)

        def isReady(self) -> bool:
            return ready

        def getAccounts(self) -> list[str]:
            return accounts

        def serverVersion(self) -> int:
            return 178

    class IB:
        client = Client()

        def disconnect(self) -> None:
            calls.append("disconnect")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        row = probe_tool.sdk_probe(port=listener.getsockname()[1], sdk=SimpleNamespace(IB=IB))
    assert row["outcome"] == outcome
    assert calls == ["connect", "disconnect"]
    receipt = probe_tool.save_receipt(row, tmp_path / "private")
    restored = pq.read_table(receipt).to_pylist()[0]
    assert restored["managed_accounts"] == accounts
    assert restored["messages"] == row["messages"]
    assert pq.ParquetFile(receipt).metadata.row_group(0).column(0).compression == "ZSTD"
    assert receipt.stat().st_mode & 0o777 == 0o600
    for account in accounts:
        assert account not in str(probe_tool.public_summary(row, receipt))


@pytest.mark.parametrize("error", [ConnectionRefusedError, TimeoutError])
def test_failed_port_is_reported_without_raising(
    monkeypatch: pytest.MonkeyPatch, error: type[OSError]
) -> None:
    def fail_connect(*args: Any, **kwargs: Any) -> None:
        raise error("Synthetic connection failure")

    # 绑定但未监听的端口在不同系统上可能拒绝或超时，分别验证错误处理。
    monkeypatch.setattr(probe_tool.socket, "create_connection", fail_connect)
    row = probe_tool.probe(port=12345, timeout=0.2)
    assert row["outcome"] == "tcp_connect_failed"
    assert row["error_type"] == error.__name__
    assert not row["tcp_connected"]


def test_runner_uses_isolated_sdk_without_deploying_an_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_tool("github_actions")
    monkeypatch.setenv("INVEST_SSH_HOST", "host.example")
    monkeypatch.setenv("INVEST_SSH_PRIVATE_KEY", "private-key")
    calls = []

    def run(command: list[str], label: str, **kwargs: Any) -> bytes:
        calls.append(label)
        if label == "Probe IBKR Paper API":
            assert "uv run --no-project --python 3.12" in command[-1]
            assert "ib_async==2.1.0" in command[-1]
            assert kwargs["data"] == (ROOT / "deploy/ibkr_probe.py").read_bytes()
            return b'{"outcome":"ok","api_ready":true}\n'
        return b""

    monkeypatch.setattr(runner, "run_quiet", run)
    runner.execute("ibkr-probe", None)
    assert calls == ["Host preflight", "Probe IBKR Paper API"]
    assert "private-key" not in capsys.readouterr().out
