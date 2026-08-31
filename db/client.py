"""Builds and caches the Supabase client.

The import of ``supabase`` is deliberately deferred into :func:`get_client` so
that importing :mod:`db.repo` costs nothing and the test suite runs without the
package installed or any credentials present.
"""

from __future__ import annotations

import logging
from typing import Any

from common import config

log = logging.getLogger(__name__)

_client: Any | None = None


def get_client() -> Any:
    """Return the cached service-role Supabase client, building it if needed.

    Raises :class:`common.config.MissingConfig` when either variable is absent,
    which is what makes a misconfigured fetcher fail on line one instead of
    part way through a batch.
    """
    global _client
    if _client is not None:
        return _client

    values = config.require_many("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover - environment problem
        raise RuntimeError(
            "The 'supabase' package is not installed. Run "
            "'pip install -r requirements.txt'."
        ) from exc

    _client = create_client(values["SUPABASE_URL"], values["SUPABASE_SERVICE_KEY"])
    log.debug("supabase client created for %s", values["SUPABASE_URL"])
    return _client


def set_client(client: Any | None) -> None:
    """Install a client (or ``None`` to clear). Used by tests."""
    global _client
    _client = client
