-- PinPlay 소셜 기능(카카오 로그인 사용자, 좋아요, 댓글, 신고)
-- 실행: Supabase SQL Editor에 이 파일 내용을 붙여 넣고 Run (schema.sql을 먼저 실행한 뒤)
-- 서버(service_role 키)만 접근한다: RLS를 켜고 정책을 만들지 않으며 anon/authenticated 권한은 회수한다.

create table if not exists public.users (
  kakao_id   bigint primary key,
  nickname   text not null,
  created_at timestamptz not null default now(),
  last_login timestamptz not null default now()
);

-- place_id는 spots.id. 만료된 장소가 정리돼도 좋아요·댓글이 연쇄 삭제되지 않게 FK를 걸지 않는다(서버가 존재 여부를 확인한다).
create table if not exists public.likes (
  place_id   uuid   not null,
  user_id    bigint not null references public.users (kakao_id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (place_id, user_id)
);
create index if not exists likes_place_ix on public.likes (place_id);

create table if not exists public.comments (
  id         uuid primary key default gen_random_uuid(),
  place_id   uuid   not null,
  user_id    bigint not null references public.users (kakao_id) on delete cascade,
  body       text   not null check (char_length(body) between 1 and 300),
  hidden     boolean not null default false,   -- 신고가 쌓이거나 관리자가 숨김
  reports    integer not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists comments_place_ix    on public.comments (place_id, created_at desc);
create index if not exists comments_reported_ix on public.comments (reports) where reports > 0;

create table if not exists public.comment_reports (
  comment_id uuid   not null references public.comments (id) on delete cascade,
  user_id    bigint not null references public.users (kakao_id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (comment_id, user_id)            -- 한 사람이 같은 댓글을 여러 번 신고할 수 없다
);

alter table public.users           enable row level security;
alter table public.likes           enable row level security;
alter table public.comments        enable row level security;
alter table public.comment_reports enable row level security;
revoke all on public.users, public.likes, public.comments, public.comment_reports from anon, authenticated;

-- 좋아요 토글: 이미 있으면 취소, 없으면 추가. 한 번의 호출로 처리해 동시에 눌러도 중복되지 않는다.
create or replace function public.toggle_like(p_place uuid, p_user bigint)
returns table (out_liked boolean, out_likes integer)
language plpgsql
as $$
declare
  removed integer;
begin
  delete from public.likes l where l.place_id = p_place and l.user_id = p_user;
  get diagnostics removed = row_count;
  if removed = 0 then
    insert into public.likes (place_id, user_id) values (p_place, p_user) on conflict do nothing;
  end if;
  return query
    select (removed = 0), (select count(*)::integer from public.likes l2 where l2.place_id = p_place);
end;
$$;

-- 여러 장소의 좋아요 수·댓글 수·내가 눌렀는지를 한 번에 (카드 목록에 표시)
create or replace function public.place_social(p_ids uuid[], p_user bigint default null)
returns table (out_place uuid, out_likes integer, out_comments integer, out_liked boolean)
language sql
stable
as $$
  select i,
         (select count(*)::integer from public.likes l where l.place_id = i),
         (select count(*)::integer from public.comments c where c.place_id = i and not c.hidden),
         (p_user is not null and exists (select 1 from public.likes l2 where l2.place_id = i and l2.user_id = p_user))
  from unnest(p_ids) as i;
$$;

-- 댓글 신고: 사람당 1회. 신고가 기준(기본 3건) 이상이면 자동으로 숨기고 관리자가 확인한다.
create or replace function public.report_comment(p_comment uuid, p_user bigint, p_threshold integer default 3)
returns table (out_reported boolean, out_hidden boolean)
language plpgsql
as $$
declare
  inserted integer;
  n integer;
  h boolean;
begin
  insert into public.comment_reports (comment_id, user_id) values (p_comment, p_user) on conflict do nothing;
  get diagnostics inserted = row_count;
  select count(*)::integer into n from public.comment_reports r where r.comment_id = p_comment;
  update public.comments c
     set reports = n, hidden = c.hidden or (n >= p_threshold)
   where c.id = p_comment
  returning c.hidden into h;
  return query select (inserted > 0), coalesce(h, false);
end;
$$;

revoke all on function public.toggle_like(uuid, bigint)                 from public, anon, authenticated;
revoke all on function public.place_social(uuid[], bigint)              from public, anon, authenticated;
revoke all on function public.report_comment(uuid, bigint, integer)     from public, anon, authenticated;
grant execute on function public.toggle_like(uuid, bigint)              to service_role;
grant execute on function public.place_social(uuid[], bigint)           to service_role;
grant execute on function public.report_comment(uuid, bigint, integer)  to service_role;
