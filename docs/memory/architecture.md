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
| `db/client.py` | Builds and caches the Supabase client. Lazy import. |
| `db/repo.py` | Every query in the project. The only module that touches the client. |
| `fetchers/parsing.py` | Pure: `"250K"` -> `250000.0`, forecast/previous strings. |
| `fetchers/titles.py` | Pure: canonical event titles + weight lookup. |
| `fetchers/diff.py` | Pure: incoming vs stored -> NEW / CHANGED / unchanged. |
| `fetchers/surprise.py` | Pure: `(actual-forecast)/abs(forecast)*10`, clamped. |
| `fetchers/regime.py` | Pure: 90-day Fed funds direction -> hiking/holding/cutting. |
| `fetchers/blackout.py` | Pure: high-weight event windows to stay out of. |
| `fetchers/series_map.py` | Title -> FRED series id + transform, for actuals. |
| `fetchers/fomc.py` | FOMC calendar parsing + a verified fallback date table. |
| `fetchers/calendar_skeleton.py` | Step 3: 12 months of release dates. |
| `fetchers/ff_sync.py` | Step 4: this/next week forecasts, diff, notify. |
| `fetchers/notify.py` | Step 5: `send(message)` -> Telegram + notifications_log. |
| `fetchers/reminders.py` | Step 5: 24h / 60min reminders for weight >= 4. |
| `fetchers/fred_actuals.py` | Step 6: fill `actual`, compute `surprise`. |
| `fetchers/prices_daily.py` | Step 7: daily prices, backfill, `events.regime`. |
| `web/app.py` | FastAPI routes. Read-only. |
| `web/templates/` | Jinja2. Emits `data-utc`; never formats local time. |
| `web/static/js/tz.js` | The only place UTC becomes local time. |
| `sql/001_init.sql` | Schema + `event_weights` seed. Run by hand in Supabase. |
| `tests/fixtures/` | Captured API responses. Tests never hit the network. |

The split between pure modules and I/O modules is deliberate: everything with
interesting logic (parsing, diff, surprise, regime, blackout) is a pure function
tested against fixtures, and the fetchers are thin wiring around them.

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
