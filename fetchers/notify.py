"""Step 5: outbound notifications.

Telegram is the only channel in this slice - free, instant, and a single POST.
Email and browser push are added later, which is why the channel name is stored
alongside every message rather than assumed.

Two rules shape this module:

* **Sending never raises.** A fetcher that has already written a correct row to
  the database must not fail its run because Telegram was briefly unreachable.
  :func:`send` returns True/False and the caller carries on.
* **Every attempt is logged to the database, delivered or not.** A silent
  notification failure is the kind of thing that goes unnoticed for weeks, so
  ``notifications_log.ok`` records the outcome and makes it queryable.
"""

from __future__ import annotations

import logging

from common import config
from common.config import MissingConfig
from db import repo
from fetchers import http

log = logging.getLogger("fetchers.notify")

CHANNEL = "telegram"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Telegram rejects anything longer; truncate rather than lose the message.
MAX_MESSAGE_CHARS = 4096


def _log_attempt(message: str, *, event_id: str | None, ok: bool) -> None:
    """Record the attempt. A logging failure must not mask the send result."""
    try:
        repo.insert_notification(CHANNEL, message, event_id=event_id, ok=ok)
    except Exception as exc:
        log.error("could not write notifications_log row: %s", exc)


def send(message: str, *, event_id: str | None = None) -> bool:
    """Send one message to the configured Telegram chat. Never raises.

    Returns True only when Telegram confirmed the send. Missing credentials are
    a warning rather than an error: a fetcher run with no bot configured should
    still do its real work and record what it would have sent.
    """
    text = message.strip()
    if not text:
        return False
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[: MAX_MESSAGE_CHARS - 3] + "..."

    try:
        token = config.require("TELEGRAM_BOT_TOKEN")
        chat_id = config.require("TELEGRAM_CHAT_ID")
    except MissingConfig as exc:
        log.warning("not sending, Telegram is not configured: %s", str(exc).splitlines()[0])
        _log_attempt(text, event_id=event_id, ok=False)
        return False

    payload = {
        "chat_id": chat_id,
        "text": text,
        # The messages carry titles with characters Markdown would choke on.
        "parse_mode": None,
        "disable_web_page_preview": True,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        response = http.post_json(
            TELEGRAM_API.format(token=token), payload, timeout=15.0
        )
    except Exception as exc:  # defence in depth; post_json already swallows
        log.error("telegram send raised: %s", exc)
        _log_attempt(text, event_id=event_id, ok=False)
        return False

    ok = bool(response and response.get("ok"))
    if ok:
        log.info("sent: %s", text)
    else:
        log.error("telegram refused the message: %s", response)

    _log_attempt(text, event_id=event_id, ok=ok)
    return ok


def send_many(messages: list[str]) -> int:
    """Send several messages, returning how many were delivered."""
    return sum(1 for m in messages if send(m))


def main() -> None:
    """``python -m fetchers.notify "text"`` - a one-line delivery test."""
    import argparse

    from common.logging_setup import configure_logging

    parser = argparse.ArgumentParser(description="Send one Telegram test message.")
    parser.add_argument(
        "message",
        nargs="?",
        default="Test message from the gold news platform.",
        help="the text to send",
    )
    args = parser.parse_args()

    configure_logging()
    ok = send(args.message)
    log.info("delivered" if ok else "not delivered - see the errors above")


if __name__ == "__main__":
    main()
