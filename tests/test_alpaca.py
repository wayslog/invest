from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest

from invest.alpaca import FetchSpec, NoRedirect, authenticated_request, decimal_value
from invest.quality import latest_completed_session


def test_http_failure_has_no_credentials_or_response_body_and_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "fixture-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fixture-secret")
    requests: list[str] = []

    class FailingOpener:
        def open(self, request: Any, timeout: int) -> Any:
            requests.append(request.full_url)
            assert request.get_method() == "GET"
            assert request.get_header("Apca-api-key-id") == "fixture-key"
            assert request.get_header("Apca-api-secret-key") == "fixture-secret"
            assert timeout == 30
            raise HTTPError(
                request.full_url,
                403,
                "fixture-secret",
                {},  # type: ignore[arg-type]
                BytesIO(b"fixture-key fixture-secret"),
            )

    monkeypatch.setattr("invest.alpaca.build_opener", lambda *args: FailingOpener())
    request = authenticated_request()
    with pytest.raises(ValueError, match="HTTP 403") as error:
        request("/v2/stocks/bars", {"feed": "sip"})
    assert str(error.value) == "Alpaca HTTP 403; no feed fallback or order submitted"
    assert requests == ["https://data.alpaca.markets/v2/stocks/bars?feed=sip"]
    with pytest.raises(ValueError, match="Unsupported read-only"):
        request("/v2/orders", {})


def test_authentication_is_not_followed_through_redirects() -> None:
    assert NoRedirect().redirect_request(None, None, 302, "", None, "https://other.test") is None


@pytest.mark.parametrize("value", ["NaN", "Infinity", "0.1234567", True, "invalid", 0.1])
def test_prices_cannot_silently_round_or_accept_inexact_floats(value: object) -> None:
    with pytest.raises(ValueError):
        decimal_value(value)
    assert decimal_value(".123456") == Decimal(".123456")


def test_feed_and_range_must_be_explicit() -> None:
    with pytest.raises(ValueError, match="feed"):
        FetchSpec("SPY", date(2024, 1, 2), date(2024, 1, 3), "default")
    with pytest.raises(ValueError, match="start"):
        FetchSpec("SPY", date(2024, 1, 3), date(2024, 1, 2), "sip")


def test_freshness_cutoff_respects_half_day_and_weekend() -> None:
    assert latest_completed_session(datetime(2024, 11, 29, 17, 59, tzinfo=UTC)) == date(
        2024, 11, 27
    )
    assert latest_completed_session(datetime(2024, 11, 29, 18, tzinfo=UTC)) == date(2024, 11, 29)
    assert latest_completed_session(datetime(2024, 12, 1, tzinfo=UTC)) == date(2024, 11, 29)
