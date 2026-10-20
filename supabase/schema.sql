-- 경남나들이 공간 DB (Supabase Postgres + PostGIS)
-- 실행: Supabase SQL Editor 또는 `psql -f supabase/schema.sql`

create extension if not exists postgis with schema extensions;

create table if not exists public.spots (
  id              uuid primary key default gen_random_uuid(),
  dedupe_key      text not null unique,                       -- 소스 간 중복 제거 키 (Python에서 생성)
  category        text not null check (category in ('FESTIVAL','FLEA_MARKET','MOVIE','TRAVEL_SPOT','NEW_OPEN')),
  title           text not null,
  subtitle        text,
  address         text,
  region_tag      text not null default '',                   -- 예: '강원 춘천'
  province        text,                                       -- region_tag 첫 토큰
  geog            extensions.geography(Point, 4326) not null, -- (lng, lat) 순서
  start_date      date,                                       -- null = 상시
  end_date        date,
  operating_hours text,
  indoor_outdoor  text check (indoor_outdoor in ('INDOOR','OUTDOOR','BOTH')),
  sources         text[] not null default '{}',
  source_url      text,
  confidence      real not null default 0.5 check (confidence between 0 and 1),
  extra           jsonb not null default '{}'::jsonb,
  fetched_at      timestamptz not null default now(),
  expires_at      timestamptz,                                -- 지나면 검색에서 제외
  check (start_date is null or end_date is null or start_date <= end_date)
);

create index if not exists spots_geog_gix    on public.spots using gist (geog);
create index if not exists spots_category_ix on public.spots (category);
create index if not exists spots_period_ix   on public.spots (start_date, end_date);
create index if not exists spots_expires_ix  on public.spots (expires_at);

-- 서버(service_role)만 접근. 정책을 만들지 않으면 anon/authenticated는 접근 불가.
alter table public.spots enable row level security;

-- 오늘 기준 진행 중인 항목 (security_invoker: 호출자 권한/RLS를 따름, PG15+)
create or replace view public.ongoing_spots with (security_invoker = true) as
select *
from public.spots
where (start_date is null or start_date <= current_date)
  and (end_date   is null or end_date   >= current_date)
  and (expires_at is null or expires_at > now());

-- 반경 검색: ST_DWithin(미터 단위, geography) + 진행 중 필터 + 거리순(KNN)
create or replace function public.search_spots_nearby(
  p_lat        double precision,
  p_lng        double precision,
  p_radius_m   integer default 3000,
  p_date       date default current_date,
  p_categories text[] default null,
  p_limit      integer default 200
)
returns table (
  id uuid, category text, title text, subtitle text, address text, region_tag text, province text,
  lat double precision, lng double precision, start_date date, end_date date,
  operating_hours text, indoor_outdoor text, sources text[], source_url text,
  confidence real, extra jsonb, distance_m double precision
)
language sql
stable
set search_path = public, extensions
as $$
  with q as (select st_setsrid(st_makepoint(p_lng, p_lat), 4326)::geography as pt)
  select s.id, s.category, s.title, s.subtitle, s.address, s.region_tag, s.province,
         st_y(s.geog::geometry), st_x(s.geog::geometry), s.start_date, s.end_date,
         s.operating_hours, s.indoor_outdoor, s.sources, s.source_url,
         s.confidence, s.extra, st_distance(s.geog, q.pt)
  from public.spots s, q
  where st_dwithin(s.geog, q.pt, least(greatest(p_radius_m, 1), 50000))
    and (s.start_date is null or s.start_date <= p_date)
    and (s.end_date   is null or s.end_date   >= p_date)
    and (s.expires_at is null or s.expires_at > now())
    and (p_categories is null or s.category = any(p_categories))
  order by s.geog <-> q.pt
  limit least(greatest(p_limit, 1), 500);
$$;

-- 일괄 Upsert: dedupe_key 충돌 시 출처 합집합, 신뢰도 최댓값, extra 병합
create or replace function public.upsert_spots(p_rows jsonb)
returns integer
language plpgsql
set search_path = public, extensions
as $$
declare
  n integer;
begin
  with src as (
    select distinct on (r->>'dedupe_key')
      r->>'dedupe_key'                         as dedupe_key,
      r->>'category'                           as category,
      r->>'title'                              as title,
      r->>'subtitle'                           as subtitle,
      r->>'address'                            as address,
      coalesce(r->>'region_tag', '')           as region_tag,
      r->>'province'                           as province,
      st_setsrid(st_makepoint((r->>'lng')::float8, (r->>'lat')::float8), 4326)::geography as geog,
      nullif(r->>'start_date', '')::date       as start_date,
      nullif(r->>'end_date', '')::date         as end_date,
      r->>'operating_hours'                    as operating_hours,
      r->>'indoor_outdoor'                     as indoor_outdoor,
      array(select jsonb_array_elements_text(coalesce(r->'sources', '[]'::jsonb))) as sources,
      r->>'source_url'                         as source_url,
      coalesce((r->>'confidence')::real, 0.5)  as confidence,
      coalesce(r->'extra', '{}'::jsonb)        as extra,
      nullif(r->>'expires_at', '')::timestamptz as expires_at
    from jsonb_array_elements(p_rows) r
    where r->>'lat' is not null and r->>'lng' is not null     -- 좌표 없는 항목은 저장하지 않음
    order by r->>'dedupe_key', coalesce((r->>'confidence')::real, 0.5) desc
  ), ins as (
    insert into public.spots as s
      (dedupe_key, category, title, subtitle, address, region_tag, province, geog, start_date, end_date,
       operating_hours, indoor_outdoor, sources, source_url, confidence, extra, expires_at)
    select dedupe_key, category, title, subtitle, address, region_tag, province, geog, start_date, end_date,
           operating_hours, indoor_outdoor, sources, source_url, confidence, extra, expires_at
    from src
    on conflict (dedupe_key) do update set
      title           = excluded.title,
      subtitle        = coalesce(excluded.subtitle, s.subtitle),
      address         = coalesce(excluded.address, s.address),
      region_tag      = case when excluded.region_tag <> '' then excluded.region_tag else s.region_tag end,
      province        = coalesce(excluded.province, s.province),
      geog            = excluded.geog,
      start_date      = excluded.start_date,
      end_date        = excluded.end_date,
      operating_hours = coalesce(excluded.operating_hours, s.operating_hours),
      indoor_outdoor  = coalesce(excluded.indoor_outdoor, s.indoor_outdoor),
      sources         = array(select distinct u from unnest(s.sources || excluded.sources) u order by u),
      source_url      = coalesce(excluded.source_url, s.source_url),
      confidence      = greatest(s.confidence, excluded.confidence),
      extra           = s.extra || excluded.extra,
      fetched_at      = now(),
      expires_at      = excluded.expires_at
    returning 1
  )
  select count(*) into n from ins;
  return n;
end;
$$;

-- 만료 항목 정리 (pg_cron 등으로 매일 실행: select cron.schedule('purge-spots','0 4 * * *','select public.purge_expired_spots()'))
create or replace function public.purge_expired_spots()
returns integer
language sql
as $$
  with d as (delete from public.spots where expires_at < now() - interval '7 days' returning 1)
  select count(*)::integer from d;
$$;

-- 함수는 service_role만 실행 가능
revoke all on function public.search_spots_nearby(double precision, double precision, integer, date, text[], integer) from public, anon, authenticated;
revoke all on function public.upsert_spots(jsonb) from public, anon, authenticated;
revoke all on function public.purge_expired_spots() from public, anon, authenticated;
grant execute on function public.search_spots_nearby(double precision, double precision, integer, date, text[], integer) to service_role;
grant execute on function public.upsert_spots(jsonb) to service_role;
grant execute on function public.purge_expired_spots() to service_role;
revoke all on public.ongoing_spots from anon, authenticated;
