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
