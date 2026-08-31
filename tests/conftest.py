"""Shared test helpers.

No test in this suite is allowed to touch the network. Anything that would
normally call out is either a pure function given fixture data, or is handed a
fake through monkeypatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_json_fixture(name: str):
    return json.loads(load_fixture(name))


@pytest.fixture(scope="session")
def ff_thisweek() -> list[dict]:
    """The captured ForexFactory weekly feed."""
    return load_json_fixture("ff_calendar_thisweek.json")


@pytest.fixture(scope="session")
def fomc_html() -> str:
    """The captured Federal Reserve FOMC calendar page."""
    return load_fixture("fomc_calendar.html")


@pytest.fixture
def weights() -> dict[str, int]:
    """A stand-in for event_weights, keyed the way db.repo returns it."""
    return {
        "fomc statement": 5,
        "federal funds rate": 5,
        "cpi m/m": 5,
        "core pce price index m/m": 5,
        "non-farm employment change": 4,
        "unemployment rate": 3,
        "average hourly earnings m/m": 3,
        "fed chair speaks": 4,
        "fed chair testifies": 4,
        "ism manufacturing pmi": 3,
        "retail sales m/m": 3,
        "unemployment claims": 1,
    }


# Loopback is left open: Starlette's TestClient runs the app through an
# in-process portal whose event loop builds a self-pipe over 127.0.0.1, and
# asyncio would fail to start without it. Nothing outside the machine is
# reachable, which is what the rule is actually about.
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _is_loopback(address) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
    elif isinstance(address, str):
        host = address
    else:
        return False
    return host in LOOPBACK_HOSTS


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a test tries to reach anything off this machine."""
    import socket

    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def guarded_connect(self, address, *args, **kwargs):
        if _is_loopback(address):
            return real_connect(self, address, *args, **kwargs)
        raise AssertionError(
            f"a test tried to reach {address!r}; give it a fixture or a fake instead"
        )

    def guarded_create_connection(address, *args, **kwargs):
        if _is_loopback(address):
            return real_create_connection(address, *args, **kwargs)
        raise AssertionError(
            f"a test tried to reach {address!r}; give it a fixture or a fake instead"
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


@pytest.fixture(autouse=True)
def _telegram_off(monkeypatch):
    """Default every test to "no bot configured", whatever the developer's .env says.

    The suite must not change behaviour depending on whether the machine running
    it happens to have credentials. Tests that need delivery turn it on with the
    ``telegram_on`` fixture.
    """
    from fetchers import notify

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(notify, "_disabled_warned", False)


@pytest.fixture
def telegram_on(monkeypatch):
    """Configure a bot, so send() and the fetchers attempt delivery."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
