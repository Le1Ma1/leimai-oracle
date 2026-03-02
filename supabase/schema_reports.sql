-- Phase 1.2 Oracle Brain schema extension
-- Adds oracle_reports table for multilingual AI report generation.

begin;

create table if not exists public.oracle_reports (
  report_id bigserial primary key,
  event_id text not null references public.anomaly_events(event_id) on delete cascade,
  locale text not null check (locale in ('en', 'zh-tw')),
  title text not null,
  slug text not null,
  body_md text not null,
  jsonld jsonb not null default '{}'::jsonb,
  unique_entity text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (event_id, locale),
  unique (locale, slug)
);

create index if not exists idx_oracle_reports_event_id on public.oracle_reports(event_id);
create index if not exists idx_oracle_reports_locale_created_at_desc on public.oracle_reports(locale, created_at desc);
create index if not exists idx_oracle_reports_slug on public.oracle_reports(slug);

drop trigger if exists trg_oracle_reports_set_updated_at on public.oracle_reports;
create trigger trg_oracle_reports_set_updated_at
before update on public.oracle_reports
for each row
execute function public.set_updated_at();

alter table public.oracle_reports enable row level security;

drop policy if exists oracle_reports_service_role_all on public.oracle_reports;
create policy oracle_reports_service_role_all
on public.oracle_reports
for all
to service_role
using (true)
with check (true);

drop policy if exists oracle_reports_public_read on public.oracle_reports;
create policy oracle_reports_public_read
on public.oracle_reports
for select
to anon, authenticated
using (true);

grant select on public.oracle_reports to anon, authenticated;
grant all privileges on public.oracle_reports to service_role;

commit;
