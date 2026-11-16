-- Horse Supabase project only (tkbhjbpiiierhjhjfjdd). Safe to run more than once.
-- Public read, no public write. Predictions are also stored in fig_meta (pred_model,
-- pred_today) so the live site works even before this table exists.

create table if not exists public.pred_today (
  ride_id bigint primary key,
  race_id bigint,
  date date,
  horse_norm text,
  horse text,
  pred real,
  lo real,
  hi real,
  best3 real,
  last_fig real,
  n_prior smallint,
  rank smallint,
  rank_best3 smallint,
  scale text
);

create index if not exists pred_today_date_idx on public.pred_today (date);

alter table public.pred_today enable row level security;

drop policy if exists pred_today_public_read on public.pred_today;
create policy pred_today_public_read on public.pred_today for select using (true);

grant select on public.pred_today to anon, authenticated;
