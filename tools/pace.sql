-- Horse Supabase project only (tkbhjbpiiierhjhjfjdd). Safe to run more than once.
-- Public read, no public write. The live site degrades gracefully if this table
-- is missing: past runs just have no precomputed pace badge (comment fallback still works).

create table if not exists public.pace (
  date date not null,
  course_norm text not null,
  course text,
  off_hhmm text,
  dist_f real,
  code text,
  label text,
  fig_rel text,
  reason text,
  source text,
  fsp real,
  field_def real,
  n_field smallint,
  horses text,
  fig_race_id text,
  rtv_race_id bigint
);

create index if not exists pace_date_course_idx on public.pace (date, course_norm);

alter table public.pace enable row level security;

drop policy if exists pace_public_read on public.pace;
create policy pace_public_read on public.pace for select using (true);

grant select on public.pace to anon, authenticated;

-- If you use the wipe_site_data RPC, add public.pace to its TRUNCATE list so
-- a later upload starts from a clean table. The uploader also DELETEs pace
-- itself when the table exists, so an upload still works before you change the RPC.
