"""Outbound-only Telegram alerts restricted to one configured private user ID."""

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from invest.alpaca import NoRedirect


def telegram_recipient(token_env: str, uid_env: str) -> tuple[str, int]:
    token, text = os.environ.get(token_env, ""), os.environ.get(uid_env, "")
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError(f"Configure {token_env} securely")
    try:
        uid = int(text)
    except ValueError as exc:
        raise ValueError(f"Configure a positive private user ID in {uid_env}") from exc
    if uid <= 0 or str(uid) != text:
        raise ValueError(f"Configure a positive private user ID in {uid_env}")
    return token, uid


def send_telegram(text: str, token_env: str, uid_env: str) -> None:
    token, uid = telegram_recipient(token_env, uid_env)
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(
            {"chat_id": uid, "text": text[:3500], "disable_web_page_preview": True}
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            body = response.read(65537)
    except HTTPError as exc:
        # Exception URLs contain the token. Never propagate their text or body.
        raise ValueError(f"Telegram delivery failed (HTTP {exc.code})") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Telegram network/TLS delivery failed") from None
    if len(body) > 65536:
        raise ValueError("Telegram response exceeds its limit")
    try:
        result = json.loads(body)
        delivered_to = result["result"]["chat"]["id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ValueError("Invalid Telegram delivery receipt") from None
    if result.get("ok") is not True or type(delivered_to) is not int or delivered_to != uid:
        raise ValueError("Telegram receipt does not confirm the configured recipient")
