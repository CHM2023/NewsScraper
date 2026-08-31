# Gold/USD Market News Platform

Scheduled US macro releases that move XAU/USD — collected, weighted, diffed and
served as a "today / this week" page and a month calendar. Slice 1 (Stage 1 data
layer + first two pages). Full concept: [docs/gold-news-platform.md](docs/gold-news-platform.md).

## Quickstart

```bash
python -m venv .venv && . .venv/Scripts/activate   # Linux/mac: . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                               # then fill in the five variables
# Run sql/001_init.sql once in the Supabase SQL editor (see docs/memory/decisions.md)
python -m fetchers.calendar_skeleton                # 12 months of release dates
python -m fetchers.ff_sync                          # this week's forecasts + diff
python -m fetchers.prices_daily --backfill-years 10 # one-off history load
uvicorn web.app:app --reload                        # http://127.0.0.1:8000
pytest -q                                           # no network required
```

Every fetcher takes `--dry-run`, which fetches and reports without writing.

Everything is stored in UTC; conversion to local time happens in the browser only.
Operating instructions for future sessions live in [CLAUDE.md](CLAUDE.md) and
[docs/memory/](docs/memory/) — start with
[next-steps.md](docs/memory/next-steps.md).
