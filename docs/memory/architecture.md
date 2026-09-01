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
| `fetchers/titles.py` | Pure: canonical titles, weight lookup, and the release -> titles fan-out. |
| `fetchers/diff.py` | Pure: incoming vs stored -> NEW / CHANGED / unchanged. |
| `fetchers/surprise.py` | Pure: `(actual-forecast)/abs(forecast)*10`, clamped. |
| `fetchers/regime.py` | Pure: 90-day Fed funds direction -> hiking/holding/cutting. |
| `fetchers/blackout.py` | Pure: high-weight event windows to stay out of. |
| `fetchers/release_times.py` | Pure: standing ET release times -> UTC, via the real IANA zone. |
| `fetchers/series_map.py` | Title -> FRED series id + transform, for actuals. |
| `fetchers/fomc.py` | FOMC calendar parsing (incl. the SEP asterisk) + a verified fallback date table. |
| `fetchers/calendar_skeleton.py` | Step 3: release dates as far ahead as FRED publishes them (~4 months, not 12) plus `--months-back` for history. |
| `fetchers/ff_sync.py` | Step 4: weekly forecasts, diff, notify. One week, see below. |
| `fetchers/notify.py` | Step 5: `send(message)` -> Telegram + notifications_log. |
| `fetchers/reminders.py` | Step 5: 24h / 60min reminders for weight >= 4. |
| `fetchers/fred_actuals.py` | Step 6: fill `actual`, compute `surprise`. |
| `fetchers/prices_daily.py` | Step 7: daily prices, backfill, `events.regime`. |
| `web/app.py` | FastAPI routes. Read-only; every read degrades, never 500s. |
| `web/presenters.py` | Pure: rows -> view models. Colours, formatting, no local time. |
| `web/templates/` | Jinja2. Emits `data-utc`; never formats local time. |
| `web/static/js/tz.js` | Converts every `data-utc` stamp. FullCalendar converts its own feed (`timeZone: 'local'`). |
| `web/static/css/app.css` | Hand-written; no framework in this slice. |
| `sql/001_init.sql` | Schema + `event_weights` seed. Run by hand in Supabase. |
| `sql/002_short_title.sql` | Adds `event_weights.short_title` + 27 calendar abbreviations. **Not yet applied** - see `next-steps.md`. |
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
| `GET /api/events?start=&end=` | JSON feed for FullCalendar. Max 400 days. `start` ends in `Z`. |
| `GET /events/{id}` | HTMX detail panel, including the Stage 3 slot. |
| `GET /health` | Liveness plus whether Supabase is reachable. |

## Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `SUPABASE_URL` | `db/client.py` | Project URL. |
| `SUPABASE_SERVICE_KEY` | `db/client.py` | Holds Supabase's current `sb_secret_...` key, not a legacy `service_role` JWT. Bypasses RLS, server only. Needs `supabase>=2.31`. |
| `FRED_API_KEY` | `calendar_skeleton`, `fred_actuals`, `prices_daily` | Free. |
| `TELEGRAM_BOT_TOKEN` | `notify` | From @BotFather. |
| `TELEGRAM_CHAT_ID` | `notify` | Numeric chat id. |

`common/config.py` reads `.env` via `python-dotenv` when present, then the real
environment (which is what GitHub Actions supplies). Missing variables raise
`MissingConfig` naming the variable — fetchers fail fast rather than half-running.

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

**Repository secrets.** Three are set and confirmed with `gh secret list`:
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FRED_API_KEY`. `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` are deliberately **not** set, so the Telegram steps run and
degrade to logging. `DATABASE_URL` is not a workflow secret either: no workflow
runs DDL. `tests/test_workflows.py` fails if a workflow ever references a secret
outside the set of five, or runs a fetcher module that does not exist.

All four workflows were dispatched and verified green against the live services
on 2026-09-01; the run ids are in `progress.md`.

## Workarounds and source deviations

Verified against the live sources on 2026-08-31. Reasoning is in `decisions.md`.

| Source | Reality | What we do |
|---|---|---|
| `ff_calendar_thisweek.json` | 200, ~112 entries, ~27 USD rows | Required feed. |
| `ff_calendar_nextweek.json` | **404** (as are lastweek/today/tomorrow) | Optional feed, `allow_404`. Forecasts therefore exist for about one week only, and `calendar_skeleton` supplies every date beyond that. |
| FOMC dates | No FRED release covers them | Regex the Fed calendar page; a table transcribed on 2026-08-31 is the fallback. All 16 fallback dates for 2026-27 match the live page. |
| ISM PMIs | Withdrawn from FRED over licensing | Dates and forecasts still come from ForexFactory; `actual` stays null, and `series_map` records why. |
| `dxy` column | ICE DXY is not free with history | Holds FRED `DTWEXBGS`, the Fed's broad dollar index. Named `dxy` but is **not** ICE DXY. |
| LBMA gold on FRED | **Both series now return `400 does not exist`**, and FRED has no free daily spot gold at all | `FRED_GOLD_SERIES = None`, so no run wastes a call on it. `xau_close` comes solely from yfinance `GC=F` (pinned `1.7.0`; 0.2.x is broken against Yahoo). Single point of failure - see `progress.md`. |
| Windows + `zoneinfo` | No IANA database on Windows | `tzdata` is pinned in requirements. |

Console and log strings are kept ASCII-only: the Windows console is cp1252 and
turns an em dash into `?`.

## Time on the two pages

Both pages convert in the browser and neither formats a local time on the
server, but they do it by different routes, which is where the 2026-09-01 bug
lived:

| Page | Server emits | Converted by |
|---|---|---|
| `/` and the partials | `<time data-utc="...+00:00">`, empty text | `web/static/js/tz.js` |
| `/calendar` | `/api/events` `start` as `...Z` | FullCalendar, `timeZone: 'local'` |

The `Z` is load-bearing: a JavaScript `Date` reads an instant with no offset as
*local*, which would shift every release by the viewer's offset silently.
`timeutil.iso_z` exists for that feed alone; `iso_utc` still produces `+00:00`
everywhere else, so nothing stored has to change.

Testing a browser timezone needs Chrome DevTools' `Emulation.setTimezoneOverride`
over CDP. The `TZ` environment variable does **not** work on Windows - Chrome
reads the OS zone, so a `TZ=`-prefixed run silently re-tests the same zone and
looks like a pass.
