-- ---------------------------------------------------------------------------
-- 003: weights for releases that were defaulting to 1.
--
-- Any ForexFactory title with no event_weights row falls back to
-- titles.DEFAULT_WEIGHT = 1, which put genuinely useful releases at the bottom
-- of the scale - the Beige Book and the ADP payrolls preview were sitting
-- alongside the API oil bulletin. That is what made a "hide weight 1" filter
-- look like it was hiding junk when it was also hiding those two.
--
-- Run 002_short_title.sql first. The column guard below means this file will
-- not fail if you have not, but the 27 rows seeded in 002 would then still
-- have no short title.
--
-- Idempotent, like 001 and 002. Safe to run more than once.
-- ---------------------------------------------------------------------------
alter table event_weights add column if not exists short_title text;

insert into event_weights (title, weight, short_title, note) values
    -- Fed publications and payroll previews: these move gold.
    ('Beige Book',                     3, 'Beige Book',     'Fed publication, two weeks before each FOMC'),
    ('ADP Non-Farm Employment Change', 3, 'ADP',            'Payrolls preview; moves gold ahead of NFP'),

    -- Second-order but genuinely read.
    ('JOLTS Job Openings',             2, 'JOLTS',          'Labour demand; the Fed cites it'),
    ('Trade Balance',                  2, 'Trade Balance',  'Feeds the dollar rather than gold directly'),

    -- Background. Listed explicitly so they are weighted by decision, not by
    -- the default falling through.
    ('Factory Orders m/m',             1, 'Factory Orders', null),
    ('Construction Spending m/m',      1, 'Construction',   null),
    ('Crude Oil Inventories',          1, 'Crude Oil',      'Energy, not gold'),
    ('Natural Gas Storage',            1, 'Nat Gas',        'Energy, not gold'),
    -- The feed publishes this as "Challenger Job Cuts y/y", not
    -- "Challenger Job Cuts" - seeding the shorter form would match nothing.
    ('Challenger Job Cuts y/y',        1, 'Job Cuts',       null),
    ('Final Manufacturing PMI',        1, 'Final Mfg PMI',  'Revision of a number already released'),
    ('Final Services PMI',             1, 'Final Svcs PMI', 'Revision of a number already released'),
    ('Revised Nonfarm Productivity q/q', 1, 'Productivity', 'Revision, quarterly'),
    ('Revised Unit Labor Costs q/q',   1, 'Labor Costs',    'Revision, quarterly')
on conflict (title) do update
    set weight      = excluded.weight,
        short_title = excluded.short_title,
        note        = excluded.note;
