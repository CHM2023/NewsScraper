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
