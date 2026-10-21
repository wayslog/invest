import io
import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from invest.notifications import send_telegram, telegram_recipient


@pytest.mark.parametrize("uid", ["-123", "0", "00123", "someone"])
def test_telegram_restricts_notifications_to_one_positive_private_uid(
    monkeypatch: pytest.MonkeyPatch, uid: str
) -> None:
    monkeypatch.setenv("TEST_TOKEN", "123456:fake-token")
    monkeypatch.setenv("TEST_UID", uid)
    with pytest.raises(ValueError, match="positive private"):
        telegram_recipient("TEST_TOKEN", "TEST_UID")


def test_notification_uses_only_configured_recipient_and_validates_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_TOKEN", "123456:fake-token")
    monkeypatch.setenv("TEST_UID", "456789")
    delivered = 456789

    class Opener:
        def open(self, request: Request, timeout: int) -> io.BytesIO:
            assert request.get_method() == "POST" and timeout == 10
            assert request.full_url == "https://api.telegram.org/bot123456:fake-token/sendMessage"
            assert isinstance(request.data, bytes)
            payload = json.loads(request.data)
            assert payload["chat_id"] == 456789
            return io.BytesIO(
                json.dumps({"ok": True, "result": {"chat": {"id": delivered}}}).encode()
            )

    monkeypatch.setattr("invest.notifications.build_opener", lambda *args: Opener())
    send_telegram("One-way failure alert", "TEST_TOKEN", "TEST_UID")
    delivered = 999
    with pytest.raises(ValueError, match="configured recipient"):
        send_telegram("Must reject wrong receipt", "TEST_TOKEN", "TEST_UID")


def test_telegram_error_does_not_expose_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_TOKEN", "123456:fake-token")
    monkeypatch.setenv("TEST_UID", "456789")

    class Opener:
        def open(self, request: Request, timeout: int) -> io.BytesIO:
            raise HTTPError(request.full_url, 401, request.full_url, {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("invest.notifications.build_opener", lambda *args: Opener())
    with pytest.raises(ValueError, match="HTTP 401") as error:
        send_telegram("Failure", "TEST_TOKEN", "TEST_UID")
    assert "fake-token" not in str(error.value) and "api.telegram.org/bot" not in str(error.value)
