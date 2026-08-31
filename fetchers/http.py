"""One place where outbound HTTP happens, so every call gets the same treatment.

The brief's rule is that every external call is wrapped with a timeout and that
one bad response never stops a batch. Callers get either parsed data or None -
never an exception from the network layer - and decide for themselves whether a
missing source is fatal.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3
BACKOFF_SECONDS = 2.0

# Some publishers (the Federal Reserve among them) reject the bare requests UA.
USER_AGENT = "gold-news-platform/0.1 (+https://github.com/CHM2023/NewsScraper)"

# Worth retrying: transient upstream faults and rate limits.
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _sleep(attempt: int) -> None:
    time.sleep(BACKOFF_SECONDS * attempt)


def get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    headers: dict[str, str] | None = None,
    allow_404: bool = False,
) -> requests.Response | None:
    """GET with a timeout and bounded retries. Returns None if it never worked.

    ``allow_404`` marks a resource whose absence is expected rather than
    broken - a publisher that has retired an endpoint. The 404 is then logged at
    INFO and returns None quietly, instead of writing an error line on every
    scheduled run for a condition nobody is going to fix.
    """
    merged = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    merged.update(headers or {})

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout, headers=merged)
        except requests.RequestException as exc:
            log.warning("GET %s failed (attempt %d/%d): %s", url, attempt, retries, exc)
            if attempt < retries:
                _sleep(attempt)
            continue

        if response.status_code in RETRY_STATUS and attempt < retries:
            log.warning(
                "GET %s returned %d (attempt %d/%d), retrying",
                url, response.status_code, attempt, retries,
            )
            _sleep(attempt)
            continue

        if response.status_code == 404 and allow_404:
            log.info("GET %s is not published (404)", url)
            return None

        if not response.ok:
            log.error("GET %s returned %d: %.200s", url, response.status_code, response.text)
            return None

        return response

    log.error("GET %s gave up after %d attempts", url, retries)
    return None


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    headers: dict[str, str] | None = None,
    allow_404: bool = False,
) -> Any | None:
    """GET and parse JSON. Returns None on network, HTTP or decode failure."""
    merged = {"Accept": "application/json"}
    merged.update(headers or {})
    response = get(
        url, params=params, timeout=timeout, retries=retries, headers=merged,
        allow_404=allow_404,
    )
    if response is None:
        return None
    try:
        return response.json()
    except ValueError as exc:
        log.error("GET %s returned unparseable JSON: %s", url, exc)
        return None


def get_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    headers: dict[str, str] | None = None,
) -> str | None:
    """GET and return the body as text, or None."""
    response = get(url, params=params, timeout=timeout, retries=retries, headers=headers)
    return None if response is None else response.text


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    headers: dict[str, str] | None = None,
) -> Any | None:
    """POST a JSON body and parse the JSON reply. None on any failure.

    Used only for Telegram sends, which are safe to retry: the Bot API is
    idempotent enough that a duplicate on a timeout is preferable to a silently
    missed alert about a weight-5 release.
    """
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    merged.update(headers or {})

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=timeout, headers=merged)
        except requests.RequestException as exc:
            log.warning("POST %s failed (attempt %d/%d): %s", url, attempt, retries, exc)
            if attempt < retries:
                _sleep(attempt)
            continue

        if response.status_code in RETRY_STATUS and attempt < retries:
            log.warning(
                "POST %s returned %d (attempt %d/%d), retrying",
                url, response.status_code, attempt, retries,
            )
            _sleep(attempt)
            continue

        if not response.ok:
            log.error("POST %s returned %d: %.200s", url, response.status_code, response.text)
            return None

        try:
            return response.json()
        except ValueError as exc:
            log.error("POST %s returned unparseable JSON: %s", url, exc)
            return None

    log.error("POST %s gave up after %d attempts", url, retries)
    return None
