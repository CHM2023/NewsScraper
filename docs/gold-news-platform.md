# Gold/USD Market News Platform — Project Concept

**Owner:** Michael Moussa
**Date:** 31 August 2026
**Status:** Concept — pre-build

---

## 1. Purpose

A web application that gives a trader the newest market-moving news for Gold/USD (XAU/USD), tells them how important each item is, and — over time — learns from ten years of history how gold typically reacts to each kind of news so the trader knows what to expect before it happens.

The platform informs; it does not trade. That keeps the first version free of execution risk and builds the data foundation that any future trading bot would need anyway.

**Why Gold/USD first.** Gold is driven by a short list of macro inputs — US inflation, Fed rate expectations, the US dollar, real yields and geopolitical fear. Most of these arrive as scheduled, numeric releases with known dates. That makes gold one of the cleanest instruments for measuring "news in, price reaction out."

---

## 2. Delivery model

| Layer | Choice | Cost |
|---|---|---|
| Web app hosting | Render (free web service) | Free |
| Database | Supabase (Postgres, free tier, 500 MB) | Free |
| Domain, CDN, caching | Cloudflare | Free |
| Scheduled data fetching | GitHub Actions cron workflows (Python) | Free |
| Large historical files (tick data) | Supabase Storage or Cloudflare R2 as Parquet | Free tier |
| Notifications | Telegram bot first; email / browser push later | Free |
| Backend language | Python (FastAPI + HTMX templates) | Free |
| Calendar UI | FullCalendar.js | Free |
| LLM classification (Stage 2) | Anthropic API — Claude Haiku | Pay per use, cents/day |

Design note: Render's free service sleeps after 15 minutes of inactivity and its cron jobs are paid, so all fetching runs in GitHub Actions and writes straight to Supabase. Render only serves pages. Cloudflare caching hides most of the cold start.

Everything is stored in UTC and converted to the viewer's timezone in the browser.

---

## 3. Stage 1 — Newest news for the trader

### 3.1 Two kinds of news, two pipelines

**A. Scheduled data releases** (CPI, Core PCE, Non-farm payrolls, FOMC decisions, PPI, ISM, retail sales, jobless claims).

- Schedule: BLS release calendar, FOMC calendar (federalreserve.gov), BEA calendar, FRED `releases/dates` API. Published up to a year ahead.
- Forecast / consensus and impact flag: ForexFactory JSON feed (`ff_calendar_thisweek.json`, `ff_calendar_nextweek.json`).
- Actual results: FRED API (every US series gold cares about, with original release dates).
- These are structured, timestamped and clean. They are the only inputs Stage 3 can learn from properly.

**B. Unscheduled headlines** (Fed speeches, geopolitical events, central bank gold purchases, sanctions, tariff news).

- Live: RSS feeds from Kitco, Reuters Commodities, MarketWatch, CNBC Markets.
- History (10 years): GDELT (free), NewsAPI (free tier is 24-hour delayed — fine for backfill, not for live).
- Headlines only; no full-article scraping. Cheaper, faster, and avoids terms-of-service problems with Investing.com, Bloomberg and similar.

### 3.2 Price and market data

- Daily gold: FRED LBMA series, or `yfinance` (`GC=F`).
- Intraday / tick gold: Dukascopy free historical tick data for XAUUSD (10+ years). Needed because the initial reaction to a release often reverses by the daily close.
- US dollar index, 10-year real yield, Fed funds rate: FRED.

### 3.3 Calendar window and smart notifications

**Calendar view.** FullCalendar.js reading events from Supabase. Colour by gold-specific weight: red (5), orange (4), grey (≤3). Clicking an event shows previous value, forecast, and — once Stage 3 exists — "what gold did the last ten times."

**Gold-specific importance weights** (stored in the DB, editable without redeploying):

| Event | Weight |
|---|---|
| FOMC decision / press conference | 5 |
| CPI, Core PCE | 5 |
| Non-farm payrolls | 4 |
| Fed chair testimony, Jackson Hole | 4 |
| PPI, ISM, retail sales | 3 |
| Jobless claims, housing data | 1 |

**Notification triggers.** The fetcher runs hourly and diffs the feed against the database:

1. New event appeared that was not in the DB → "NEW: CPI scheduled 14 Oct 13:30 UTC (weight 5)".
2. A stored event's time or forecast changed → "CHANGED: …".
3. Reminders at 24 hours and 60 minutes before any event with weight ≥ 4.

Telegram is the first channel (free, instant, ten lines of code). Email and browser push are added once the app has users beyond the owner.

### 3.4 Stage 1 pages

1. **Today / This week** — upcoming events with weight, forecast, previous; latest headlines with source and time.
2. **Calendar** — month view with red-flagged dates.
3. **Event detail** — history of that release, forecast vs actual, placeholder for Stage 3 reaction panel.
4. **Settings** — notification channel, reminder lead times, timezone.

---

## 4. Stage 2 — Importance scoring (important / medium / useless)

### 4.1 Scheduled releases
Importance is already known. Use the weight table above. No machine learning required. Stage 3 later validates the weights by measuring actual gold moves after each event type and proposes adjustments.

### 4.2 Headlines
Use an LLM (Claude Haiku) only for unstructured headlines, and only to answer two narrow questions:

- **Category:** rates / inflation / USD / geopolitics / physical demand / noise.
- **Expected 24-hour impact on gold:** score from −3 (strongly negative) to +3 (strongly positive), 0 = none.

Output is strict JSON, one headline per call. Every classification is logged so accuracy can be checked later against what gold actually did. Headlines with |score| ≥ 2 are pushed to the trader as "important"; 1 as "medium"; 0 as "useless" (hidden by default).

### 4.3 Surprise score for releases
For each release with a forecast and an actual:

```
surprise = (actual − forecast) / |forecast|, scaled and clamped to −3 … +3
```

A release that lands on forecast has surprise ≈ 0 and is expected to move gold little, regardless of its weight. This distinction — direction vs surprise — is the core of Stage 3.

---

## 5. Stage 3 — Learn what to expect (event study)

### 5.1 The idea
For each historical release of a given type (e.g. CPI), measure gold's return in several windows after the release — first 5 minutes, first hour, end of day, next day — and tag the release by its surprise (above / in line / below expectations). Average the returns by tag and report the distribution and hit rate. The trader sees:

> "CPI above forecast: last 10 occurrences, gold fell in 7, average −0.6% in the first hour, average −0.2% by close."

This is a standard finance technique (event study), applied across ten years of history for every event type in the weight table.

### 5.2 Data required
- Ten years of release dates, forecast, actual (Section 3.1A). Consensus history is the hardest piece to get free; options are Trading Economics (limited free tier), Kaggle datasets of scraped ForexFactory history, or "actual vs previous" as a labelled proxy.
- Ten years of intraday gold (Dukascopy) aligned on the same UTC timeline.
- Fed funds rate and its recent direction (FRED) for every event date.

### 5.3 Three rules that make the results honest

1. **Condition on surprise, not direction.** CPI rising when everyone expected it to rise does nothing.
2. **Condition on regime.** Gold's reaction to the same news has flipped over the decade. In 2022, hot CPI meant faster Fed hikes and gold fell; in other years, hot CPI meant inflation fear and gold rose. Every event is tagged with the Fed regime (hiking / holding / cutting) and the UI lets the trader filter by it. Without this, Stage 3 gives confidently wrong answers.
3. **Show distributions, not averages.** Monthly CPI over ten years is ~120 events. Enough for a directional read, not for confident statistics. Display the hit rate and the range, never a single "gold goes up."

### 5.4 Beyond price: demand and supply proxies
Live order-book depth for gold is not available free and does not survive historically. Better free proxies, all with long history:

- **CFTC Commitments of Traders** (weekly) — how long or short speculators are.
- **CME gold futures open interest** — participation and crowding.
- **GLD / IAU ETF holdings** — physical investment demand.

These are stored alongside every event so the reaction panel can say "speculators were already at a 2-year long extreme when this CPI landed" — which changes what to expect.

### 5.5 Optional: retrieval layer
Once Stages 1–3 work, embed all historical headlines (Voyage AI or a local sentence-transformers model) into a vector store (ChromaDB / SQLite-vec) and expose it via an MCP server. Use: "find the 20 most similar past headlines and show what gold did in the following 24 hours." That output becomes context in the Stage 2 classification prompt, so the LLM reasons from precedent rather than guessing. This is the last layer, not the first.

---

## 6. Data model (Supabase)

| Table | Key columns |
|---|---|
| `event_weights` | title, weight |
| `events` | id, title, country, ts_utc, impact, weight, forecast, previous, actual, surprise, regime, reminded_24h, reminded_1h |
| `headlines` | id, source, ts_utc, title, category, score, classified_at |
| `prices_daily` | date, xau_close, dxy, real_yield_10y, fed_funds |
| `prices_intraday` | pointer to Parquet in storage; only event windows loaded into Postgres |
| `positioning` | date, cot_net_spec_long, cme_open_interest, gld_holdings |
| `reactions` | event_id, window (5m / 1h / 1d / next_day), return_pct |
| `notifications_log` | ts_utc, channel, message |

---

## 7. Roadmap

| Step | Deliverable | Effort |
|---|---|---|
| 1 | FRED + FOMC skeleton calendar, daily gold, Supabase schema, Telegram bot | 1 weekend |
| 2 | ForexFactory sync with diff + notifications, calendar page on Render + Cloudflare | 1 weekend |
| 3 | RSS headlines pipeline, Stage 2 LLM classification, "Today" page | 1–2 weekends |
| 4 | Backfill 10 years: releases (FRED), headlines (GDELT), intraday gold (Dukascopy) | 1–2 weekends |
| 5 | Stage 3 event study for CPI only; reaction panel in event detail | 1 weekend |
| 6 | Extend Stage 3 to all weighted event types; add regime and positioning filters | 2 weekends |
| 7 | Validate Stage 2 weights against Stage 3 results; adjust | Ongoing |
| 8 | Retrieval layer / MCP server | Optional |

First build this week: step 1. Scheduled releases only — no headlines, no LLM — with a page listing upcoming events and the last ten releases. Stage 3 for CPI then becomes a single SQL query on top of it.

---

## 8. Known risks

- **Consensus history is not free.** Budget for Trading Economics or accept the "vs previous" proxy and label it clearly in the UI.
- **Timezones.** Everything UTC on the server, converted in the browser. One Sydney/US daylight-saving bug will silently break the blackout and reminder logic.
- **Small samples.** ~120 CPI events in ten years. Show distributions; never present a single expected direction as fact.
- **Regime flips.** A reaction pattern that held 2015–2019 may not hold in a hiking cycle. Always show the regime filter.
- **Feed terms of service.** Check ForexFactory and RSS publishers' terms before relying on them; keep a swap-in plan (Trading Economics, GDELT).
- **Free-tier limits.** Supabase 500 MB fills fast with tick data — keep ticks in Parquet in object storage.
- **LLM output.** Wrap every JSON parse in try/except; log and skip failures; never let one bad response stop the loop.

---

*This document describes an information product for educational and research purposes. It is not financial advice.*
