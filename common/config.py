"""Environment configuration. The only place the process environment is read.

Values come from the real environment first (that is what GitHub Actions
supplies) and fall back to a local ``.env`` loaded once via python-dotenv.
Anything missing raises :class:`MissingConfig` naming the variable, so a fetcher
fails immediately instead of running half way and writing partial rows.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Every variable the project understands, with the hint shown when it is absent.
KNOWN_VARS: dict[str, str] = {
    "SUPABASE_URL": "Supabase project URL, e.g. https://xxxx.supabase.co",
    "SUPABASE_SERVICE_KEY": "Supabase service_role key (Project Settings -> API)",
    "DATABASE_URL": "Supabase -> Connect -> Session pooler URI, password percent-encoded",
    "FRED_API_KEY": "Free key from https://fredaccount.stlouisfed.org/apikeys",
    "TELEGRAM_BOT_TOKEN": "Bot token from @BotFather",
    "TELEGRAM_CHAT_ID": "Numeric chat id to send notifications to",
    "REMINDER_LEAD_MINUTES": (
        "Reminder lead times in minutes, far tier first, e.g. 1440,60 "
        "(the default: 24 hours and 1 hour)"
    ),
}

# Supabase renamed its server-side key: the dashboard now calls it a "Secret
# key" (sb_secret_...) rather than service_role. Both names are accepted so the
# owner can paste the variable under whichever name the dashboard shows, and an
# existing .env keeps working. Canonical name first, then the alternates.
ALIASES: dict[str, tuple[str, ...]] = {
    "SUPABASE_SERVICE_KEY": ("SUPABASE_SECRET_KEY",),
}

_dotenv_loaded = False


class MissingConfig(RuntimeError):
    """Raised when a required environment variable is absent or blank."""


def _load_dotenv_once() -> None:
    """Load ``.env`` from the repo root, once per process. Never overrides."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv is optional in CI, where real env vars are set
        log.debug("python-dotenv not installed; relying on the real environment")
        return
    load_dotenv(env_path, override=False)
    log.debug("loaded %s", env_path)


def get(name: str, default: str | None = None) -> str | None:
    """Return a variable, or ``default``. Blank strings count as absent.

    Falls back to any alias registered for the name, so a value stored under
    Supabase's own label is found without the owner having to re-paste a secret.
    """
    _load_dotenv_once()
    for candidate in (name, *ALIASES.get(name, ())):
        value = os.environ.get(candidate)
        if value is not None and value.strip():
            return value.strip()
    return default


def require(name: str) -> str:
    """Return a variable or raise :class:`MissingConfig` explaining the fix."""
    value = get(name)
    if value is None:
        hint = KNOWN_VARS.get(name, "")
        raise MissingConfig(
            f"Environment variable {name} is not set. {hint}\n"
            f"Add it to .env (see .env.example) or, in CI, to the repository secrets."
        )
    return value


def require_many(*names: str) -> dict[str, str]:
    """Return several variables, reporting *all* missing ones in one message."""
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        value = get(name)
        if value is None:
            missing.append(name)
        else:
            values[name] = value
    if missing:
        lines = [f"  {n} - {KNOWN_VARS.get(n, '')}".rstrip(" -") for n in missing]
        raise MissingConfig(
            "Missing required environment variables:\n"
            + "\n".join(lines)
            + "\nAdd them to .env (see .env.example) or to the repository secrets."
        )
    return values


def has(*names: str) -> bool:
    """True when every named variable is present. Used to skip optional work."""
    return all(get(n) is not None for n in names)
