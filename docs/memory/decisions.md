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
