-- Seed: Acme Plumbing — the one business the v1 demo serves.

insert into businesses (slug, name, business_hours, emergency_phone, greeting)
values (
  'acme-plumbing',
  'Acme Plumbing',
  '{
    "mon": [8, 18],
    "tue": [8, 18],
    "wed": [8, 18],
    "thu": [8, 18],
    "fri": [8, 18],
    "sat": [9, 14],
    "sun": null
  }'::jsonb,
  '+15551234567',
  'Acme Plumbing, this is Mike. How can I help you today?'
)
on conflict (slug) do nothing;

with biz as (select id from businesses where slug = 'acme-plumbing')
insert into services (business_id, name, description, base_price_cents, duration_minutes, emergency_eligible)
select biz.id, s.name, s.descr, s.price, s.dur, s.emerg
from biz, (values
  ('Drain cleaning',          'Standard drain or toilet unclog',           12500, 60, false),
  ('Leak repair',             'Fix a leaking pipe or fixture',             15000, 90, true),
  ('Water heater service',    'Diagnose or repair a water heater',         18500, 120, false),
  ('Burst pipe — emergency',  'Stop active flooding, temporary patch',     35000, 60, true),
  ('Toilet repair',           'Repair or replace flush mechanism / wax ring', 14000, 75, false),
  ('Sewer line inspection',   'Camera inspection of main sewer line',      22500, 90, false)
) as s(name, descr, price, dur, emerg)
on conflict do nothing;
