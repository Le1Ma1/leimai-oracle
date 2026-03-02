-- Phase 1 bootstrap schema for zero-budget ingestion pipeline.
-- Apply in Supabase SQL editor with a role that can create tables/policies.

begin;

create table if not exists public.market_liquidations (
  id bigserial primary key,
  ts_utc timestamptz not null,
  symbol text not null,
  side text not null check (side in ('BUY', 'SELL', 'LONG', 'SHORT', 'UNKNOWN')),
  usd_value numeric(20, 6) not null check (usd_value >= 0),
  hash_id text not null unique,
  source text not null default 'binance_force_orders',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.anomaly_events (
  id bigserial primary key,
  event_id text not null unique,
  ts_utc timestamptz not null default now(),
  event_type text not null,
  severity text not null check (severity in ('low', 'medium', 'high', 'critical')),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'new' check (status in ('new', 'queued', 'processed', 'failed', 'ignored')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_market_liquidations_ts_utc_desc
  on public.market_liquidations (ts_utc desc);

create index if not exists idx_market_liquidations_symbol_ts_desc
  on public.market_liquidations (symbol, ts_utc desc);

create index if not exists idx_anomaly_events_ts_utc_desc
  on public.anomaly_events (ts_utc desc);

create index if not exists idx_anomaly_events_status_ts_desc
  on public.anomaly_events (status, ts_utc desc);

create index if not exists idx_anomaly_events_type_ts_desc
  on public.anomaly_events (event_type, ts_utc desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_anomaly_events_set_updated_at on public.anomaly_events;
create trigger trg_anomaly_events_set_updated_at
before update on public.anomaly_events
for each row
execute function public.set_updated_at();

alter table public.market_liquidations enable row level security;
alter table public.anomaly_events enable row level security;

drop policy if exists market_liquidations_service_role_all on public.market_liquidations;
create policy market_liquidations_service_role_all
on public.market_liquidations
for all
to service_role
using (true)
with check (true);

drop policy if exists anomaly_events_service_role_all on public.anomaly_events;
create policy anomaly_events_service_role_all
on public.anomaly_events
for all
to service_role
using (true)
with check (true);

-- Keep anon/authenticated blocked for write by default under RLS.
grant usage on schema public to anon, authenticated, service_role;
grant select on public.market_liquidations to anon, authenticated;
grant select on public.anomaly_events to anon, authenticated;
grant all privileges on public.market_liquidations to service_role;
grant all privileges on public.anomaly_events to service_role;

commit;
