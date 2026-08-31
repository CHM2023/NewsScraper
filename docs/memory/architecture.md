# Architecture

## Data flow

```
FRED releases/dates ─┐
federalreserve.gov  ─┼─> fetchers/calendar_skeleton.py ─┐
                     │                                   │
nfs.faireconomy.media┼─> fetchers/ff_sync.py ────────────┤
                     │        │                          │
FRED observations   ─┼─> fetchers/fred_actuals.py ───────┼─> db/repo.py ─> Supabase
                     │                                   │       ^
FRED + yfinance     ─┴─> fetchers/prices_daily.py ───────┘       │
                              │                                  │
                     fetchers/reminders.py ──> fetchers/notify.py ──> Telegram
                                                                  │
                                            web/app.py (FastAPI) ─┘
                                                  │
                                    Jinja2 + HTMX + FullCalendar (CDN)
```

Scheduling is GitHub Actions cron only — nothing schedules itself inside the web
app, because the eventual Render free tier sleeps after 15 minutes idle. The web
app only reads.

## Folder layout

| Path | Responsibility |
|---|---|
| `common/config.py` | Env-var access. Fail fast, name the missing variable. |
| `common/timeutil.py` | UTC helpers. Raises on naive datetimes. |
| `common/logging_setup.py` | One `configure_logging()` used by every entry point. |
| `common/stats.py` | Per-run fetched/inserted/updated/skipped counters. |
| `db/client.py` | Builds and caches the Supabase client. Lazy import. |
| `db/repo.py` | Every query in the project. The only module that touches the client. |
| `fetchers/http.py` | Every outbound HTTP call. Timeout, retries, `allow_404`. |
| `fetchers/fred.py` | Shared FRED observation client. |
| `fetchers/parsing.py` | Pure: `"250K"` -> `250000.0`, forecast/previous strings. |
| `fetchers/titles.py` | Pure: canonical event titles + weight lookup. |
| `fetchers/diff.py` | Pure: incoming vs stored -> NEW / CHANGED / unchanged. |
| `fetchers/surprise.py` | Pure: `(actual-forecast)/abs(forecast)*10`, clamped. |
| `fetchers/regime.py` | Pure: 90-day Fed funds direction -> hiking/holding/cutting. |
| `fetchers/blackout.py` | Pure: high-weight event windows to stay out of. |
| `fetchers/release_times.py` | Pure: standing ET release times -> UTC, via the real IANA zone. |
| `fetchers/series_map.py` | Title -> FRED series id + transform, for actuals. |
| `fetchers/fomc.py` | FOMC calendar parsing + a verified fallback date table. |
| `fetchers/calendar_skeleton.py` | Step 3: 12 months of release dates. |
| `fetchers/ff_sync.py` | Step 4: weekly forecasts, diff, notify. One week, see below. |
| `fetchers/notify.py` | Step 5: `send(message)` -> Telegram + notifications_log. |
| `fetchers/reminders.py` | Step 5: 24h / 60min reminders for weight >= 4. |
| `fetchers/fred_actuals.py` | Step 6: fill `actual`, compute `surprise`. |
| `fetchers/prices_daily.py` | Step 7: daily prices, backfill, `events.regime`. |
| `web/app.py` | FastAPI routes. Read-only; every read degrades, never 500s. |
| `web/presenters.py` | Pure: rows -> view models. Colours, formatting, no local time. |
| `web/templates/` | Jinja2. Emits `data-utc`; never formats local time. |
| `web/static/js/tz.js` | The only place UTC becomes local time. |
| `web/static/css/app.css` | Hand-written; no framework in this slice. |
| `sql/001_init.sql` | Schema + `event_weights` seed. Run by hand in Supabase. |
| `tests/fixtures/` | Captured API responses. Tests never hit the network. |

The split between pure modules and I/O modules is deliberate: everything with
interesting logic (parsing, diff, surprise, regime, blackout) is a pure function
tested against fixtures, and the fetchers are thin wiring around them.

## Web routes

| Route | Purpose |
|---|---|
| `GET /` | Today / this week. Next 7 days plus the last 10 releases. |
| `GET /partials/today` | The same tables alone; HTMX polls this every 300s. |
| `GET /calendar` | FullCalendar month view. |
| `GET /api/events?start=&end=` | JSON feed for FullCalendar. Max 400 days. |
| `GET /events/{id}` | HTMX detail panel, including the Stage 3 slot. |
| `GET /health` | Liveness plus whether Supabase is reachable. |

## Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `SUPABASE_URL` | `db/client.py` | Project URL. |
| `SUPABASE_SERVICE_KEY` | `db/client.py` | service_role key; bypasses RLS, server only. |
| `FRED_API_KEY` | `calendar_skeleton`, `fred_actuals`, `prices_daily` | Free. |
| `TELEGRAM_BOT_TOKEN` | `notify` | From @BotFather. |
| `TELEGRAM_CHAT_ID` | `notify` | Numeric chat id. |

`common/config.py` reads `.env` via `python-dotenv` when present, then the real
environment (which is what GitHub Actions supplies). Missing variables raise
`MissingConfig` naming the variable — fetchers fail fast rather than half-running.

## Workarounds and source deviations
Recorded here as they are discovered; the reasoning lives in `decisions.md`.

## Scheduled workflows

| Workflow | Cron (UTC) | Runs | Secrets |
|---|---|---|---|
| `calendar-sync.yml` | `0 * * * *` (hourly) | `fetchers.ff_sync` | Supabase + Telegram |
| `reminders.yml` | `*/15 * * * *` | `fetchers.reminders` | Supabase + Telegram |
| `daily.yml` | `0 7 * * *` | `calendar_skeleton`, `fred_actuals`, `prices_daily` | Supabase + FRED |
| `tests.yml` | on push / PR | `pytest -q` | none |

All three scheduled workflows set `concurrency` so runs cannot overlap: two
`ff_sync` runs racing would diff against the same pre-write state and send the
same NEW message twice. `daily.yml` runs at 07:00 UTC - after the US close and
before the 08:30 ET releases - and its steps are ordered so the skeleton creates
rows before actuals fill them and before `prices_daily` re-tags regimes.
`daily.yml` also accepts a `backfill_years` input for the one-off history load.

**Repository secrets to add** (Settings -> Secrets and variables -> Actions):
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FRED_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`. `tests/test_workflows.py` fails if a workflow ever references
a secret outside this set, or runs a fetcher module that does not exist.

## Workarounds and source deviations

Verified against the live sources on 2026-08-31. Reasoning is in `decisions.md`.

| Source | Reality | What we do |
|---|---|---|
| `ff_calendar_thisweek.json` | 200, ~112 entries, ~27 USD rows | Required feed. |
| `ff_calendar_nextweek.json` | **404** (as are lastweek/today/tomorrow) | Optional feed, `allow_404`. Forecasts therefore exist for about one week only, and `calendar_skeleton` supplies every date beyond that. |
| FOMC dates | No FRED release covers them | Regex the Fed calendar page; a table transcribed on 2026-08-31 is the fallback. All 16 fallback dates for 2026-27 match the live page. |
| ISM PMIs | Withdrawn from FRED over licensing | Dates and forecasts still come from ForexFactory; `actual` stays null, and `series_map` records why. |
| `dxy` column | ICE DXY is not free with history | Holds FRED `DTWEXBGS`, the Fed's broad dollar index. Named `dxy` but is **not** ICE DXY. |
| LBMA gold on FRED | Discontinued once already | Used when current; falls back to yfinance `GC=F` when stale or absent. |
| Windows + `zoneinfo` | No IANA database on Windows | `tzdata` is pinned in requirements. |

Console and log strings are kept ASCII-only: the Windows console is cp1252 and
turns an em dash into `?`.
