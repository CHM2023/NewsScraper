"""Data fetchers. One module per source, each runnable as python -m fetchers.<name>.

Every fetcher is idempotent, upserts rather than inserts, wraps its external
calls in try/except with a timeout, and logs rows fetched/inserted/updated/
skipped on the way out. None of them import the Supabase client directly; they
all go through db.repo.
"""
