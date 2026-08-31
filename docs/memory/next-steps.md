# Next steps

Updated at the end of every step. Newest plan replaces the old one.

## Owner actions first — nothing below works without these

1. **Apply the schema.** Paste `sql/001_init.sql` into the Supabase SQL editor and
   run it. It is idempotent. This creates five tables and seeds 27 gold weights.
2. **Fill in `.env`.** Copy `.env.example` and supply all five variables. The file
   at the repo root is currently empty.
3. **Give this machine push rights**, then `git push -u origin main`. See the
   blocked-push entry in `decisions.md` for the three options. Then add the same
   five values as repository secrets (Settings -> Secrets and variables ->
   Actions) so the workflows can run.

## The first three things to do next session

1. **Run the fetchers against the live database, in this order, and read the
   logs.** `python -m fetchers.calendar_skeleton --dry-run` first, then without
   the flag, then `ff_sync`, then `prices_daily --backfill-years 10`, then
   `fred_actuals`. The dry-run flags exist for exactly this.
2. **Fix the FRED series ids that turn out to be wrong.** `series_map.py` is the
   least-verified part of the build: the ids were chosen from knowledge of FRED,
   not confirmed against it. A wrong id logs `no usable observation yet` and
   skips the event, so work through `fred_actuals` output and correct
   `SERIES_MAP` until every mapped title resolves. `PPIFIS`, `RSFSXMV`,
   `CES0500000003` and `EXHOSLUSM495S` are the ones to check first.
3. **Confirm the skeleton and the feed really do collide on one id.** After
   running both fetchers, check that no release appears twice for the same day:
   `select ts_utc::date, title, count(*) from events group by 1,2 having count(*) > 1;`
   The id scheme is designed to prevent it and there is a test for it, but it has
   never been exercised against real FRED release names.

## After that
- Send one real Telegram message (`python -m fetchers.notify "test"`) and confirm
  `notifications_log.ok` is true.
- Watch one `reminders` run fire a real 24h reminder, and check the flag flips.
- Then Stage 2: the RSS headline pipeline and the Claude Haiku classifier. The
  `headlines` table already exists as a stub and the extension points are marked
  `# STAGE 2:`.
