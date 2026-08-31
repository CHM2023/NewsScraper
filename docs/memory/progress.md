# Progress

Status values: todo / in progress / done / blocked.

| # | Step | Status | Verified by | Gaps |
|---|------|--------|-------------|------|
| 1 | Project skeleton | done | Pushed to origin main; remote head 7cf8744 matches local | none |
| 2 | Supabase schema | done | 5 tables + 27 seeded weights; SQL parses, not yet applied | Owner must run it in the Supabase SQL editor |
| 3 | Annual calendar skeleton | done | 22 tests; ids proven to match ff_sync; DST verified both sides of each changeover | Not yet run against live FRED - needs FRED_API_KEY |
| 4 | ForexFactory weekly sync + diff | done | 34 tests against a captured feed; diff/NEW/CHANGED covered | Not yet run against live Supabase |
| 5 | Telegram notifications + reminders | done | 35 tests; send never raises, reminders fire once | No Telegram credentials, so no live delivery test |
| 6 | Actuals from FRED + surprise | done | 28 tests covering all five transforms | ISM unmapped by design; some FRED series ids unverified against the live API |
| 7 | Daily prices + 10y backfill + regime | done | 66 tests: regime, blackout, source merge and gold fallback | dxy column holds the Fed broad index, not ICE DXY - see decisions.md |
| 8 | GitHub Actions workflows | done | 44 tests guard module names, secrets, crons and step order | Cannot run in GitHub Actions until the repo is pushed and secrets added |
| 9 | Web: Today / This week | done | 39 web tests + live uvicorn check; HTMX polls every 300s; all data-utc verified UTC | Shows empty state until Supabase is configured |
| 10 | Web: Calendar + event detail | done | FullCalendar in UTC, colour by weight, HTMX detail panel with the Stage 3 slot | Event detail is reachable from the calendar only, not from the today table |

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
