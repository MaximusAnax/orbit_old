create table if not exists public.enrichment_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  profile_id uuid not null references public.profiles (id) on delete cascade,
  status text not null default 'completed' check (status in ('pending', 'completed', 'failed')),
  provider text not null default 'orbit',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists enrichment_jobs_profile_created_idx on public.enrichment_jobs (profile_id, created_at desc);

alter table public.enrichment_jobs enable row level security;

drop policy if exists "enrichment_jobs_select_own" on public.enrichment_jobs;
create policy "enrichment_jobs_select_own" on public.enrichment_jobs
  for select using (auth.uid() = user_id);
drop policy if exists "enrichment_jobs_insert_own" on public.enrichment_jobs;
create policy "enrichment_jobs_insert_own" on public.enrichment_jobs
  for insert with check (auth.uid() = user_id);
