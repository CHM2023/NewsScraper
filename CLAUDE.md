# CLAUDE.md — operating instructions

## What this is
A Gold/USD (XAU/USD) market news platform. Scheduled US macro releases are fetched
into Supabase, weighted by how much they matter to gold, diffed for changes, pushed
to Telegram, and served as two pages (today/this week, month calendar).
Full concept: `docs/gold-news-platform.md`. This repo currently implements
**Slice 1** = Stage 1 data layer + first two pages. Steps 1-10, see
`docs/memory/progress.md`.

## Read these first, in order
1. `docs/memory/project-brief.md` — goal, scope, what is explicitly out of scope
2. `docs/memory/architecture.md` — folder layout, data flow, env vars, workarounds
3. `docs/memory/progress.md` — what is done, verified, and still broken
4. `docs/memory/next-steps.md` — what to do first
5. `docs/memory/decisions.md` — append-only; why things are the way they are

## Run it
```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env                                # fill in 5 vars
python -m fetchers.<name>                           # any fetcher, idempotent
uvicorn web.app:app --reload
pytest -q                                           # must stay green, no network
```

## Conventions — do not break these
- **UTC everywhere.** Every datetime crossing a boundary is timezone-aware and
  serialised ISO-8601 with an offset. `common/timeutil.py` raises on naive
  datetimes; use it rather than `datetime.utcnow()` (which is naive and banned —
  a test asserts this).
- **Local time is a browser concern.** Templates emit `data-utc="..."`;
  `web/static/js/tz.js` converts. No server-side timezone conversion, ever.
- **Fetchers**: one module per source under `fetchers/`, each with `main()`,
  runnable as `python -m fetchers.<name>`, idempotent, upserting not inserting.
  Each logs rows fetched / inserted / updated / skipped.
- **Only `db/` talks to Supabase.** Fetchers call `db.repo`, never the client.
- **Pure logic is separated from I/O** so it can be tested without network:
  parsing, diff, surprise, regime and blackout live in their own modules and are
  tested against fixtures in `tests/fixtures/`. No test may hit the network.
- **Config from env only**, via `common/config.py`. Fail fast with a clear
  message naming the missing variable. Never read `os.environ` directly.
- **Logging via `logging`**, never `print`.
- Wrap every external call in try/except with a timeout. One bad row must never
  stop a batch — log it, skip it, count it.

## Git
- Branch `main`, remote `origin` = `git@github.com:CHM2023/NewsScraper.git`.
- Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`) with a scope,
  e.g. `feat(calendar): ForexFactory weekly sync with diff and upsert`.
- **Never commit `.env` or any key.** `.env.example` carries the variable names.
- Every behaviour change updates the relevant memory file *in the same commit*.
- Update `progress.md` + `next-steps.md` at the end of every step; append to
  `decisions.md` the moment a decision is made.
- Run `pytest` before the final commit of a session.

## Out of scope in this slice
Headlines/RSS, LLM classification (Stage 2), the event study (Stage 3),
deployment to Render, auth, CSS frameworks, Docker. Extension points are marked
with `# STAGE 2:` / `# STAGE 3:` comments — leave them.
