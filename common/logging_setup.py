"""One logging configuration, called by every entry point."""

from __future__ import annotations

import logging
import os
import sys

_configured = False


def configure_logging(level: int | str | None = None) -> None:
    """Set up stdout logging once. ``LOG_LEVEL`` overrides the default INFO."""
    global _configured
    if _configured:
        return
    _configured = True
    resolved = level or os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=resolved,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    # These libraries are chatty at INFO and say nothing we need.
    for noisy in ("httpx", "httpcore", "hpack", "urllib3", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
