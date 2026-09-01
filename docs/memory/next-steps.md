# Next steps

Updated at the end of every step. Newest plan replaces the old one.

Stage 1 is code-complete. `docs/memory/progress.md` carries the component-level
completion table; this is the order to work in.

## 1. Apply the outstanding migrations

Four files, in order, in the Supabase SQL editor. All are idempotent, and
nothing below works properly until they are in.

| File | What it adds | What is broken without it |
|---|---|---|
| `sql/002_short_title.sql` | `event_weights.short_title` + 27 abbreviations | Calendar titles ellipsise |
| `sql/003_more_weights.sql` | 13 releases weighted (Beige Book and ADP at 3) | Those 13 sit at weight 1 |
| `sql/004_headlines.sql` | `headlines.title_norm`, `fetched_at`, indexes | **The headlines fetcher stores nothing** - it reports `errors=1` naming this file |

`sql/001_init.sql` is already applied.

**Fix `DATABASE_URL` while you are there.** The first line of `.env` is a
mangled comment (`####ConnectionStringdb postgresql://...`) rather than an
assignment, so the variable is unset. Point it at the **session pooler** host,
not `db.<ref>.supabase.co`, which resolves IPv6-only and cannot be reached from
this machine. With it set, `python -m scripts.apply_schema sql/00N_*.sql`
applies migrations without the editor - that script has still never run.

## 2. Telegram: verify live

The only Stage 1 component that has never done its job. Everything computes
correctly and delivers nothing.

1. Create a bot with @BotFather, message it, and read the numeric chat id from
   `https://api.telegram.org/bot<TOKEN>/getUpdates`.
2. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.
3. `python -m fetchers.notify "test"`, then confirm delivery landed:
   `select ts_utc, ok, error from notifications_log order by ts_utc desc limit 5;`
   `ok` must be **true**.
4. Add both as repository secrets (pipe over stdin, never `--body`).
5. Watch one reminder fire. `reminders` deliberately does not flip
   `reminded_24h` / `reminded_1h` while Telegram is unset, so a backlog of due
   reminders is waiting - expect a burst on the first configured run, and check
   how many are pending first.
6. `/settings` will flip from "Telegram not configured" to configured on its
   own; it reads the token's presence.

## 3. Deploy: Render + Cloudflare

The web app is read-only and stateless, so this is mostly configuration.
- Render's free tier **sleeps after 15 minutes idle**, so the first request
  after a quiet period takes ~30 seconds. Nothing schedules itself inside the
  app - the fetchers are all in Actions - so sleeping costs freshness of the
  page only, not of the data.
- Set the same secrets as the workflows. `DATABASE_URL` is not needed: the app
  never runs DDL.
- Cloudflare in front for TLS and caching. Cache the static assets; **do not**
  cache `/api/events` or `/partials/today`, which is where freshness lives.
- Check `/health` reports `database: ok` from the deployed host - a Supabase
  network policy that allows this machine may not allow Render's egress.

## 4. Stage 2: classification

The headlines are already flowing and `category`/`score` are waiting.
1. **Classify with Claude Haiku** at the points marked `# STAGE 2:`. Keep the
   prompt and the response parsing in a pure module tested against captured
   fixtures, so the suite stays offline.
2. **Classify once per headline and store it.** Never on page load.
3. **Then the release importance scoring** of concept doc 4.1-4.3, which can
   reuse the surprise score that already exists.

## Also worth doing, unscheduled

- **Map the releases FRED can actually answer.** JOLTS (`JTSJOL`), Construction
  Spending (`TTLCONS`) and Trade Balance (`BOPGSTB`) are real series missing from
  `SERIES_MAP`, so those events can never get an actual.
- **Decide weights for four titles** left unweighted on purpose:
  `API Weekly Statistical Bulletin`, `ISM Manufacturing Prices`,
  `Omdia Total Vehicle Sales`, `RCM/TIPP Economic Optimism`.
- **A gold coverage check in `prices_daily`** that fails the run when
  `xau_close` is missing for too many recent weekdays. Gold has one upstream
  source and it has gone null silently once already.
- **Measure the actuals lag** on the first mappable release - Unemployment
  Claims, Thursday 2026-09-03 12:30Z. The query is in `progress.md`.
- **Pin the workflow actions**: `actions/checkout@v4` and `setup-python@v5` warn
  that Node 20 is deprecated.

## Deferred by decision, not forgotten

**Dukascopy intraday gold** (concept doc 3.2) is deferred to **Stage 3** by the
owner, 2026-09-01. Its only consumer is the event study: nothing in Stage 1
reads a tick, and the daily close is what the regime tagging and the calendar
need. It moves back into scope when section 5.2's data requirements do.
