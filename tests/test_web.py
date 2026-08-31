"""The two pages, the JSON feed and the detail panel.

Served through Starlette's TestClient with db.repo faked out, so the routes are
exercised end to end without Supabase or a running server.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from common.config import MissingConfig
from common.timeutil import now_utc
from web import app as web_app


@pytest.fixture
def client():
    return TestClient(web_app.app)


def make_event(offset_minutes, *, title="CPI m/m", weight=5, **extra):
    ts = now_utc() + timedelta(minutes=offset_minutes)
    row = {
        "id": f"USD|{title}|{ts.date().isoformat()}",
        "title": title,
        "country": "USD",
        "ts_utc": ts,
        "impact": "High",
        "weight": weight,
        "forecast": 0.3,
        "previous": 0.2,
        "actual": None,
        "surprise": None,
        "regime": "holding",
        "source": "forexfactory",
    }
    row.update(extra)
    return row


@pytest.fixture
def stocked(monkeypatch):
    """A repo with one upcoming and one completed release."""
    upcoming = make_event(60 * 30, title="CPI m/m", weight=5)
    past = make_event(
        -60 * 24, title="Non-Farm Employment Change", weight=4,
        forecast=165_000.0, actual=142_000.0, surprise=-1.4,
    )

    monkeypatch.setattr(
        web_app.repo, "fetch_events_between", lambda start, end, **kw: [upcoming]
    )
    monkeypatch.setattr(
        web_app.repo, "fetch_recent_releases", lambda before, **kw: [past]
    )
    monkeypatch.setattr(
        web_app.repo, "fetch_event",
        lambda event_id, **kw: past if event_id == past["id"] else None,
    )
    monkeypatch.setattr(web_app.repo, "fetch_event_weights", lambda **kw: {"cpi m/m": 5})
    return {"upcoming": upcoming, "past": past}


@pytest.fixture
def unconfigured(monkeypatch):
    """A repo that raises the way it does with no credentials."""

    def missing(*args, **kwargs):
        raise MissingConfig("Environment variable SUPABASE_URL is not set.")

    for name in (
        "fetch_events_between", "fetch_recent_releases", "fetch_event",
        "fetch_event_weights",
    ):
        monkeypatch.setattr(web_app.repo, name, missing)


class TestTodayPage:
    def test_it_renders(self, client, stocked):
        response = client.get("/")
        assert response.status_code == 200
        assert "Next 7 days" in response.text

    def test_it_lists_the_upcoming_release(self, client, stocked):
        assert "CPI m/m" in client.get("/").text

    def test_it_lists_the_recent_release(self, client, stocked):
        body = client.get("/").text
        assert "Non-Farm Employment Change" in body
        assert "142K" in body, "the actual should be rendered"

    def test_the_surprise_is_shown_with_its_label(self, client, stocked):
        assert "-1.4 (below forecast)" in client.get("/").text

    def test_weight_badges_carry_the_colour_class(self, client, stocked):
        assert 'class="badge w5"' in client.get("/").text

    def test_it_emits_utc_and_no_local_time(self, client, stocked):
        """Every timestamp must leave as data-utc for the browser to convert."""
        body = client.get("/").text
        stamps = re.findall(r'data-utc="([^"]+)"', body)
        assert stamps, "no data-utc attributes rendered"
        for stamp in stamps:
            assert stamp.endswith("+00:00"), stamp

    def test_time_elements_are_left_empty_for_the_browser(self, client, stocked):
        assert re.search(r'<time data-utc="[^"]+"></time>', client.get("/").text)

    def test_it_polls_the_partial(self, client, stocked):
        body = client.get("/").text
        assert 'hx-get="/partials/today"' in body
        assert 'hx-trigger="every 300s"' in body, "the brief asks for 5 minutes"

    def test_it_loads_the_timezone_script(self, client, stocked):
        assert "/static/js/tz.js" in client.get("/").text

    def test_empty_database_gives_a_hint_not_an_error(self, client, monkeypatch):
        monkeypatch.setattr(web_app.repo, "fetch_events_between", lambda *a, **k: [])
        monkeypatch.setattr(web_app.repo, "fetch_recent_releases", lambda *a, **k: [])
        response = client.get("/")
        assert response.status_code == 200
        assert "fetchers.ff_sync" in response.text


class TestBlackoutBanner:
    def test_it_warns_before_a_high_weight_release(self, client, monkeypatch):
        soon = make_event(20, weight=5)
        monkeypatch.setattr(web_app.repo, "fetch_events_between", lambda *a, **k: [soon])
        monkeypatch.setattr(web_app.repo, "fetch_recent_releases", lambda *a, **k: [])
        body = client.get("/").text
        assert "Blackout now" in body

    def test_it_counts_down_to_the_next_one(self, client, monkeypatch):
        later = make_event(180, weight=5)
        monkeypatch.setattr(web_app.repo, "fetch_events_between", lambda *a, **k: [later])
        monkeypatch.setattr(web_app.repo, "fetch_recent_releases", lambda *a, **k: [])
        assert "Next blackout" in client.get("/").text

    def test_a_low_weight_release_raises_no_banner(self, client, monkeypatch):
        quiet = make_event(20, weight=2, title="Unemployment Claims")
        monkeypatch.setattr(web_app.repo, "fetch_events_between", lambda *a, **k: [quiet])
        monkeypatch.setattr(web_app.repo, "fetch_recent_releases", lambda *a, **k: [])
        body = client.get("/").text
        assert "Blackout" not in body


class TestPartial:
    def test_it_returns_a_fragment_not_a_page(self, client, stocked):
        response = client.get("/partials/today")
        assert response.status_code == 200
        assert "<html" not in response.text.lower()
        assert "CPI m/m" in response.text


class TestCalendarPage:
    def test_it_renders(self, client, stocked):
        response = client.get("/calendar")
        assert response.status_code == 200
        assert 'id="calendar"' in response.text

    def test_it_loads_fullcalendar(self, client, stocked):
        assert "fullcalendar" in client.get("/calendar").text.lower()

    def test_it_renders_in_utc(self, client, stocked):
        """Rendering in UTC keeps the grid aligned with the event ids."""
        assert "timeZone: 'UTC'" in client.get("/calendar").text

    def test_it_has_the_weight_legend(self, client, stocked):
        body = client.get("/calendar").text
        assert "weight 5" in body and "weight 4" in body

    def test_it_has_a_panel_for_the_detail(self, client, stocked):
        assert 'id="event-panel"' in client.get("/calendar").text


class TestApiEvents:
    def test_it_returns_calendar_events(self, client, stocked):
        response = client.get("/api/events", params={"start": "2026-09-01", "end": "2026-09-30"})
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload, list)
        assert payload[0]["title"] == "CPI m/m"
        assert payload[0]["backgroundColor"] == "#c0392b"

    def test_starts_are_utc(self, client, stocked):
        payload = client.get(
            "/api/events", params={"start": "2026-09-01", "end": "2026-09-30"}
        ).json()
        assert payload[0]["start"].endswith("+00:00")

    def test_it_accepts_full_timestamps(self, client, stocked):
        response = client.get(
            "/api/events",
            params={"start": "2026-09-01T00:00:00Z", "end": "2026-09-30T00:00:00Z"},
        )
        assert response.status_code == 200

    def test_missing_parameters_are_rejected(self, client, stocked):
        assert client.get("/api/events").status_code == 422

    def test_junk_parameters_are_rejected(self, client, stocked):
        response = client.get("/api/events", params={"start": "banana", "end": "2026-09-30"})
        assert response.status_code == 422

    def test_a_reversed_range_is_rejected(self, client, stocked):
        response = client.get(
            "/api/events", params={"start": "2026-09-30", "end": "2026-09-01"}
        )
        assert response.status_code == 422

    def test_an_absurd_range_is_rejected(self, client, stocked):
        response = client.get(
            "/api/events", params={"start": "2000-01-01", "end": "2026-09-01"}
        )
        assert response.status_code == 422

    def test_an_unconfigured_database_still_answers_200(self, client, unconfigured):
        """A non-2xx would make FullCalendar show nothing at all."""
        response = client.get(
            "/api/events", params={"start": "2026-09-01", "end": "2026-09-30"}
        )
        assert response.status_code == 200
        assert response.json()["events"] == []
        assert "Supabase is not configured" in response.json()["warning"]


class TestEventDetail:
    def test_it_renders_the_stored_figures(self, client, stocked):
        response = client.get(f"/events/{stocked['past']['id']}")
        assert response.status_code == 200
        body = response.text
        assert "Non-Farm Employment Change" in body
        assert "165K" in body and "142K" in body
        assert "holding" in body

    def test_it_has_the_stage_three_placeholder(self, client, stocked):
        """The brief asks for an empty "Historical reaction" section."""
        body = client.get(f"/events/{stocked['past']['id']}").text
        assert "Historical reaction" in body
        assert "Not available yet" in body

    def test_an_id_with_a_pipe_survives_the_url(self, client, stocked):
        """Event ids are USD|<title>|<date>; the pipe must round-trip."""
        assert "|" in stocked["past"]["id"]
        assert client.get(f"/events/{stocked['past']['id']}").status_code == 200

    def test_an_unknown_id_gives_404(self, client, stocked):
        assert client.get("/events/USD|Nope|2026-01-01").status_code == 404

    def test_it_returns_a_fragment(self, client, stocked):
        body = client.get(f"/events/{stocked['past']['id']}").text
        assert "<html" not in body.lower()


class TestDegradation:
    def test_the_today_page_survives_missing_credentials(self, client, unconfigured):
        response = client.get("/")
        assert response.status_code == 200
        assert "Supabase is not configured" in response.text

    def test_the_calendar_page_survives(self, client, unconfigured):
        assert client.get("/calendar").status_code == 200

    def test_an_unexpected_database_error_does_not_leak_details(self, client, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("relation \"events\" does not exist")

        monkeypatch.setattr(web_app.repo, "fetch_events_between", explode)
        monkeypatch.setattr(web_app.repo, "fetch_recent_releases", explode)
        response = client.get("/")
        assert response.status_code == 200
        assert "Could not reach the database" in response.text
        assert "does not exist" not in response.text


class TestHealth:
    def test_ok_when_the_database_answers(self, client, stocked):
        assert client.get("/health").json() == {"status": "ok", "database": "ok"}

    def test_reports_an_unavailable_database(self, client, unconfigured):
        assert client.get("/health").json()["database"] == "unavailable"


class TestStatic:
    def test_the_stylesheet_is_served(self, client):
        response = client.get("/static/css/app.css")
        assert response.status_code == 200
        assert "--w5" in response.text

    def test_the_timezone_script_is_served(self, client):
        response = client.get("/static/js/tz.js")
        assert response.status_code == 200
        assert "data-utc" in response.text
