-- Horse Supabase project only (tkbhjbpiiierhjhjfjdd). Safe to run more than once.
-- Public read, no public write. Win percentages are also stored in fig_meta
-- (win_pct_today) so the live site works even before this table exists.

create table if not exists public.win_pct (
  ride_id bigint primary key,
  race_id bigint,
  date date,
  horse_norm text,
  horse text,
  win_pct real,
  fair_odds real,
  win_rank smallint
);

create index if not exists win_pct_date_idx on public.win_pct (date);

alter table public.win_pct enable row level security;

drop policy if exists win_pct_public_read on public.win_pct;
create policy win_pct_public_read on public.win_pct for select using (true);

grant select on public.win_pct to anon, authenticated;
