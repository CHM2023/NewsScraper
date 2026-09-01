# Decisions

Append-only. Newest at the bottom. Every entry: what was chosen, what was
rejected, and why.

## 2026-08-31 — Concept doc lives at `docs/gold-news-platform.md`
The build brief referred to `docs/project-concept.md`. The file actually present
is `docs/gold-news-platform.md`. **Chosen:** leave the owner's filename alone and
reference the real path everywhere. **Rejected:** renaming it, which would break
any link the owner already has.

## 2026-08-31 — A `common/` package for config and time helpers
`config` and `timeutil` are needed by `fetchers/`, `db/` and `web/` alike, so they
belong to none of them. **Chosen:** a small `common/` package. **Rejected:**
root-level `config.py` (clutters the root, and `timeutil` would have nowhere
natural to live) and putting config in `db/` (Telegram and FRED settings are not
database concerns).

## 2026-08-31 — `httpx` pinned explicitly in requirements.txt
Not in the brief's library list. It is already a hard dependency of `supabase`,
and `starlette.testclient` (used by the web tests) imports it directly. **Chosen:**
pin it so CI and local resolve identically. **Rejected:** leaving it transitive,
which historically breaks when supabase and httpx versions drift apart.

## 2026-08-31 — Makefile *and* PowerShell scripts
Owner develops on Windows 11; CI runs on ubuntu-latest. `make` is not installed by
default on Windows. **Chosen:** ship both a `Makefile` (CI, Linux, macOS) and
`scripts/*.ps1` (owner's machine) with the same four verbs. **Rejected:**
Makefile only (unusable for the owner), scripts only (noisier in CI).

## 2026-08-31 — BLOCKED: cannot push to origin, no GitHub credential on this machine
`git ls-remote origin` returns `Permission denied (publickey)`. `~/.ssh` holds one
key, `id_ed25519_g15` (comment `agentrag-automation`); tested explicitly against
`git@github.com` with `IdentitiesOnly=yes` and it is also rejected. `gh` is not
installed. **Chosen:** keep committing locally in the required order and hand the
owner an actionable fix, per the brief's "do not retry blindly". **Rejected:**
stopping the session at step 1 (the remaining nine steps do not depend on the
remote), and switching the remote to HTTPS unasked (it would just prompt for a
password that is not available here either).
Fix, whichever suits: add this machine's public key to the GitHub account, or
`gh auth login`, or `git remote set-url origin https://github.com/CHM2023/NewsScraper.git`
and push with a PAT. Then `git push -u origin main`.

## 2026-08-31 — Three columns added beyond the brief's table
**Chosen:** `events.source` ('skeleton' | 'forexfactory'), plus
`notifications_log.event_id` and `notifications_log.ok`. `source` is needed
because two fetchers write the same row and the UI must show which one is
authoritative; the notifications columns make delivery failures debuggable and
allow dedupe. **Rejected:** inferring source from `impact IS NULL` (fragile) and
a write-only notification log (undiagnosable when Telegram silently fails).

## 2026-08-31 — RLS enabled with no policies
Every writer uses the `service_role` key, which bypasses RLS; the web app is
server-rendered and also server-keyed. **Chosen:** `enable row level security`
with zero policies, so anon/authenticated clients get nothing while service_role
keeps working. **Rejected:** leaving RLS off (Supabase flags it, and the tables
would be readable by anyone holding the anon key).

## 2026-08-31 — `tzdata` added, so Eastern-to-UTC conversion is real
Windows ships no IANA time zone database, so `zoneinfo.ZoneInfo("America/New_York")`
raises there. FRED gives a release *date* with no time, so the skeleton has to
supply 08:30/10:00/14:00 ET itself and convert. **Chosen:** add the `tzdata`
package and convert through the real zone, so a January release is 13:30 UTC and
a July one 12:30 UTC. **Rejected:** hard-coding UTC-5 or UTC-4 (wrong for half
the year, and the concept doc names exactly this as a known risk), and storing
the naive date at midnight (would sort wrongly and shift event ids).

## 2026-08-31 — Skeleton and feed rows share one primary key
`calendar_skeleton` names releases as FRED does, `ff_sync` as ForexFactory does.
Left alone, the same CPI print would be stored twice. **Chosen:** translate FRED
release names to the ForexFactory title of that release's headline number
(`fetchers/titles.py`), so both writers compute the same
`USD|<title>|<YYYY-MM-DD>` id and the second updates the first's row. Feed-only
secondary prints (Core CPI m/m, Unemployment Rate) still get their own rows
inside the two-week forecast window. **Rejected:** a separate `source` table with
a join (heavier than the problem), and letting duplicates through and
de-duplicating in the UI (the notification diff would fire twice).

## 2026-08-31 — Ownership rule: the feed wins over the skeleton
A row carries `source`. `ff_sync` always overwrites; `calendar_skeleton` skips
any row already marked `forexfactory`. **Chosen** so a precise feed timestamp is
never replaced by the skeleton's standing-time guess on a later run. **Rejected:**
last-writer-wins, which made the stored time flip depending on which cron ran
last.

## 2026-08-31 — Surprise is null, not zero, when the forecast is zero
The formula divides by `|forecast|`. **Chosen:** return None for a zero forecast
and render "n/a". **Rejected:** substituting an absolute difference, which would
put a number on the same -3..+3 scale that does not mean the same thing as the
others and would quietly corrupt any Stage 3 average built on it.

## 2026-08-31 — Reminder tiers are disjoint, and flags are set before sending
The 24h tier ignores anything inside 60 minutes, and sending the 1h reminder also
sets `reminded_24h`. **Chosen** so an event ff_sync discovers *inside* the 24h
window cannot fire a "24 hours away" message about something 40 minutes out.
Flags are written before the send: **chosen** because a missed reminder is a much
smaller failure than a loop re-sending every 15 minutes when the flag write fails
after a successful send. **Rejected:** send-then-flag, and a single tier.

## 2026-08-31 — ISM has no actuals source
ISM withdrew its PMIs from FRED over licensing, and there is no free replacement.
**Chosen:** keep ISM in the calendar (dates and forecasts come from ForexFactory,
which is what the trader reads) but leave it unmapped in `series_map.py`, with the
reason recorded so `fred_actuals` logs *why* it skipped rather than "unknown".
**Rejected:** dropping ISM from the calendar, and scraping ismworld.org.

## 2026-08-31 — FOMC dates: parse the Fed page, with a transcribed fallback
FRED has no FOMC release. **Chosen:** regex the Federal Reserve calendar page
(stable `fomc-meeting__month` / `fomc-meeting__date` class names) and keep a
fallback table transcribed from it on 2026-08-31, used only when the fetch fails
and logged loudly when it is. The announcement is the meeting's *closing* day.
**Rejected:** adding BeautifulSoup for one page, and shipping only the hard-coded
table (it would silently rot).

## 2026-08-31 — The dollar index is the Fed's broad index, not ICE DXY
ICE DXY is not available free with ten years of history. **Chosen:** FRED
`DTWEXBGS`, the Fed's nominal broad trade-weighted dollar index, with yfinance
`DX-Y.NYB` as a fallback if FRED returns nothing. The two correlate closely
enough for conditioning a gold event study, and DTWEXBGS is one reliable API
call for the whole backfill. **Rejected:** scraping ICE, and paying for a data
vendor in a free-tier project. *If Stage 3 results ever look sensitive to this
choice, revisit it - the column is named `dxy` but does not hold ICE DXY.*

## 2026-08-31 — Gold: FRED LBMA first, yfinance when it is stale
FRED's `GOLDPMGBD228NLBM` has been discontinued once already over ICE licensing.
**Chosen:** read FRED, and if its newest observation is more than 10 days old (or
absent) fall back to yfinance `GC=F` for the range, merging per date with FRED
preferred. The run notes record which source answered. **Rejected:** yfinance
only (less reliable in CI, and no London PM fix), and FRED only (would silently
stop updating the day the series is retired again).

## 2026-08-31 — Regime returns None, not "holding", when history is thin
`classify_regime` needs a Fed funds observation both at the event date and 90
days earlier. **Chosen:** return None when either is missing, so a partial
backfill leaves `events.regime` null instead of labelling a decade of events as a
flat rate environment - which would quietly corrupt the Stage 3 regime filter,
the very thing the concept doc says prevents "confidently wrong answers".
Threshold is 0.125, half a standard 25bp move, so quarter-end noise in the
effective rate does not read as policy. **Rejected:** defaulting to "holding".

## 2026-08-31 — Blackout windows are informational and asymmetric
The brief asks for blackout logic to be tested but does not define it. **Chosen:**
`fetchers/blackout.py`, a pure module giving a window of 30 minutes before to 15
minutes after any event of weight >= 4, surfaced as a banner on the "today" page.
Asymmetric because liquidity thins well before a print and returns sooner after
it. Simultaneous releases report the heaviest event. **Rejected:** enforcing
anything (the platform informs, it does not trade) and a symmetric window.

## 2026-08-31 — VERIFIED LIVE: only `ff_calendar_thisweek.json` still exists
Checked against the live host on 2026-08-31. `ff_calendar_thisweek.json` returns
200 (112 entries, 27 USD rows). `ff_calendar_nextweek.json`, `_lastweek`,
`_today` and `_tomorrow` all return **404**. The brief assumed a two-week
forecast window; the real window is one week.
**Chosen:** model a feed as `Feed(url, required=...)`. The this-week feed is
required and its loss is an error; the next-week feed is kept in the list but
optional, fetched with `allow_404=True`, so a 404 logs at INFO, does not count
as an error, and the extra week is picked up automatically if the publisher ever
restores it. **Rejected:** deleting the next-week URL (throws away a free
upgrade), and leaving it required (an ERROR line on all 24 scheduled runs a day,
which trains the owner to ignore the log).
**Consequence:** `calendar_skeleton` is now the *only* source of dates beyond
about a week, so it matters more than the brief implies. Forecasts simply do not
exist past that horizon, and the UI shows "n/a" rather than implying none was
published.

## 2026-08-31 — VERIFIED LIVE: the FOMC parser works against the real page
`fetch_decision_dates()` parsed 27 announcement dates from federalreserve.gov,
2021 through 2027. All 16 dates in `FALLBACK_DECISION_DATES` (2026-2027) match
the live page exactly, so the transcription is correct as of today. The parser
returns historical years too; `calendar_skeleton` clips to its 12-month window.

## 2026-08-31 — The web app degrades instead of returning 500
Every database read in `web/app.py` goes through `_safe()`. **Chosen:** a missing
credential or an unreachable Supabase renders an empty page with a specific,
actionable banner; an unexpected error renders a generic one and logs the
traceback server-side. `/api/events` answers 200 with `{"events": [], "warning":
...}` rather than a non-2xx, because FullCalendar treats any non-2xx as a load
failure and renders nothing at all. **Rejected:** letting the exception surface
(the owner could not see the interface before the database existed, and a
transient fault would show a stack trace), and putting the Postgres error text on
the page.

## 2026-08-31 — No local time is produced on the server, anywhere
Templates emit `<time data-utc="...">` with empty content; `web/static/js/tz.js`
fills it in from the browser's zone and keeps the UTC value in the `title`
attribute. FullCalendar is configured `timeZone: 'UTC'` so its grid stays aligned
with the event ids, which are keyed on the UTC date. A test asserts every
`data-utc` the pages emit ends in `+00:00`. **Rejected:** a server-side timezone
setting or an offset cookie - the concept doc names a daylight-saving mistake as
the bug most likely to break things silently, and the defence is that the server
has no opinion about the viewer's zone at all.

## 2026-08-31 — Push unblocked
`ssh -T git@github.com` now greets `CHM2023`. `git push -u origin main` succeeded
and `git ls-remote origin main` matches the local head. The blocked-push entry
above is resolved; it is left in place because it records why the first session's
commits were local only.

## 2026-08-31 — `SUPABASE_SECRET_KEY` accepted as an alias
Supabase's dashboard no longer says "service_role": the server-side key is now
labelled a **Secret key** and starts `sb_secret_`. The owner's `.env` uses that
name. **Chosen:** an `ALIASES` table in `common/config.py`, canonical name first,
so `SUPABASE_SERVICE_KEY` resolves from `SUPABASE_SECRET_KEY`. **Rejected:**
asking the owner to re-paste a secret under a different name, and renaming the
variable everywhere (the workflows, `.env.example` and the docs all use the
canonical name, and a rename would break any environment already set up).
Verified: the key authenticates against PostgREST - the pre-schema probe
returned `PGRST205 table not found`, which is a 404 *after* a successful auth,
not the 401 a bad key gives.

## 2026-08-31 — `psycopg` added, and a script rather than psql
PostgREST cannot run DDL, and `psql` is not on this machine's PATH. **Chosen:**
`psycopg[binary]` in requirements plus `scripts/apply_schema.py`, which sends the
file as one transaction and then verifies the five tables and the 27 seeded
weights. **Rejected:** installing the Postgres client tools for one statement,
and pasting the SQL into the dashboard by hand (not reproducible, and the next
migration would need the same manual step). `DATABASE_URL` stays out of the
repository secrets: no workflow runs DDL.

## 2026-08-31 — Telegram absent: degrade, never lose a reminder
Credentials are deliberately unavailable this session. Two problems that only
appear once a fetcher runs for real:
1. `notify.send` warned on *every* call, so one ff_sync run with 30 qualifying
   events would emit 30 warnings and write 30 `notifications_log` rows.
2. Worse, `reminders` flips `reminded_*` **before** sending. With no token that
   would have marked every due event as reminded and lost the reminder for good.
**Chosen:** `notify.enabled()`, a warn-once notice reading exactly
`notifications disabled: no token`, and no `notifications_log` row when nothing
was attempted. `reminders.run()` degrades to a dry run when no bot is configured,
so events stay pending and fire correctly once a token exists. `ff_sync.announce`
still logs each NEW/CHANGED line at INFO - that is the useful record - but sends
nothing and counts no error. **Rejected:** letting reminders flag-and-drop (silent
data loss), and treating a deliberately absent token as a run error.

## 2026-08-31 — VERIFIED LIVE: every FRED series id in series_map.py is correct
Resolved all 17 ids against `/fred/series` with the live key. All returned the
expected series, including the four flagged in the last session's next-steps as
most likely wrong: `PPIFIS` (PPI final demand), `RSFSXMV` (retail sales ex motor
vehicles), `CES0500000003` (average hourly earnings) and `EXHOSLUSM495S`
(existing home sales). **No id changes were needed.**
Units were checked against the scales too, since a units mismatch would silently
produce a surprise score off by a factor of a thousand: `PAYEMS` and the housing
series report "Thous.", matching `scale=1000`; `EXHOSLUSM495S` reports "Number of
Units", matching `scale=1`. `DFEDTARU` is daily and current to today, which is
what `level_at_or_after` needs to read a decision on the day.

## 2026-08-31 — GitHub CLI installed user-scope; its login needs a terminal
`winget install --id GitHub.cli -e` failed with MSI exit code 1603 (the
system-scope install wants elevation). `--scope user` succeeded via the zip
package: `gh` 2.98.0 now sits at
`%LOCALAPPDATA%\Microsoft\WinGet\Links\gh.exe`.
`gh auth login --web` could not be driven from here - the device flow needs a
TTY and produced no output with stdin closed, so it was stopped rather than left
hanging. **Chosen:** the owner runs `gh auth login` once in their own terminal,
after which this session can set the secrets; failing that, the three secrets go
in by hand in the browser. **Rejected:** asking for a personal access token
(a broader credential than the task needs, and one more secret to handle).
Note SSH auth to GitHub already works, but that does not help: setting a
repository secret goes through the REST API, which needs a token.

## 2026-09-01 — supabase-py upgraded 2.11 -> 2.31 to accept `sb_secret_` keys
The owner applied the schema by hand, but the first real client call failed with
`SupabaseException: Invalid API key`. The key was not the problem: supabase-py
2.11 validated it against a **JWT-shaped regex**
(`^[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?...$`) and Supabase's current secret keys
are `sb_secret_...`, which has no dots. The raw PostgREST probe with the same key
had already authenticated, so the rejection was purely client-side.
**Chosen:** upgrade to `supabase==2.31.0`, which drops that check entirely.
Verified afterwards: all five tables reachable, 27 weights read back, suite still
green. **Rejected:** asking for the legacy `service_role` JWT (it is the older,
coarser credential and Supabase is migrating away from it), and monkey-patching
the regex (leaves a landmine for the next person who upgrades).

## 2026-09-01 — Repository secrets set, three of them
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (from the `SUPABASE_SECRET_KEY` value) and
`FRED_API_KEY`, confirmed with `gh secret list`. Deliberately **not** set:
the two Telegram variables (no credentials this session, and the fetchers now
degrade cleanly without them) and `DATABASE_URL` (no workflow runs DDL, so
shipping the database password to CI would widen the blast radius for nothing).
Values were piped to `gh` over stdin rather than passed as `--body`, so no secret
reached a command line or the shell history.

## 2026-09-01 — BUG FOUND LIVE: PostgREST silently caps a select at 1000 rows
`prices_daily` held 3651 rows after the backfill, but a default `select()`
returned exactly 1000 - no error, no marker, the response just stops.
`repo.fetch_fed_funds` therefore saw only 2016-09-01..2019-05-28, so
`classify_regime` compared a 2019 rate with a 2019 rate, found no change, and
tagged **all 71 events `holding`**. This is precisely the "confidently wrong
answer" the concept doc's rule 2 exists to prevent, and nothing about the run
looked wrong: `errors=0`, and today's events genuinely *are* holding, so the
answer was right by coincidence. It would have mislabelled every historical
event Stage 3 backfills.
**Chosen:** `db/repo._fetch_paged()`, which pages with `.range()` until a short
page arrives, applied to every unbounded reader (`fetch_event_weights`,
`fetch_events_between`, `fetch_events_missing_actual`,
`fetch_reminder_candidates`, `fetch_prices`). Each paged query now carries a
second `.order("id")`/`.order("date")` tiebreaker, because paging a query whose
sort has ties can repeat or skip rows. `fetch_recent_releases` keeps its explicit
`.limit(10)` and is deliberately not paged.
**Rejected:** raising PostgREST's `max-rows` server-side (it is a project-wide
setting, and code that assumes an unbounded response is fragile regardless), and
passing a large `.limit()` (moves the cliff rather than removing it).
Verified after the fix: `fetch_fed_funds` returns 3649 rows spanning 2016-2026,
and the classifier gives hiking for 2018 and 2022, cutting for 2020, holding for
2024 and 2026. `tests/test_repo_paging.py` covers it.

## 2026-09-01 — BUG FOUND LIVE: no free daily gold price left, and yfinance 0.2 is broken
Two failures stacked on the most important column in the project:
1. FRED's `GOLDPMGBD228NLBM` now returns `400 The series does not exist`, as does
   `GOLDAMGBD228NLBM`. A FRED search turns up **no free daily spot gold series at
   all** - only volatility indices (GVZCLS) and an index (NASDAQQGLDI).
2. The designed fallback, yfinance `GC=F`, failed too:
   `YFTzMissingError: possibly delisted; no timezone found`, a known break
   between yfinance 0.2.x and Yahoo's current API.
The net effect was a "successful" backfill - `errors=0`, 3649 rows - with
`xau_close` **entirely null**.
**Chosen:** pin `yfinance==1.7.0`, which works (`GC=F` returns 2512 closes over
ten years, last 2026-08-31 = 4431.10), and set `FRED_GOLD_SERIES = None` so no
run wastes a call on a retired series or logs an error for it. The constant is
kept, documented, and preferred if it is ever set again.
**Rejected:** Stooq's XAUUSD CSV, which now sits behind a JavaScript
proof-of-work bot challenge and cannot be read from a script; and GLD as a proxy,
which is an ETF price, not spot gold.
**Watch:** gold now has a single unpinned-upstream source. If Yahoo breaks again,
`xau_close` goes null silently - `prices_daily` should grow a check that fails
the run when gold coverage over the last 30 weekdays drops below a threshold.

## 2026-09-01 — BUG FOUND LIVE (1 of 2): the observation cache ignored its window
`fred_actuals` cached FRED observations under `(series_id, lookback)`, but the
window it fetched was derived from the **first** event's date. Events are
processed oldest-first, so every later event of the same series reused a window
ending ~10 days after the oldest one - and `extract_actual` then found the same
"newest observation before asof" every time. The first live run over four months
of history gave **every** claims week 210000, **every** CPI month 0.4729, every
NFP 63000. `errors=0` throughout.
**Chosen:** resolve all events to their series first, then fetch one window per
series spanning `[min(asof) - lookback, max(asof) + forward]` (`_fetch_windows`).
One API call per series still, but a window that actually covers every date.
**Rejected:** fetching per event (correct but one call per row) and keying the
cache by window (would refetch almost every time).

## 2026-09-01 — BUG FOUND LIVE (2 of 2): every monthly actual was a month late
With the cache fixed the numbers varied, but they were still **wrong**: the CPI
released 2026-05-12 was stored as 0.4729, which is *May's* m/m. A CPI release in
May reports **April** (+0.6400). Cross-checking the stored values against the raw
CPIAUCSL index showed every monthly release was off by one month.
The cause is that FRED dates an observation by its **reference period**, not its
publication date. By the time we query, a 2026-05-01 observation exists, so
"newest observation dated before the release date" picks the month the release
has not measured yet. The bug is invisible in a fixture built from a single
release, which is why the unit tests missed it.
**Chosen:** each `SeriesSpec` now records a `frequency`. Monthly series anchor on
the **1st of the release month**, so a release in month M reads month M-1;
weekly and daily series are dated by period end and still anchor on the day.
Verified against the real 2026 index: releases on 12 May / 10 Jun / 14 Jul /
12 Aug now yield +0.6400 / +0.4729 / -0.4225 / +0.0737, matching what the BLS
published. `tests/test_fred_actuals.py::TestReferenceMonth` locks it in.
**Rejected:** FRED's realtime/vintage parameters, which would be the most correct
answer - ask what the series looked like *on* the release date - but cost one API
call per event and are not needed while the reference-period rule holds.

## 2026-09-01 — Historical events have no forecast, so no surprise
Every backfilled event has `surprise = null`, because ForexFactory publishes only
the current week and consensus history is not free - the concept doc's known risk
1. This is the designed behaviour (the brief: do not compute surprise without a
forecast), not a failure. The wiring was verified live by temporarily attaching a
forecast of 0.2 to the 2026-08-12 CPI: actual 0.0737 gave surprise -3.0
("below forecast", clamped from -6.3), stored correctly, and the temporary
forecast was then reverted. Stage 3 will need a consensus history source before
the surprise column is usable for anything historical.

## 2026-09-01 — `calendar_skeleton --months-back`
`fred_actuals` could not be verified at all: the skeleton only wrote future dates,
so there were no past events to fill in. FRED serves historical release dates from
the same endpoint. **Chosen:** a `--months-back` flag extending the window
backwards, used here to seed four months. It is also the mechanism Stage 3's
ten-year event backfill will use. **Rejected:** a throwaway script, which would
have left the history in the database with no reproducible way to regenerate it.

## 2026-09-01 — All four workflows verified live, and why the zeros were checked
`gh workflow run` on each of `tests`, `calendar-sync`, `daily` and `reminders`,
all green on the three real repository secrets. The CI install resolved the new
pins (`supabase==2.31.0`, `yfinance==1.7.0`, `tzdata`, `psycopg[binary]`) on
ubuntu-latest / Python 3.12 with no build step - worth confirming, because
`psycopg[binary]` and `yfinance` are the two most likely to need one. Run ids are
in `progress.md`.

Three of the four runs reported **zero** work done, which is the exact shape the
five bugs found earlier in the day took: `errors=0` over wrong or absent data. So
none of the zeros was taken at face value.
- `calendar-sync`: `0 new, 0 changed, 27 unchanged` is a *positive* result - the
  diff read 27 real stored rows back out of Supabase and matched them. A broken
  read would have reported 27 new.
- `daily`: `fetched=46 skipped=47` looked like an off-by-one and is not.
  `stats.skipped` is incremented in two places - once per row already present
  (46) and once per FRED release that cannot be resolved (1, ISM). The counter is
  overloaded, but the run also emits an explicit note naming ISM, so the log is
  not misleading. Left as is.
- `reminders`: `0 candidate(s)` in both tiers was checked against the database
  rather than assumed. The next weight >= 4 event is NFP on 2026-09-04 12:30Z;
  everything inside the 24h window is weight 1 or 3 (Unemployment Claims is
  deliberately weight 1 - "rarely moves gold on its own"). The zero is correct.

**Confirmed by the same run:** with no Telegram token, `reminders` logs
`reported due reminders, flagged none` - it does not flip `reminded_*`. That is
the behaviour dfae043 promised and it means the missing credentials delay
reminders rather than destroying them.

## 2026-09-01 — BUG FOUND LIVE: the calendar rendered UTC under a local-time label
`/calendar` showed Non-Farm Employment Change at 12:30 and the FOMC Statement at
18:00 while the header read "times in Asia/Beirut". Those were the raw UTC
instants: the correct local values are 15:30 and 21:00. The "Today / This week"
page was **not** affected - `tz.js` converts every `<time data-utc>` correctly,
and NFP already read 15:30 there. The divergence was one line:
`calendar.html` set FullCalendar's `timeZone: 'UTC'`, and a test
(`test_it_renders_in_utc`) asserted it, so the suite was locking the bug in.
This is worse than showing UTC honestly - a trader reads 12:30 as local and
misses the release by three hours.
**Chosen:** `timeZone: 'local'`, so FullCalendar converts exactly as tz.js does.
The feed now emits `start` with a trailing `Z` via a new `timeutil.iso_z`,
because an instant with no offset is read as *local* by `Date` and would shift
every release silently. `iso_utc` is untouched, so stored `ts_utc` values and
every `data-utc` attribute keep their `+00:00` form and nothing in the database
has to be rewritten. `eventDidMount` puts the UTC instant in a `title` attribute
so the underlying value is one hover away.
**Verified** by driving headless Chrome over CDP with
`Emulation.setTimezoneOverride` - the real DevTools mechanism. Note that the
`TZ` environment variable does **not** work for this on Windows: Chrome reads
the OS zone, so a `TZ=`-prefixed run silently re-tests the same zone and looks
like a pass. NFP on 4 Sep reads 15:30 in Asia/Beirut, 22:30 in Australia/Sydney
and 12:30 in UTC; the FOMC Statement reads 21:00, 04:00 **on 17 Sep** (the date
correctly rolls) and 18:00.
**Rejected:** keeping UTC and relabelling the calendar page, which would have
left two pages of the same app disagreeing about when a release happens.

## 2026-09-01 — A Fed decision day is four events, and the Fed marks its own SEP meetings
The calendar showed only "FOMC Statement" on 16 September. The Fed announces the
decision at 14:00 ET and holds a press conference at 14:30 ET, and at four
meetings a year also publishes the Summary of Economic Projections and dot plot.
`event_weights` already seeded all four titles at weight 5; only one was created.
**Chosen:** `calendar_skeleton` fans every decision date out into `FOMC
Statement`, `Federal Funds Rate` and `FOMC Press Conference`, plus `FOMC
Economic Projections` at projection meetings only.

**Which meetings publish an SEP: read the Fed's own marker.** The calendar page
puts an asterisk on the date of those meetings ("15-16*"), so `fomc.py` parses it
rather than inferring anything. If the Fed moves the SEP to a different meeting
the page will be right and a month-based rule would be wrong. The offline
fallback table carries no markers, so there the months March/June/September/
December stand in - a rule that reproduces the published 2026 and 2027 schedules
exactly. `fetch_meetings()` returns `Meeting(day, has_projections)`;
`parse_fomc_calendar` and `fetch_decision_dates` are kept as dates-only wrappers
so nothing else had to change.

**Daylight saving is the trap here.** 14:00 ET is 18:00 UTC under EDT and 19:00
UTC under EST, so the December meeting is an hour later in UTC than the September
one. Times go through `release_times.et_to_utc`, which converts via
`America/New_York`; no offset is ever hardcoded. Verified live: 16 Sep 2026 has
four rows at 18:00/18:30Z, 9 Dec 2026 has four at 19:00/19:30Z, and 28 Oct 2026
- not a projection meeting - correctly has three.

**FOUND WHILE DOING THIS: the FOMC fixture was not faithful.** It carried
asterisks on seven of eight 2026 meetings, because the parser only ever stripped
them and nothing checked. Once the asterisk became load-bearing that fixture
would have asserted the wrong answer. Corrected against the live page, and its
header now says the markers are load-bearing. The 2027 block stays partial and
synthetic - it exists to exercise the month-straddling rule - so the count test
is pinned to 2026, the one complete year.

## 2026-09-01 — One FRED release is several events, not one
Beyond the one-week ForexFactory window the calendar showed `PPI m/m` alone on
10 September and `CPI m/m` alone on 11 September. Missing: `Core CPI m/m` and
`CPI y/y` (both weight 5), `Core PPI m/m`, `Core Retail Sales m/m`,
`Unemployment Rate`, `Average Hourly Earnings m/m`. Inside the ForexFactory
window the same days looked complete, because that feed lists every line of a
release - so the gap only appeared where the skeleton was the sole source, which
is most of the calendar.
The cause: `FRED_RELEASE_TO_TITLE` mapped a release to exactly one title, chosen
as its headline print, and the skeleton created one row per release.
**Chosen:** `FRED_RELEASE_TO_TITLES` maps each release to the ordered tuple of
titles it publishes, headline first. `collect_schedule` now fetches each
release's dates **once** and fans them over every title, which is also one fewer
API call than the old title-by-title loop. `FRED_RELEASE_TO_TITLE` survives as a
derived headline-only view so existing callers were untouched.
Ids stay collision-free because `event_id` is `USD|<title>|<date>` and the
titles differ; the three CPI rows share a timestamp and have three distinct ids.
Re-checked live after the change: 181 events, **zero** duplicate `(date, title)`
pairs and zero duplicate ids, including where ff_sync had already written
`Unemployment Rate` and `Average Hourly Earnings m/m` for 4 September - those
merged onto the skeleton rows rather than doubling.
**`Core PPI m/m` had no FRED series**, so it would have sat on the calendar
permanently blank. Added `PPIFES` (Final Demand less foods and energy), verified
live against the API and from the same "Final Demand" family as the `PPIFIS`
already used for the headline. A test now asserts every fanned-out title either
has a series spec or a recorded reason it cannot.
Verified: 26 actuals filled for the new titles, each from its own series, and
Core CPI for the 12 Aug release cross-checks exactly against `CPILFESL`
(+0.2154, July over June - the reference-month rule holding for the new rows).

## 2026-09-01 — Calendar UI: the grid, not the sidebar, is the page
Every symptom had the same root: the month grid was being asked to fit full feed
titles into roughly 90px, inside 1100px of page, next to a 320px panel that was
empty until something was clicked.
**Chosen, in order of how much each fixed:**
- **`short_title` on `event_weights`** (`sql/002_short_title.sql`), nullable, with
  the full title as the fallback. "Non-Farm Employment Change" -> "NFP",
  "Core PCE Price Index m/m" -> "Core PCE", "FOMC Economic Projections" ->
  "Dot Plot". Read by `repo.fetch_short_titles`, which returns `{}` rather than
  raising if the migration has not been applied, so the calendar degrades to
  full titles instead of breaking.
- **Weight-1 hidden by default**, with a remembered toggle. They outnumber the
  rows that move gold about four to one; 1 September went from ten rows to two.
- **`dayMaxEvents: 5` plus `eventOrder: '-weight,start,title'`.** Ordering
  chronologically is the obvious choice and it was wrong here: on 16 September it
  put Retail Sales above the FOMC statement and pushed two weight-5 rows into
  "+2 more" - precisely the "low-value rows crowd out the ones that matter"
  complaint. Heaviest first, chronological within a weight; the time is on every
  chip so the day still reads.
- **The detail panel moved below the grid** and is `hidden` until an event is
  clicked, and `main.wide` takes the calendar to 1500px.
- **Chips are neutral, colour lives in the dot.** FullCalendar applies the feed's
  `backgroundColor` as an *inline* style, so this needs `!important`. A solid
  colour block per event made the month shout, and left grey time text on a grey
  chip. Weight 5 and 4 are also bold, and the legend now says what a weight
  means in words.
- **`listMonth` below 700px**, where a seven-column grid is unreadable.
- Detail panel shows UTC and local side by side - the left cell is the raw
  instant, the right a `data-utc` stamp tz.js fills. The server still formats no
  local time. The Stage 3 "Historical reaction" slot is untouched.
`short_title_for` falls back through `titles.resolve_alias` exactly as
`weight_for` does, so the per-speaker feed titles ("FOMC Member Waller Speaks")
that are not in `event_weights` still pick up the seeded short form.

**BLOCKED, needs the owner: `sql/002_short_title.sql` has not been applied.**
`DATABASE_URL` is not set - the first line of `.env` is a mangled comment
(`####ConnectionStringdb...`) rather than an assignment - and the connection
string inside it points at `db.<ref>.supabase.co`, which now resolves **IPv6
only**; this machine has no IPv6 route, so `psycopg` times out. Same constraint
that made `001` a paste-into-the-SQL-editor job. Verified the rendering by
serving the app with the migration's 27 values injected: every title fits.
Until it is applied the calendar shows full titles, ellipsised with the full
text on hover.

## 2026-09-01 — "+1 more" on 16 September hides Retail Sales m/m, and that is correct
Checked against the database, in the exact order the calendar sorts
(`eventOrder: '-weight,start,title'`, `dayMaxEvents: 5`):

| # | Weight | Time | Title | |
|---|---|---|---|---|
| 1 | 5 | 18:00Z | FOMC Economic Projections | visible |
| 2 | 5 | 18:00Z | FOMC Statement | visible |
| 3 | 5 | 18:00Z | Federal Funds Rate | visible |
| 4 | 5 | 18:30Z | FOMC Press Conference | visible |
| 5 | 3 | 12:30Z | Core Retail Sales m/m | visible |
| 6 | 3 | 12:30Z | Retail Sales m/m | **hidden** |

No weight-4 or weight-5 event is collapsed, and none can be while a lower-weight
one is shown: sorting by weight descending means the events pushed into
"+N more" are always the lightest on that day. That is the guarantee, and it
lives entirely in the `eventOrder` line - which is why there is now a test
asserting it starts with `-weight`.
Swept all 71 days that carry events: the most weight>=4 events on any single day
is **4**, against a cap of 5. The only way a weight-5 could ever be collapsed is
a day carrying more than five weight-5 events - a Fed decision day (4) coinciding
with a CPI release (3) would do it. That is not "low-value rows crowding out the
ones that matter", it is a genuinely overloaded day, and "+N more" still exposes
them. Left alone rather than special-cased.

## 2026-09-01 — Minimum-weight dropdown, filtered in the browser
The "show low-impact" checkbox hid weight 1 **on load**, so a first-time visitor
saw a calendar that was quietly missing rows. Replaced with a `Show:` dropdown -
5 only / 4 and above / 3 and above / 2 and above / 1 and above (everything) -
defaulting to **everything**. Nothing is hidden unless the reader asks.
The choice persists in `localStorage` under `xau.minWeight`; the old
`xau.showLowImpact` key is deleted on load so a stale boolean cannot linger with
no meaning. A first-time visitor with no stored value always gets everything.

**Filtering is client-side, and `/api/events` stays unfiltered.** Reasons, in
order of weight:
1. The badge has to say how many rows are being held back, which needs the
   unfiltered total for the visible range. Server-side filtering would need a
   second request or a count header to say the same thing.
2. Changing the filter is then instant and needs no round trip.
3. `/api/events` stays a plain representation of the data rather than one that
   varies with a piece of view state, which keeps it cacheable and keeps the
   tests describing data rather than UI.
A month is tens of rows, so there is nothing to gain by moving the work.
Because the filter runs inside the feed callback, month, week and list views all
inherit it without knowing it exists.

**BUG FOUND WHILE TESTING: the hidden count went stale on a view change.**
It was computed inside the fetch callback, but FullCalendar reuses cached events
when the new range sits inside the fetched one - switching month -> week does not
re-run the callback, so the badge kept reporting the month's number (37 hidden
against a week holding 26). Moved to an `updateBadge()` driven by `datesSet`,
which fires on every render, navigation and view change, and counts against the
range actually on screen. Verified over CDP: first visit shows 48 events and no
badge; 5/4/3/2/1 give 39/37/23/23/0 hidden; the choice survives a reload; and
week and list recompute their own counts.

## 2026-09-01 — Weights that were defaulting to 1
`titles.DEFAULT_WEIGHT` is 1, so any ForexFactory title without an
`event_weights` row lands at the bottom of the scale. That put the Beige Book
and the ADP payrolls preview next to the API oil bulletin, which is the real
reason a "hide weight 1" filter felt wrong: it was hiding useful releases along
with the noise. `sql/003_more_weights.sql` seeds 13 of them.

**One of the owner's titles did not exist.** The feed publishes
`Challenger Job Cuts y/y`, not `Challenger Job Cuts`; seeding the shorter form
would have matched nothing and left the row at weight 1 with no error anywhere -
the same silent-miss shape as the earlier bugs. Seeded under the real title. The
other twelve matched exactly, checked against the distinct titles in `events`.

**Four titles left unweighted on purpose**, because inventing weights for rows
the owner has not seen is how a scale stops meaning anything:
`API Weekly Statistical Bulletin`, `ISM Manufacturing Prices`,
`Omdia Total Vehicle Sales`, `RCM/TIPP Economic Optimism`. All four appear once,
on 1 September, and all default to 1.

**The survey is a snapshot, not a complete list.** ForexFactory publishes one
week at a time, so the only unweighted titles visible are the ones in the window
currently loaded. New ones will keep arriving; the query worth re-running is
"distinct `events.title` with no `event_weights` row, after alias resolution".
