-- ---------------------------------------------------------------------------
-- 002: short_title for event_weights.
--
-- The month calendar has roughly 90px of usable width per event. Full feed
-- titles ("Non-Farm Employment Change", "Core PCE Price Index m/m") were being
-- cut off mid-word by the cell, so a busy day read as a column of "12:30
-- Unempl". These are the abbreviations a trader would use out loud.
--
-- Nullable on purpose: a title with no short form falls back to the full one,
-- so a row added by hand later is never rendered blank.
--
-- Idempotent, like 001. Safe to run more than once.
-- ---------------------------------------------------------------------------
alter table event_weights add column if not exists short_title text;

update event_weights set short_title = v.short_title
from (values
    -- Fed decisions and communication
    ('FOMC Statement',                'Statement'),
    ('Federal Funds Rate',            'Fed Funds'),
    ('FOMC Press Conference',         'Presser'),
    ('FOMC Economic Projections',     'Dot Plot'),
    ('FOMC Meeting Minutes',          'Minutes'),
    ('FOMC Member Speaks',            'Fed Speak'),

    -- Inflation
    ('CPI m/m',                       'CPI m/m'),
    ('CPI y/y',                       'CPI y/y'),
    ('Core CPI m/m',                  'Core CPI'),
    ('Core PCE Price Index m/m',      'Core PCE'),
    ('PPI m/m',                       'PPI m/m'),
    ('Core PPI m/m',                  'Core PPI'),

    -- Labour
    ('Non-Farm Employment Change',    'NFP'),
    ('Unemployment Rate',             'U-Rate'),
    ('Average Hourly Earnings m/m',   'Avg Earnings'),
    ('Unemployment Claims',           'Claims'),

    -- Fed chair set pieces
    ('Fed Chair Testifies',           'Chair Testifies'),
    ('Fed Chair Speaks',              'Chair Speaks'),
    ('Jackson Hole Symposium',        'Jackson Hole'),

    -- Demand and surveys
    ('ISM Manufacturing PMI',         'ISM Mfg'),
    ('ISM Services PMI',              'ISM Svcs'),
    ('Retail Sales m/m',              'Retail Sales'),
    ('Core Retail Sales m/m',         'Core Retail'),

    -- Housing
    ('Building Permits',              'Permits'),
    ('Housing Starts',                'Starts'),
    ('Existing Home Sales',           'Existing Homes'),
    ('New Home Sales',                'New Homes')
) as v(title, short_title)
where event_weights.title = v.title;
