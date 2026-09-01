# Progress

Status values: todo / in progress / done / blocked.

| # | Step | Status | Verified by | Gaps |
|---|------|--------|-------------|------|
| 1 | Project skeleton | done | Pushed to origin main; remote head 7cf8744 matches local | none |
| 2 | Supabase schema | done, VERIFIED LIVE | 5 tables reachable over PostgREST; event_weights = 27 rows | Applied by hand in the SQL editor, not via scripts/apply_schema.py |
| 3 | Annual calendar skeleton | done, VERIFIED LIVE | 181 rows. One FRED release fans out into every print it carries (CPI day = m/m + y/y + core); a Fed decision day = statement, rate, projections and press conference, EDT/EST correct | FRED only publishes release dates to year end - 4 months, not 12 |
| 4 | ForexFactory weekly sync + diff | done, VERIFIED LIVE | 27 USD rows; 25 new + 2 merged onto skeleton rows; zero duplicate (date,title) pairs | next-week feed still 404, so forecasts cover ~1 week |
| 5 | Telegram notifications + reminders | done, TESTED ONLY | 35 tests; send never raises, reminders fire once. Both fetchers ran live in Actions and degraded cleanly: `telegram not configured: reported due reminders, flagged none` | **No message has ever been delivered.** Credentials are unset by instruction, so the whole delivery path is unexercised |
| 6 | Actuals from FRED + surprise | done, VERIFIED LIVE | 39 historical events filled; CPI/PPI/NFP/PCE cross-checked against raw FRED; surprise wiring verified | No consensus history, so surprise is null for backfilled events |
| 7 | Daily prices + 10y backfill + regime | done, VERIFIED LIVE | 3651 price rows 2016-2026, 2512 gold closes; regimes correct across history | gold depends solely on yfinance GC=F; dxy is the Fed broad index |
| 8 | GitHub Actions workflows | done, VERIFIED LIVE | All four dispatched and green on real secrets - see the run table below | Telegram steps run but cannot deliver; `actions/checkout@v4` + `setup-python@v5` warn that Node 20 is deprecated |
| 9 | Web: Today / This week | done, VERIFIED LIVE | Served real Supabase rows: /health reports `database: ok`, / renders real titles with data-utc stamps that tz.js converts | Event detail is not linked from the today table |
| 10 | Web: Calendar + event detail | done, VERIFIED LIVE | Times convert in the browser - NFP reads 15:30 Beirut / 22:30 Sydney / 12:30 UTC, checked over CDP. Low-impact toggle filters 24->48 and persists; listMonth below 700px; detail shows both clocks | `short_title` needs sql/002 applied, so titles ellipsise until then |

## Workflow runs verified live

Dispatched by hand on 2026-09-01 with `gh workflow run`, all four green on the
real repository secrets. `pip install -r requirements.txt` resolved the new pins
(`supabase==2.31.0`, `yfinance==1.7.0`, `tzdata`, `psycopg[binary]`) on the
ubuntu-latest / Python 3.12 runner with no build step and no conflict.

| Workflow | Run | Result |
|---|---|---|
| `tests.yml` | [33504211064](https://github.com/CHM2023/NewsScraper/actions/runs/33504211064) | 543 tests green in 33s, triggered by the push of 8bde217 |
| `calendar-sync.yml` | [33504224862](https://github.com/CHM2023/NewsScraper/actions/runs/33504224862) | 27s. Read 27 weights from Supabase, parsed 113 entries -> 27 USD rows, diffed `0 new, 0 changed, 27 unchanged` |
| `daily.yml` | [33504310243](https://github.com/CHM2023/NewsScraper/actions/runs/33504310243) | 36s. Skeleton 46 dates (0 new, already present); actuals found 0 events missing; prices inserted 6 rows incl. 6 gold closes from `GC=F` |
| `reminders.yml` | [33504544368](https://github.com/CHM2023/NewsScraper/actions/runs/33504544368) | 0 candidates in either tier, and **flagged none** because Telegram is unconfigured |

Three of those results are zeros, which is the shape a silent failure takes, so
each was checked rather than trusted:
- `calendar-sync` reading back 27 unchanged rows proves the diff saw real stored
  rows - those are the same 27 the local run wrote yesterday.
- `daily`'s skeleton reports `fetched=46 skipped=47`. The extra one is not an
  off-by-one: `skipped` counts both the 46 rows already present *and* the one
  release it could not resolve, ISM (withdrawn from FRED, decisions.md
  2026-08-31). `fred_actuals` finding nothing missing is correct - yesterday's
  run filled every event in the window.
- `reminders` finding 0 candidates was checked against the database: the next
  weight >= 4 event is Non-Farm Employment Change on 2026-09-04 12:30Z, outside
  both the 1h and 24h windows. Everything due sooner is weight 1 or 3.

## Known gaps

Verified on 2026-09-01. All ten steps are code-complete, the suite is green
(543 tests, no network), and every component except Telegram has now been run
against the live service it depends on.

**Verified live** - run end to end against the real service, output cross-checked:
Supabase schema, `calendar_skeleton`, `ff_sync`, `prices_daily`, `fred_actuals`,
all four workflows, and the web app on real rows.

**Blocked on the owner:** `sql/002_short_title.sql` is written and verified but
not applied - `DATABASE_URL` is unset and Supabase's direct host is IPv6-only
from this machine. Until it runs, calendar titles fall back to the full text.

**Tested only** - covered by the suite against fakes, never exercised for real:
- **Telegram.** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are empty by
  instruction and were deliberately not set as repository secrets. `notify.send`
  is fully tested against a fake transport, but no message has been delivered, no
  `notifications_log` row has `ok = true`, and no reminder flag has ever flipped.
  This is the one remaining unknown in the slice; see `next-steps.md`.
- **`scripts/apply_schema.py`.** The schema was applied by hand in the Supabase
  SQL editor, so the script itself has never run.

Carried forward, understood and not being fixed now:
- **The skeleton horizon is ~4 months, not 12.** FRED publishes release dates
  only to the end of the current calendar year. `daily.yml` extends the horizon
  by itself as FRED publishes further out.
- **Forecasts cover about one week.** `ff_calendar_nextweek.json` still 404s.
- **Surprise is null for every backfilled event**, because they have no forecast
  and consensus history is not free. Stage 3 needs a source for it.
- **`xau_close` depends solely on yfinance `GC=F`.** FRED retired both LBMA
  series. If Yahoo breaks again the column goes null with `errors=0`, exactly as
  it did on 2026-09-01. `prices_daily` should grow a coverage check that fails
  the run when gold is missing for too many recent weekdays.
- **ISM has no actuals source** and no FRED release date, so it is scheduled from
  ForexFactory only and its `actual` stays null.
- **`dxy` is the Fed broad dollar index (`DTWEXBGS`), not ICE DXY.**
