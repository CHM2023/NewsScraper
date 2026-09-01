# Progress

Status values: todo / in progress / done / blocked.

| # | Step | Status | Verified by | Gaps |
|---|------|--------|-------------|------|
| 1 | Project skeleton | done | Pushed to origin main; remote head 7cf8744 matches local | none |
| 2 | Supabase schema | done, VERIFIED LIVE | 5 tables reachable over PostgREST; event_weights = 27 rows | Applied by hand in the SQL editor, not via scripts/apply_schema.py |
| 3 | Annual calendar skeleton | done, VERIFIED LIVE | 46 rows written from live FRED+Fed; times correct (NFP 12:30Z, FOMC 18:00Z) | FRED only publishes release dates to year end - 4 months, not 12 |
| 4 | ForexFactory weekly sync + diff | done, VERIFIED LIVE | 27 USD rows; 25 new + 2 merged onto skeleton rows; zero duplicate (date,title) pairs | next-week feed still 404, so forecasts cover ~1 week |
| 5 | Telegram notifications + reminders | done | 35 tests; send never raises, reminders fire once | No Telegram credentials, so no live delivery test |
| 6 | Actuals from FRED + surprise | done, VERIFIED LIVE | 39 historical events filled; CPI/PPI/NFP/PCE cross-checked against raw FRED; surprise wiring verified | No consensus history, so surprise is null for backfilled events |
| 7 | Daily prices + 10y backfill + regime | done, VERIFIED LIVE | 3651 price rows 2016-2026, 2512 gold closes; regimes correct across history | gold depends solely on yfinance GC=F; dxy is the Fed broad index |
| 8 | GitHub Actions workflows | done | 44 tests guard module names, secrets, crons and step order | Cannot run in GitHub Actions until the repo is pushed and secrets added |
| 9 | Web: Today / This week | done, VERIFIED LIVE | Served real Supabase rows: /health reports `database: ok`, / renders real release titles with data-utc stamps, /api/events returns 35 September events with the right weight colours | Event detail is not linked from the today table |
| 10 | Web: Calendar + event detail | done, VERIFIED LIVE | /calendar renders live rows in UTC; /events/USD%7CCPI%20m%2Fm%7C2026-08-12 shows actual 0.07 and regime holding | Event detail is reachable from the calendar only, not from the today table |

## Known gaps

Verified on 2026-08-31. All ten steps are code-complete and the suite is green
(503 tests, no network). What has *not* been exercised end to end:

- **Nothing has touched Supabase.** No credentials were supplied this session, so
  `sql/001_init.sql` has not been applied and no fetcher has written a row. Every
  database interaction is covered by tests against fakes, not against Postgres.
- **No FRED call has been made.** `FRED_API_KEY` is absent, so
  `calendar_skeleton`, `fred_actuals` and `prices_daily` are unverified against
  the live API. The series ids in `series_map.py` are the most likely thing to be
  wrong; a wrong id logs "no usable observation" and skips, it does not crash.
- **No Telegram message has been sent.** `notify.send` is fully tested against a
  fake transport, but the bot token has never been exercised.
- **The repository has never been pushed.** No GitHub credential exists on this
  machine, so the workflows have never run. See `decisions.md`.

Verified live this session, without credentials:
- ForexFactory: 112 entries, 27 USD rows parsed, `errors=0`.
- The FOMC calendar parser against the real federalreserve.gov page: 27 dates,
  and all 16 fallback dates for 2026-27 match it exactly.
- `uvicorn web.app:app` serving `/`, `/calendar`, `/health` and the static files
  over HTTP.
