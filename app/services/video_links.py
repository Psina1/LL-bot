from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode


def _signature(media_id: int, expires_at: int, secret: str) -> str:
    payload = f"{media_id}:{expires_at}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _director_signature(telegram_id: int, expires_at: int, secret: str) -> str:
    payload = f"director:{telegram_id}:{expires_at}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def build_video_watch_url(
    base_url: str,
    media_id: int,
    secret: str = "",
    ttl_hours: int = 24,
) -> str:
    clean_base_url = base_url.rstrip("/")
    if not secret:
        return f"{clean_base_url}/watch/{media_id}"

    expires_at = int(time.time()) + max(ttl_hours, 1) * 60 * 60
    query = urlencode(
        {
            "expires": expires_at,
            "token": _signature(media_id, expires_at, secret),
        }
    )
    return f"{clean_base_url}/watch/{media_id}?{query}"


def build_director_dashboard_url(
    base_url: str,
    telegram_id: int,
    secret: str = "",
    ttl_hours: int = 24,
) -> str:
    clean_base_url = base_url.rstrip("/")
    if not secret:
        query = urlencode({"telegram_id": telegram_id})
        return f"{clean_base_url}/director?{query}"

    expires_at = int(time.time()) + max(ttl_hours, 1) * 60 * 60
    query = urlencode(
        {
            "telegram_id": telegram_id,
            "expires": expires_at,
            "token": _director_signature(telegram_id, expires_at, secret),
        }
    )
    return f"{clean_base_url}/director?{query}"


def verify_video_watch_token(media_id: int, expires_raw: str | None, token: str | None, secret: str = "") -> bool:
    if not secret:
        return True
    if not expires_raw or not token:
        return False

    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False

    if expires_at < int(time.time()):
        return False

    expected = _signature(media_id, expires_at, secret)
    return hmac.compare_digest(expected, token)


def verify_director_dashboard_token(
    telegram_id: int,
    expires_raw: str | None,
    token: str | None,
    secret: str = "",
) -> bool:
    if not secret:
        return True
    if not expires_raw or not token:
        return False

    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False

    if expires_at < int(time.time()):
        return False

    expected = _director_signature(telegram_id, expires_at, secret)
    return hmac.compare_digest(expected, token)
