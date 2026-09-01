# Next steps

Updated at the end of every step. Newest plan replaces the old one.

Slice 1 is complete and verified live, with one exception: Telegram has never
delivered a message. Everything below assumes `main` at 8bde217 or later, the
schema applied, and the three repository secrets set.

## 0. Two owner actions, both one paste each

1. **Apply `sql/002_short_title.sql`** in the Supabase SQL editor. It adds
   `event_weights.short_title` and seeds 27 abbreviations, and it is idempotent.
   Until it runs the calendar falls back to full titles, which ellipsise in the
   month grid. It could not be applied from here: `DATABASE_URL` is unset and
   `db.<ref>.supabase.co` resolves IPv6-only, which this machine cannot route.
2. **Fix the first line of `.env`**, which is currently the mangled comment
   `####ConnectionStringdb postgresql://...` rather than an assignment. It
   should read `DATABASE_URL=postgresql://...`, and is worth pointing at the
   **session pooler** host rather than the direct one so it works over IPv4.
   With that set, `python -m scripts.apply_schema sql/002_short_title.sql`
   applies migrations without the SQL editor. That script has still never run.

## 1. Telegram: verify live

The only part of the slice that has never touched the real service. It is one
setting away from working, and until it does the platform can compute a NEW /
CHANGED alert perfectly and tell nobody.

1. Create a bot with @BotFather, send it one message, and read the numeric chat
   id from `https://api.telegram.org/bot<TOKEN>/getUpdates`.
2. Put both values in `.env` as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Send a real message: `python -m fetchers.notify "test"`. Then confirm the row
   landed and the send actually succeeded:
   `select ts_utc, ok, error from notifications_log order by ts_utc desc limit 5;`
   `ok` must be **true**. A false with an error string means the token or chat id
   is wrong; a missing row means `notify` was never reached.
4. Add the same two values as repository secrets:
   `gh secret set TELEGRAM_BOT_TOKEN --repo CHM2023/NewsScraper` (pipe the value
   over stdin, never `--body`, so it stays out of the shell history).
5. Watch one reminder fire for real. The next weight >= 4 event is Non-Farm
   Employment Change on **2026-09-04 12:30Z**, so the 24h reminder is due around
   2026-09-03 12:30Z and the 1h around 2026-09-04 11:30Z. Dispatch
   `reminders.yml` in that window and confirm the log says it *flagged* the event
   rather than `flagged none`, then check `reminded_24h` / `reminded_1h` flipped
   and that a second dispatch sends nothing.

Watch for the ordering trap: `reminders` deliberately does **not** flip a flag
when Telegram is unconfigured, so no reminder is lost while the credentials are
missing. That behaviour was confirmed live in run 33504544368. Once the secrets
are set, the backlog of due reminders becomes deliverable - check how many are
pending before the first run so a burst is expected rather than alarming.

## 2. Slice 2: RSS headlines + Stage 2 classification

Start with ingestion, not the LLM. A classifier with nothing to classify is
untestable, and the headline pipeline is the part that can be verified against
reality.

1. **`fetchers/rss_sync.py`**, modelled on `ff_sync`: one module, `main()`,
   idempotent, upserting into the existing `headlines` stub. Sources from the
   concept doc are Kitco, Reuters, MarketWatch and CNBC. Deduplicate on URL, and
   expect the same class of bug the last session found five times - check that a
   "successful" run with `errors=0` actually stored distinct, current rows.
2. **Confirm the `headlines` table matches what the feeds supply** before writing
   the classifier. The stub was designed without a real feed in front of it.
3. **Then the Claude Haiku classifier**: category + impact score, at the points
   already marked `# STAGE 2:`. Keep it behind the same pure/IO split as the rest
   - the prompt and the parsing of its response belong in a pure module tested
   against captured fixtures, so the suite stays offline.
4. **Rate limits and cost**: classify once per headline and store the result;
   never re-classify on page load.

## Also worth doing early in Slice 2
- **A gold coverage check in `prices_daily`** that fails the run when `xau_close`
  is missing for too many of the last 30 weekdays. Gold now has a single upstream
  source and it has already gone null once with `errors=0`.
- **Link the event detail panel from the today table**, not just the calendar.
- **Pin the workflow actions**: `actions/checkout@v4` and `setup-python@v5` now
  warn that Node 20 is deprecated and are being forced onto Node 24.
