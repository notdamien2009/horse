-- Horse Supabase project only (tkbhjbpiiierhjhjfjdd). Safe to run more than once.
-- Public read, no public write. Compact last-~6 sectional runs for today's card
-- horses only. The live site hides the sectional panel if this table is missing.

create table if not exists public.sectionals (
  horse_norm text not null,
  date date not null,
  course text,
  rtv_race_id bigint,
  n smallint not null,
  pace_label text,
  fin_speed_pct real,
  fig_adj real,
  fig real,
  run_style text,
  style_pct real,
  sectors text,
  primary key (horse_norm, n)
);

create index if not exists sectionals_horse_date_idx on public.sectionals (horse_norm, date);

alter table public.sectionals enable row level security;

drop policy if exists sectionals_public_read on public.sectionals;
create policy sectionals_public_read on public.sectionals for select using (true);

grant select on public.sectionals to anon, authenticated;
