-- Voice AI Receptionist — initial schema
-- Apply via: psql "$SUPABASE_DB_URL" -f infra/supabase/001_init.sql
-- Or paste into Supabase SQL Editor.

-- ============================================================================
-- Enums
-- ============================================================================

do $$ begin
  create type call_outcome as enum (
    'in_progress', 'booked', 'emergency', 'info_only', 'dropped', 'infra_error'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type appointment_status as enum (
    'pending', 'confirmed', 'cancelled', 'completed'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type transcript_role as enum ('user', 'assistant', 'tool', 'system');
exception when duplicate_object then null; end $$;

-- ============================================================================
-- Tables
-- ============================================================================

create table if not exists businesses (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  business_hours jsonb not null,
  emergency_phone text not null,
  receptionist_name text not null default 'Mike',
  greeting text not null,
  created_at timestamptz not null default now()
);

create table if not exists services (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references businesses(id) on delete cascade,
  name text not null,
  description text,
  base_price_cents integer not null,
  duration_minutes integer not null,
  emergency_eligible boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists services_business_idx on services(business_id);

create table if not exists calls (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references businesses(id),
  twilio_call_sid text unique not null,
  caller_phone text not null,
  caller_phone_last4 text generated always as (right(caller_phone, 4)) stored,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  outcome call_outcome not null default 'in_progress',
  latency_metrics jsonb,
  created_at timestamptz not null default now()
);
create index if not exists calls_business_started_idx on calls(business_id, started_at desc);
create index if not exists calls_outcome_idx on calls(outcome);

create table if not exists transcripts (
  id uuid primary key default gen_random_uuid(),
  call_id uuid not null references calls(id) on delete cascade,
  turn_index integer not null,
  role transcript_role not null,
  text text not null,
  tool_name text,
  tool_args jsonb,
  tool_result jsonb,
  started_at timestamptz not null,
  ended_at timestamptz not null,
  stt_latency_ms integer,
  llm_latency_ms integer,
  tts_latency_ms integer,
  unique (call_id, turn_index)
);
create index if not exists transcripts_call_turn_idx on transcripts(call_id, turn_index);

create table if not exists appointments (
  id uuid primary key default gen_random_uuid(),
  call_id uuid not null references calls(id),
  business_id uuid not null references businesses(id),
  service_id uuid not null references services(id),
  customer_name text not null,
  customer_phone text not null,
  customer_address text not null,
  scheduled_at timestamptz not null,
  status appointment_status not null default 'confirmed',
  confirmation_code text unique not null,
  notes text,
  created_at timestamptz not null default now()
);
create index if not exists appointments_scheduled_idx on appointments(business_id, scheduled_at);
create index if not exists appointments_call_idx on appointments(call_id);

-- ============================================================================
-- RLS — anon role gets read-only access to last 7 days
-- ============================================================================

alter table businesses    enable row level security;
alter table services      enable row level security;
alter table calls         enable row level security;
alter table transcripts   enable row level security;
alter table appointments  enable row level security;

drop policy if exists anon_read_businesses on businesses;
drop policy if exists anon_read_services on services;
drop policy if exists anon_read_calls on calls;
drop policy if exists anon_read_transcripts on transcripts;
drop policy if exists anon_read_appointments on appointments;

create policy anon_read_businesses on businesses for select to anon using (true);
create policy anon_read_services on services for select to anon using (true);

create policy anon_read_calls on calls for select to anon
  using (started_at > now() - interval '7 days');

create policy anon_read_transcripts on transcripts for select to anon
  using (exists (select 1 from calls c where c.id = call_id and c.started_at > now() - interval '7 days'));

create policy anon_read_appointments on appointments for select to anon
  using (created_at > now() - interval '7 days');

-- ============================================================================
-- Realtime — broadcast inserts/updates so the dashboard subscribes
-- ============================================================================

-- REPLICA IDENTITY FULL is required for UPDATE/DELETE events to carry row data,
-- and (critically) re-adding the tables forces the Realtime service to re-read
-- the publication. Without the FULL identity + re-add, postgres_changes events
-- silently never reach subscribers even though the channel reports SUBSCRIBED.
alter table calls         replica identity full;
alter table transcripts   replica identity full;
alter table appointments  replica identity full;

alter publication supabase_realtime add table calls;
alter publication supabase_realtime add table transcripts;
alter publication supabase_realtime add table appointments;
