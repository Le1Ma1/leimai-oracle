-- Phase 4.1 schema extension:
-- 1) Whale profiling fields on user_access_logs
-- 2) Mock payment state machine storage (payment_invoices)

begin;

alter table public.user_access_logs
  add column if not exists meta jsonb not null default '{}'::jsonb;

alter table public.user_access_logs
  add column if not exists whale_tier text;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'user_access_logs_whale_tier_check'
  ) then
    alter table public.user_access_logs
      add constraint user_access_logs_whale_tier_check
      check (
        whale_tier is null
        or whale_tier in ('Plankton', 'Fish', 'Dolphin', 'Whale', 'Kraken')
      );
  end if;
end $$;

create index if not exists idx_user_access_logs_wallet_created_desc
  on public.user_access_logs (wallet_address, created_at desc);

create index if not exists idx_user_access_logs_tier_created_desc
  on public.user_access_logs (whale_tier, created_at desc);

alter table public.user_access_logs enable row level security;

drop policy if exists "user_access_logs_service_update" on public.user_access_logs;
create policy "user_access_logs_service_update"
  on public.user_access_logs
  for update
  to service_role
  using (true)
  with check (true);

create table if not exists public.payment_invoices (
  invoice_id text primary key,
  wallet_address text,
  slug text not null default 'vault',
  plan_code text not null default 'sovereign',
  amount_usdt numeric(20, 6) not null check (amount_usdt > 0),
  pay_to_address text not null,
  nonce text not null unique,
  status text not null default 'pending'
    check (status in ('pending', 'expired', 'paid', 'cancelled')),
  expires_at_utc timestamptz not null,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_payment_invoices_status_created_desc
  on public.payment_invoices (status, created_at desc);

create index if not exists idx_payment_invoices_wallet_created_desc
  on public.payment_invoices (wallet_address, created_at desc);

drop trigger if exists trg_payment_invoices_set_updated_at on public.payment_invoices;
create trigger trg_payment_invoices_set_updated_at
before update on public.payment_invoices
for each row
execute function public.set_updated_at();

alter table public.payment_invoices enable row level security;

drop policy if exists "payment_invoices_public_read" on public.payment_invoices;
create policy "payment_invoices_public_read"
  on public.payment_invoices
  for select
  to anon, authenticated
  using (true);

drop policy if exists "payment_invoices_service_role_all" on public.payment_invoices;
create policy "payment_invoices_service_role_all"
  on public.payment_invoices
  for all
  to service_role
  using (true)
  with check (true);

grant select on public.payment_invoices to anon, authenticated;
grant all privileges on public.payment_invoices to service_role;

commit;
