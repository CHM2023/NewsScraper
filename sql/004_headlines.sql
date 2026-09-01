-- ---------------------------------------------------------------------------
-- 004: make the headlines stub usable by the RSS pipeline.
--
-- 001 created the table as a Stage 2 placeholder. The collector needs two more
-- things:
--   * title_norm - the title lowercased and stripped of punctuation, so the
--     same story carried by two feeds under slightly different wording is
--     recognised as one. Deduplicating on url alone does not catch it: every
--     feed links to its own copy.
--   * a unique index on url, so a re-run of the same feed updates rather than
--     inserts. The primary key is a hash of the url, which covers the same
--     ground, but the index makes the intent explicit and the lookup fast.
--
-- category, score and classified_at stay nullable and unwritten. They are the
-- Stage 2 slots for the Claude Haiku classifier.
--
-- Idempotent. Safe to run more than once.
-- ---------------------------------------------------------------------------
alter table headlines add column if not exists title_norm text;
alter table headlines add column if not exists fetched_at timestamptz not null default now();

create unique index if not exists headlines_url_idx on headlines (url) where url is not null;
create index if not exists headlines_title_norm_idx on headlines (title_norm);
create index if not exists headlines_source_ts_idx on headlines (source, ts_utc desc);
