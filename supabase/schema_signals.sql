-- Phase 3.6 - signals storage prototype
-- Pre-allocates model signal schema before production signal output is enabled.

create table if not exists public.model_signals (
  signal_id bigserial primary key,
  ts_utc timestamptz not null default now(),
  symbol text not null,
  timeframe text not null default '1m',
  signal_type text not null,
  direction text not null,
  entry_price numeric(20,8) not null,
  confidence_score numeric(6,5) not null,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint model_signals_direction_check check (direction in ('long', 'short', 'flat')),
  constraint model_signals_confidence_check check (confidence_score >= 0 and confidence_score <= 1)
);

create index if not exists idx_model_signals_symbol_ts
  on public.model_signals (symbol, ts_utc desc);

create index if not exists idx_model_signals_type_dir_ts
  on public.model_signals (signal_type, direction, ts_utc desc);

alter table public.model_signals enable row level security;

drop policy if exists "model_signals_public_read" on public.model_signals;
create policy "model_signals_public_read"
  on public.model_signals
  for select
  to anon, authenticated
  using (true);

drop policy if exists "model_signals_service_insert" on public.model_signals;
create policy "model_signals_service_insert"
  on public.model_signals
  for insert
  to service_role
  with check (true);

drop policy if exists "model_signals_service_update" on public.model_signals;
create policy "model_signals_service_update"
  on public.model_signals
  for update
  to service_role
  using (true)
  with check (true);
