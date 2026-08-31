"""FastAPI app: "Today / This week" and the month calendar.

Read-only. Nothing here writes to Supabase and nothing here schedules work - the
fetchers run in GitHub Actions, because the eventual Render free tier sleeps
after fifteen minutes of inactivity.

Every route that reads the database goes through :func:`_safe`, which turns a
missing credential or an unreachable Supabase into an empty page carrying an
explanatory banner rather than a 500. That is deliberate: the owner can start the
server and see the interface before the database exists, and a transient
database fault degrades to "no data" rather than a stack trace.

Run: ``uvicorn web.app:app --reload``
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from common.config import MissingConfig
from common.logging_setup import configure_logging
from common.timeutil import now_utc
from db import repo
from fetchers.blackout import active_window, next_window
from web import presenters

configure_logging()
log = logging.getLogger("web.app")

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Gold/USD news", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# How far ahead the "this week" page looks, and how many past releases it shows.
UPCOMING_DAYS = 7
RECENT_LIMIT = 10

# The calendar refuses absurd ranges rather than trying to serve them.
MAX_RANGE_DAYS = 400


def _safe(operation: Callable[[], Any], default: Any) -> tuple[Any, str | None]:
    """Run a database read, returning ``(value, warning)``.

    A missing credential is reported as a specific, actionable message; anything
    else is logged with its traceback and reported generically, because the
    detail of a Postgres error does not belong on a public page.
    """
    try:
        return operation(), None
    except MissingConfig as exc:
        log.warning("database not configured: %s", str(exc).splitlines()[0])
        return default, (
            "Supabase is not configured yet. Copy .env.example to .env and fill in "
            "SUPABASE_URL and SUPABASE_SERVICE_KEY, then reload."
        )
    except Exception as exc:
        log.exception("database read failed: %s", exc)
        return default, "Could not reach the database. The data below may be incomplete."


def _today_context() -> dict:
    """Everything both the full page and the HTMX partial need."""
    now = now_utc()

    upcoming_rows, warning = _safe(
        lambda: repo.fetch_events_between(now, now + timedelta(days=UPCOMING_DAYS)), []
    )
    recent_rows, recent_warning = _safe(
        lambda: repo.fetch_recent_releases(now, limit=RECENT_LIMIT), []
    )

    window = active_window(now, upcoming_rows) or next_window(now, upcoming_rows)
    blackout = presenters.blackout_view(window, now) if window else None

    return {
        "now_utc": now.isoformat(),
        "upcoming": presenters.event_views(upcoming_rows),
        "recent": presenters.event_views(recent_rows),
        "summary": presenters.summarise(upcoming_rows),
        "blackout": blackout,
        "upcoming_days": UPCOMING_DAYS,
        "warning": warning or recent_warning,
    }


@app.get("/", response_class=HTMLResponse)
def today(request: Request):
    """Upcoming releases for the next week, and the last ten results."""
    return templates.TemplateResponse(request, "today.html", _today_context())


@app.get("/partials/today", response_class=HTMLResponse)
def today_partial(request: Request):
    """The refreshing part of the page. HTMX polls this every five minutes."""
    return templates.TemplateResponse(
        request, "partials/today_tables.html", _today_context()
    )


@app.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request):
    """Month view. FullCalendar fetches the events themselves from /api/events."""
    return templates.TemplateResponse(
        request, "calendar.html", {"now_utc": now_utc().isoformat()}
    )


@app.get("/api/events")
def api_events(
    start: str = Query(..., description="ISO date or timestamp, inclusive"),
    end: str = Query(..., description="ISO date or timestamp, inclusive"),
):
    """FullCalendar's JSON feed."""
    try:
        start_dt = presenters.parse_range_param(start, field="start")
        end_dt = presenters.parse_range_param(end, field="end")
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    if end_dt < start_dt:
        return JSONResponse({"error": "end must not precede start"}, status_code=422)
    if (end_dt - start_dt).days > MAX_RANGE_DAYS:
        return JSONResponse(
            {"error": f"range must be {MAX_RANGE_DAYS} days or fewer"}, status_code=422
        )

    rows, warning = _safe(lambda: repo.fetch_events_between(start_dt, end_dt), [])
    if warning:
        # FullCalendar treats a non-2xx as a load failure and shows nothing; an
        # empty list with a note lets the page stay usable.
        return JSONResponse({"events": [], "warning": warning})
    return JSONResponse(presenters.calendar_events(rows))


@app.get("/events/{event_id:path}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: str):
    """The panel HTMX loads when a calendar event is clicked."""
    row, warning = _safe(lambda: repo.fetch_event(event_id), None)
    return templates.TemplateResponse(
        request,
        "partials/event_detail.html",
        {
            "event": presenters.event_view(row) if row else None,
            "event_id": event_id,
            "warning": warning,
        },
        status_code=200 if row or warning else 404,
    )


@app.get("/health")
def health():
    """Liveness plus whether the database is actually reachable."""
    _, warning = _safe(lambda: repo.fetch_event_weights(), {})
    return {"status": "ok", "database": "unavailable" if warning else "ok"}
