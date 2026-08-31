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
