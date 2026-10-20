"""Read-only Alpaca market data; exact response bodies are retained in Parquet."""

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

import pyarrow as pa

from invest.market import BAR_SCHEMA, MONEY, validate_bars
from invest.quality import parse_as_of

NEW_YORK = ZoneInfo("America/New_York")
RequestData = Callable[[str, dict[str, str]], bytes]
RAW_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("endpoint", pa.string()),
        ("query", pa.string()),
        ("received_at", pa.timestamp("us", tz="UTC")),
        ("sha256", pa.string()),
        ("body", pa.binary()),
    ],
    metadata={b"schema_version": b"invest.raw.alpaca.v1"},
)
ACTION_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("dividend", MONEY),
        ("pay_date", pa.date32()),
        ("split_ratio", pa.int64()),
    ],
    metadata={b"schema_version": b"invest.actions.v1"},
)
AVAILABILITY_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("published_at", pa.timestamp("us", tz="UTC")),
    ],
    metadata={b"basis": b"observed_at_fetch; historical_publication_unknown"},
)


@dataclass(frozen=True)
class FetchSpec:
    symbol: str
    start: date
    end: date
    feed: str
    actions_through: date = field(default_factory=lambda: datetime.now(UTC).date())

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", self.symbol):
            raise ValueError("Use one uppercase US symbol")
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        if self.feed not in {"sip", "iex"}:
            raise ValueError("feed must explicitly be sip or iex")
        if not self.end <= self.actions_through <= datetime.now(UTC).date():
            raise ValueError("Action capture cutoff must cover end and cannot be in the future")

    def queries(self) -> list[tuple[str, str, dict[str, str]]]:
        # Alpaca timestamps represent midnight in New York; end includes the requested day.
        opening = datetime.combine(self.start, time(), NEW_YORK)
        ending = datetime.combine(self.end + timedelta(days=1), time(), NEW_YORK)
        return [
            (
                "bars",
                "/v2/stocks/bars",
                {
                    "symbols": self.symbol,
                    "timeframe": "1Day",
                    "adjustment": "raw",
                    "feed": self.feed,
                    "start": opening.isoformat(),
                    "end": (ending - timedelta(microseconds=1)).isoformat(),
                    "asof": self.end.isoformat(),
                    "sort": "asc",
                    "limit": "10000",
                },
            ),
            (
                "actions",
                "/v1/corporate-actions",
                {
                    "symbols": self.symbol,
                    # This endpoint filters on process_date, not ex_date. Capture
                    # all available processed history, then select ex-dates locally.
                    # The explicit cutoff is persisted for reproducible verification.
                    "start": "1970-01-01",
                    "end": self.actions_through.isoformat(),
                    "sort": "asc",
                    "limit": "1000",
                },
            ),
        ]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        # Never forward authentication to a redirect destination.
        return None


def authenticated_request() -> RequestData:
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise ValueError(
            "Configure APCA_API_KEY_ID and APCA_API_SECRET_KEY in secure environment settings"
        )
    opener = build_opener(NoRedirect())

    def get(endpoint: str, params: dict[str, str]) -> bytes:
        if endpoint not in {"/v2/stocks/bars", "/v1/corporate-actions"}:
            raise ValueError("Unsupported read-only market data endpoint")
        request = Request(
            "https://data.alpaca.markets" + endpoint + "?" + urlencode(params),
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=30) as response:
                body = response.read(16 * 1024 * 1024 + 1)
        except HTTPError as exc:
            raise ValueError(
                f"Alpaca HTTP {exc.code}; no feed fallback or order submitted"
            ) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError(
                "Alpaca network/TLS request failed; retry after resolving access"
            ) from None
        if len(body) > 16 * 1024 * 1024:
            raise ValueError("Alpaca response exceeds the 16 MiB page limit")
        return bytes(body)

    return get


def object_map(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object with string keys")
    return value


def decode(body: bytes) -> dict[str, Any]:
    return object_map(json.loads(body, parse_float=Decimal))


def fetch_pages(spec: FetchSpec, request: RequestData) -> Iterator[dict[str, object]]:
    for kind, endpoint, parameters in spec.queries():
        seen: set[str] = set()
        for _ in range(1000):
            body = request(endpoint, parameters.copy())
            yield {
                "kind": kind,
                "endpoint": endpoint,
                "query": json.dumps(parameters, sort_keys=True),
                "received_at": datetime.now(UTC),
                "sha256": hashlib.sha256(body).hexdigest(),
                "body": body,
            }
            page = decode(body)
            if "next_page_token" not in page:
                raise ValueError("Missing pagination marker; completeness is unknown")
            token = page["next_page_token"]
            if token is None:
                break
            if not isinstance(token, str) or not token or token in seen:
                raise ValueError("Invalid/repeated pagination token")
            seen.add(token)
            parameters["page_token"] = token
        else:
            raise ValueError("Pagination limit reached; dataset is incomplete")


def decimal_value(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Expected an exact decimal value")
    try:
        result = Decimal(value)
        if not result.is_finite() or result != result.quantize(Decimal("0.000001")):
            raise ValueError("Value must be finite with at most six decimal places")
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal value") from exc
    return result


def date_value(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("Missing/invalid corporate-action date")
    return date.fromisoformat(value)


def normalize(
    raw: pa.Table, spec: FetchSpec, dataset_id: str
) -> tuple[pa.Table, pa.Table, pa.Table]:
    try:
        return _normalize(raw, spec, dataset_id)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Provider response has a missing/invalid required field") from exc


def _normalize(
    raw: pa.Table, spec: FetchSpec, dataset_id: str
) -> tuple[pa.Table, pa.Table, pa.Table]:
    """Replay captured pages deterministically; reject unsupported or ambiguous events."""
    if not raw.schema.equals(RAW_SCHEMA, check_metadata=True) or not raw.num_rows:
        raise ValueError("Invalid/empty raw capture")
    rows: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []
    by_date: dict[date, dict[str, object]] = {}
    pages = raw.to_pylist()
    # Recheck query identity, hashes and pagination, including the final page of both endpoints.
    for kind, endpoint, initial in spec.queries():
        subset = [row for row in pages if row["kind"] == kind]
        expected = initial.copy()
        seen: set[str] = set()
        if not subset:
            raise ValueError(f"Missing {kind} capture")
        for i, captured in enumerate(subset):
            if captured["endpoint"] != endpoint or json.loads(captured["query"]) != expected:
                raise ValueError("Capture query/pagination does not match its manifest")
            if hashlib.sha256(captured["body"]).hexdigest() != captured["sha256"]:
                raise ValueError("Raw response checksum mismatch")
            page = decode(captured["body"])
            if "next_page_token" not in page:
                raise ValueError("Missing pagination marker")
            token = page["next_page_token"]
            if token is None:
                if i != len(subset) - 1:
                    raise ValueError("Unexpected page after end of pagination")
            else:
                if not isinstance(token, str) or not token or token in seen or i == len(subset) - 1:
                    raise ValueError("Incomplete/repeated pagination")
                seen.add(token)
                expected["page_token"] = token
            if kind == "bars":
                symbols = object_map(page.get("bars"))
                if set(symbols) - {spec.symbol}:
                    raise ValueError("Unexpected symbol in bar response")
                entries = symbols.get(spec.symbol, [])
                if not isinstance(entries, list):
                    raise ValueError("Invalid bars response")
                for value in entries:
                    item = object_map(value)
                    timestamp = parse_as_of(item["t"]).astimezone(NEW_YORK)
                    session = timestamp.date()
                    if timestamp.time() != time() or not spec.start <= session <= spec.end:
                        raise ValueError("Unexpected daily-bar timestamp/range")
                    if session in by_date:
                        raise ValueError("Duplicate daily bar")
                    volume = decimal_value(item["v"])
                    if volume != volume.to_integral_value():
                        raise ValueError("Non-integer volume")
                    bar: dict[str, object] = {
                        "date": session,
                        "symbol": spec.symbol,
                        **{
                            name: decimal_value(item[key])
                            for name, key in [
                                ("open", "o"),
                                ("high", "h"),
                                ("low", "l"),
                                ("close", "c"),
                            ]
                        },
                        "volume": int(volume),
                        "split_ratio": 1,
                        "dividend": Decimal(0),
                        "dividend_pay_date": None,
                    }
                    by_date[session] = bar
                    rows.append(bar)
            else:
                groups = object_map(page.get("corporate_actions"))
                for action_kind, entries in groups.items():
                    if not isinstance(entries, list):
                        raise ValueError("Invalid corporate-action response")
                    if entries and action_kind not in {"cash_dividends", "forward_splits"}:
                        raise ValueError(f"Unsupported corporate action: {action_kind}")
                    for value in entries:
                        item = object_map(value)
                        session = date_value(item.get("ex_date"))
                        if item.get("symbol") != spec.symbol:
                            raise ValueError("Corporate action lacks matching symbol/session")
                        if not spec.start <= session <= spec.end:
                            continue  # Retained in raw capture; no entitlement before inception.
                        if session not in by_date:
                            raise ValueError("Corporate action lacks matching symbol/session")
                        if any(action["date"] == session for action in actions):
                            raise ValueError(
                                "Duplicate/simultaneous corporate actions require review"
                            )
                        if any(
                            item.get(key) is not None
                            for key in [
                                "due_bill_on_date",
                                "due_bill_off_date",
                                "due_bill_redemption_date",
                            ]
                        ):
                            raise ValueError("Due-bill corporate actions are unsupported")
                        dividend, ratio, payment = Decimal(0), 1, None
                        if action_kind == "cash_dividends":
                            if item.get("special") is not False or item.get("foreign") is not False:
                                raise ValueError(
                                    "Only ordinary domestic cash dividends are supported"
                                )
                            dividend = decimal_value(item["rate"])
                            try:
                                payment = date_value(item.get("payable_date"))
                            except ValueError as exc:
                                raise ValueError(
                                    f"Dividend {spec.symbol} {session}: invalid payable_date"
                                ) from exc
                            if dividend <= 0 or payment < session:
                                raise ValueError("Invalid cash dividend or payment date")
                        else:
                            new, old = (
                                decimal_value(item["new_rate"]),
                                decimal_value(item["old_rate"]),
                            )
                            if old <= 0 or new <= old or new % old:
                                raise ValueError("Only integer forward splits are supported")
                            ratio = int(new / old)
                        by_date[session].update(
                            dividend=dividend, split_ratio=ratio, dividend_pay_date=payment
                        )
                        actions.append(
                            {
                                "kind": action_kind,
                                "date": session,
                                "symbol": spec.symbol,
                                "dividend": dividend,
                                "pay_date": payment,
                                "split_ratio": ratio,
                            }
                        )
    if set(raw["kind"].to_pylist()) != {"bars", "actions"}:
        raise ValueError("Unexpected raw capture kind")
    observed_at = max(raw["received_at"].to_pylist())
    metadata = {
        **(BAR_SCHEMA.metadata or {}),
        b"source": b"alpaca",
        b"feed": spec.feed.encode(),
        b"dataset_id": dataset_id.encode(),
        b"observed_at": observed_at.isoformat().encode(),
        b"usage": b"historical_research_only",
        b"daily_open": b"provider_bar_proxy",
    }
    bars = pa.Table.from_pylist(rows, schema=BAR_SCHEMA.with_metadata(metadata))
    validate_bars(bars, spec.symbol)
    availability = pa.Table.from_pylist(
        [{"date": row["date"], "observed_at": observed_at, "published_at": None} for row in rows],
        schema=AVAILABILITY_SCHEMA,
    )
    return bars, pa.Table.from_pylist(actions, schema=ACTION_SCHEMA), availability
