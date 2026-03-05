-- Worldforge schema extension:
-- 1) Semantic world cells with entropy/rules lifecycle
-- 2) Global counters for space unlock thresholds

begin;

create extension if not exists postgis;
create extension if not exists vector;

create table if not exists public.world_entities (
  id bigserial primary key,
  lat double precision not null check (lat >= -90 and lat <= 90),
  lng double precision not null check (lng >= -180 and lng <= 180),
  location geography(point, 4326)
    generated always as (st_setsrid(st_makepoint(lng, lat), 4326)::geography) stored,
  seed_hash text not null unique,
  entropy double precision not null default 0.25 check (entropy >= 0 and entropy <= 1),
  rules jsonb not null default '{}'::jsonb,
  rules_summary text not null default '',
  embedding vector(1536),
  last_observed timestamptz not null default now(),
  is_fixed boolean not null default false,
  fixed_until timestamptz,
  development_count bigint not null default 0,
  mutation_count bigint not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_world_entities_location_gist
  on public.world_entities using gist (location);

create index if not exists idx_world_entities_entropy_desc
  on public.world_entities (entropy desc);

create index if not exists idx_world_entities_last_observed_desc
  on public.world_entities (last_observed desc);

create index if not exists idx_world_entities_fixed_until_desc
  on public.world_entities (is_fixed, fixed_until desc);

drop trigger if exists trg_world_entities_set_updated_at on public.world_entities;
create trigger trg_world_entities_set_updated_at
before update on public.world_entities
for each row
execute function public.set_updated_at();

create table if not exists public.world_meta (
  meta_key text primary key,
  value_num bigint not null default 0,
  meta jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

drop trigger if exists trg_world_meta_set_updated_at on public.world_meta;
create trigger trg_world_meta_set_updated_at
before update on public.world_meta
for each row
execute function public.set_updated_at();

insert into public.world_meta (meta_key, value_num, meta)
values ('global_development_count', 0, '{"seed":"worldforge"}'::jsonb)
on conflict (meta_key) do nothing;

alter table public.world_entities enable row level security;
alter table public.world_meta enable row level security;

drop policy if exists "world_entities_public_read" on public.world_entities;
create policy "world_entities_public_read"
  on public.world_entities
  for select
  to anon, authenticated
  using (true);

drop policy if exists "world_entities_service_role_all" on public.world_entities;
create policy "world_entities_service_role_all"
  on public.world_entities
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "world_meta_public_read" on public.world_meta;
create policy "world_meta_public_read"
  on public.world_meta
  for select
  to anon, authenticated
  using (true);

drop policy if exists "world_meta_service_role_all" on public.world_meta;
create policy "world_meta_service_role_all"
  on public.world_meta
  for all
  to service_role
  using (true)
  with check (true);

grant select on public.world_entities to anon, authenticated;
grant all privileges on public.world_entities to service_role;
grant select on public.world_meta to anon, authenticated;
grant all privileges on public.world_meta to service_role;

commit;

