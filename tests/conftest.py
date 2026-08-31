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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a test ever tries to open a socket."""
    import socket

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "a test tried to use the network; give it a fixture or a fake instead"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
