-- Archive table for oracle_reports history snapshots.
-- Apply once before running scripts/reseed_reports.py in archive mode.

begin;

create table if not exists public.oracle_reports_archive (
  archive_id bigserial primary key,
  report_id bigint not null,
  event_id text not null,
  locale text not null,
  title text not null,
  slug text not null,
  body_md text not null,
  jsonld jsonb not null default '{}'::jsonb,
  unique_entity text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  archived_at timestamptz not null default now(),
  unique (report_id)
);

create index if not exists idx_oracle_reports_archive_locale_archived_at_desc
  on public.oracle_reports_archive(locale, archived_at desc);

create index if not exists idx_oracle_reports_archive_event_locale
  on public.oracle_reports_archive(event_id, locale);

alter table public.oracle_reports_archive enable row level security;

drop policy if exists oracle_reports_archive_service_role_all on public.oracle_reports_archive;
create policy oracle_reports_archive_service_role_all
on public.oracle_reports_archive
for all
to service_role
using (true)
with check (true);

grant all privileges on public.oracle_reports_archive to service_role;

commit;

