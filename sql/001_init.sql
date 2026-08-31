-- 001_init.sql — Gold/USD news platform, Slice 1 schema.
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query).
-- Idempotent: safe to re-run.

-- ---------------------------------------------------------------------------
-- event_weights: how much each release matters to gold. Editable without a
-- redeploy; fetchers read it on every run.
-- ---------------------------------------------------------------------------
create table if not exists event_weights (
    title      text primary key,
    weight     smallint    not null check (weight between 1 and 5),
    note       text,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- events: one scheduled release. id = 'USD|<title>|<YYYY-MM-DD>' (UTC date).
-- Written by calendar_skeleton (dates only, 12 months out) and ff_sync
-- (forecast/previous, 2 weeks out); enriched by fred_actuals and prices_daily.
-- ---------------------------------------------------------------------------
create table if not exists events (
    id           text        primary key,
    title        text        not null,
    country      text        not null default 'USD',
    ts_utc       timestamptz not null,
    impact       text,
    weight       smallint    not null default 1 check (weight between 1 and 5),
    forecast     double precision,
    previous     double precision,
    actual       double precision,
    surprise     double precision check (surprise between -3 and 3),
    regime       text        check (regime in ('hiking', 'holding', 'cutting')),
    source       text        not null default 'skeleton'
                             check (source in ('skeleton', 'forexfactory')),
    reminded_24h boolean     not null default false,
    reminded_1h  boolean     not null default false,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists events_ts_utc_idx        on events (ts_utc);
create index if not exists events_weight_ts_idx     on events (weight desc, ts_utc);
-- Supports fred_actuals' "recent releases still missing an actual" scan.
create index if not exists events_missing_actual_idx on events (ts_utc)
    where actual is null;

-- ---------------------------------------------------------------------------
-- prices_daily: one row per calendar date. Gold plus the three macro drivers.
-- ---------------------------------------------------------------------------
create table if not exists prices_daily (
    date           date primary key,
    xau_close      double precision,
    dxy            double precision,
    real_yield_10y double precision,
    fed_funds      double precision,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- notifications_log: every message we tried to send, delivered or not.
-- ---------------------------------------------------------------------------
create table if not exists notifications_log (
    id       bigint generated always as identity primary key,
    ts_utc   timestamptz not null default now(),
    channel  text        not null,
    message  text        not null,
    event_id text,
    ok       boolean     not null default true
);

create index if not exists notifications_log_ts_idx on notifications_log (ts_utc desc);

-- ---------------------------------------------------------------------------
-- STAGE 2: headlines. Stub only — nothing writes to this in Slice 1. The RSS
-- pipeline fills id/source/ts_utc/title/url; the Claude Haiku classifier fills
-- category/score/classified_at.
-- ---------------------------------------------------------------------------
create table if not exists headlines (
    id            text        primary key,
    source        text        not null,
    ts_utc        timestamptz not null,
    title         text        not null,
    url           text,
    category      text,   -- rates | inflation | usd | geopolitics | demand | noise
    score         smallint    check (score between -3 and 3),
    classified_at timestamptz,
    created_at    timestamptz not null default now()
);

create index if not exists headlines_ts_idx on headlines (ts_utc desc);

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------
create or replace function set_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists events_set_updated_at on events;
create trigger events_set_updated_at before update on events
    for each row execute function set_updated_at();

drop trigger if exists prices_daily_set_updated_at on prices_daily;
create trigger prices_daily_set_updated_at before update on prices_daily
    for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- Row level security: every writer uses the service_role key, which bypasses
-- RLS. Enabling it with no policies denies anon/authenticated clients entirely.
-- ---------------------------------------------------------------------------
alter table event_weights     enable row level security;
alter table events            enable row level security;
alter table prices_daily      enable row level security;
alter table notifications_log enable row level security;
alter table headlines         enable row level security;

-- ---------------------------------------------------------------------------
-- Seed: gold-specific importance weights (concept doc section 3.3).
--   5 = FOMC decision / press conference, CPI, Core PCE
--   4 = Non-farm payrolls, Fed chair testimony, Jackson Hole
--   3 = PPI, ISM, retail sales
--   1 = jobless claims, housing data
-- Titles are ForexFactory's, because that is the feed the trader sees; matching
-- in code is case-insensitive with an alias table (fetchers/titles.py).
-- Re-running updates weights but keeps any row the owner added by hand.
-- ---------------------------------------------------------------------------
insert into event_weights (title, weight, note) values
    -- Fed decisions and communication
    ('FOMC Statement',                5, 'Rate decision; the single biggest gold driver'),
    ('Federal Funds Rate',            5, 'Published alongside the FOMC statement'),
    ('FOMC Press Conference',         5, 'Chair Q&A, often moves more than the statement'),
    ('FOMC Economic Projections',     5, 'Dot plot; quarterly'),
    ('FOMC Meeting Minutes',          4, 'Three weeks after each meeting'),
    ('FOMC Member Speaks',            3, 'Non-chair speakers; occasionally material'),

    -- Inflation
    ('CPI m/m',                       5, 'Headline inflation, the classic gold trigger'),
    ('CPI y/y',                       5, 'Released with CPI m/m'),
    ('Core CPI m/m',                  5, 'The number the Fed actually watches'),
    ('Core PCE Price Index m/m',      5, 'The Fed''s preferred inflation gauge'),

    -- Labour. Only Non-Farm Employment Change is weight 4: the other two land on
    -- the same timestamp, and three weight-4 rows would fire three reminders for
    -- one release.
    ('Non-Farm Employment Change',    4, 'Employment Situation headline print'),
    ('Unemployment Rate',             3, 'Same release and timestamp as NFP'),
    ('Average Hourly Earnings m/m',   3, 'Same release and timestamp as NFP'),

    -- Fed chair set pieces
    ('Fed Chair Testifies',           4, 'Semi-annual monetary policy testimony'),
    ('Fed Chair Speaks',              4, 'Includes Jackson Hole keynote'),
    ('Jackson Hole Symposium',        4, 'Late August, multi-day'),

    -- Second tier
    ('PPI m/m',                       3, 'Pipeline inflation'),
    ('Core PPI m/m',                  3, null),
    ('ISM Manufacturing PMI',         3, null),
    ('ISM Services PMI',              3, null),
    ('Retail Sales m/m',              3, 'Consumer demand, feeds growth expectations'),
    ('Core Retail Sales m/m',         3, null),

    -- Background
    ('Unemployment Claims',           1, 'Weekly; rarely moves gold on its own'),
    ('Building Permits',              1, null),
    ('Housing Starts',                1, null),
    ('Existing Home Sales',           1, null),
    ('New Home Sales',                1, null)
on conflict (title) do update
    set weight = excluded.weight,
        note   = excluded.note;
