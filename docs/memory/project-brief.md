# Project brief

## Goal
Give a gold trader the newest market-moving news for XAU/USD, tell them how much
each item matters, and lay the data foundation for later learning what gold
typically does after each kind of release. The platform informs; it never trades.

Owner: Michael Moussa. Concept doc: `docs/gold-news-platform.md` (dated 31 Aug 2026).

## Why gold first
Gold is driven by a short list of macro inputs — US inflation, Fed rate
expectations, the dollar, real yields, geopolitical fear — and most of those
arrive as scheduled, numeric releases on known dates. That makes it the cleanest
instrument for measuring "news in, price reaction out".

## Scope of this slice (Slice 1 = Stage 1 data layer + first two pages)
Steps 1-10 of the Stage 1 build table:

1. Project skeleton
2. Supabase schema
3. Annual calendar skeleton — fixed release dates for the next 12 months
4. Weekly forecast sync from ForexFactory, with diff logic
5. Telegram notifications — NEW / CHANGED / 24h / 1h reminders
6. Actuals fetcher from FRED
7. Daily gold and macro prices, with 10-year backfill
8. GitHub Actions workflows scheduling the fetchers
9. Web page: "Today / This week"
10. Web page: Calendar, colour-by-weight, event detail panel

## Explicitly out of scope in this slice
- Headlines / RSS ingestion (Kitco, Reuters, MarketWatch, CNBC)
- Stage 2 LLM classification of headlines (Claude Haiku, category + impact score)
- Stage 3 event study: intraday Dukascopy data, reaction windows, distributions
- Positioning data (CFTC COT, CME open interest, GLD/IAU holdings)
- Deployment to Render / Cloudflare
- Auth, CSS frameworks, Docker

Extension points for the above are left in place and marked `# STAGE 2:` or
`# STAGE 3:` in the code — notably the `headlines` table stub and the empty
"Historical reaction" section in the event detail panel.

## Definition of done for the slice
- `pytest` green, no network access in tests
- `python -m fetchers.ff_sync` runs end to end against the live Supabase
- `uvicorn web.app:app` serves `/` and `/calendar`
- All memory files accurate as of the last commit

**Met on 2026-09-01**, with one carve-out: Telegram has never delivered a real
message, because no credentials were supplied. Step 5 is therefore tested but not
verified live, and it is the first item in `next-steps.md`. Everything else in
the slice has been run against the live service it depends on.
