-- Phase 3.3 - wallet signature unlock telemetry
-- Tracks which wallet unlocked which report slug and when.

create table if not exists public.user_access_logs (
  id bigserial primary key,
  wallet_address text not null,
  slug text not null,
  signed_at_utc timestamptz not null default now(),
  source text not null default 'wallet_signature',
  created_at timestamptz not null default now()
);

create index if not exists idx_user_access_logs_wallet_signed_at
  on public.user_access_logs (wallet_address, signed_at_utc desc);

create index if not exists idx_user_access_logs_slug_signed_at
  on public.user_access_logs (slug, signed_at_utc desc);

alter table public.user_access_logs enable row level security;

drop policy if exists "user_access_logs_public_read" on public.user_access_logs;
create policy "user_access_logs_public_read"
  on public.user_access_logs
  for select
  to anon, authenticated
  using (true);

drop policy if exists "user_access_logs_service_insert" on public.user_access_logs;
create policy "user_access_logs_service_insert"
  on public.user_access_logs
  for insert
  to service_role
  with check (true);

