create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  full_name text not null,
  normalized_name text not null,
  current_org text,
  job_role text,
  metadata jsonb not null default '{}'::jsonb,
  last_interaction_at timestamptz,
  next_follow_up_at timestamptz,
  follow_up_interval_days integer,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.interactions (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references public.profiles (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  raw_content text not null,
  structured_summary text not null,
  search_text text not null,
  tags text[] not null default '{}',
  sentiment text not null,
  suggested_follow_up_days integer not null,
  embedding vector(1536) not null,
  interaction_date timestamptz not null default timezone('utc', now()),
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users (id) on delete set null,
  event_name text not null,
  anonymous_id text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists profiles_user_id_idx on public.profiles (user_id);
create index if not exists profiles_user_id_normalized_name_idx on public.profiles (user_id, normalized_name);
create index if not exists profiles_user_id_next_follow_up_idx on public.profiles (user_id, next_follow_up_at);
create index if not exists interactions_user_id_idx on public.interactions (user_id);
create index if not exists interactions_profile_id_date_idx on public.interactions (profile_id, interaction_date desc);
create index if not exists interactions_embedding_idx on public.interactions using ivfflat (embedding vector_cosine_ops) with (lists = 100);
create index if not exists events_user_id_created_at_idx on public.events (user_id, created_at desc);

alter table public.profiles enable row level security;
alter table public.interactions enable row level security;
alter table public.events enable row level security;

create policy "profiles_select_own" on public.profiles
  for select using (auth.uid() = user_id);
create policy "profiles_insert_own" on public.profiles
  for insert with check (auth.uid() = user_id);
create policy "profiles_update_own" on public.profiles
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "profiles_delete_own" on public.profiles
  for delete using (auth.uid() = user_id);

create policy "interactions_select_own" on public.interactions
  for select using (auth.uid() = user_id);
create policy "interactions_insert_own" on public.interactions
  for insert with check (auth.uid() = user_id);
create policy "interactions_update_own" on public.interactions
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "interactions_delete_own" on public.interactions
  for delete using (auth.uid() = user_id);

create policy "events_select_own" on public.events
  for select using (auth.uid() = user_id or user_id is null);
create policy "events_insert_any" on public.events
  for insert with check (auth.uid() = user_id or user_id is null);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

create or replace function public.search_interactions(
  p_query_embedding vector(1536),
  p_match_count integer default 5
)
returns table (
  interaction_id uuid,
  profile_id uuid,
  full_name text,
  current_org text,
  job_role text,
  structured_summary text,
  raw_content text,
  tags text[],
  sentiment text,
  interaction_date timestamptz,
  similarity double precision
)
language sql
security invoker
set search_path = public
as $$
  select
    i.id as interaction_id,
    p.id as profile_id,
    p.full_name,
    p.current_org,
    p.job_role,
    i.structured_summary,
    i.raw_content,
    i.tags,
    i.sentiment,
    i.interaction_date,
    1 - (i.embedding <=> p_query_embedding) as similarity
  from public.interactions i
  join public.profiles p on p.id = i.profile_id
  where i.user_id = auth.uid()
  order by i.embedding <=> p_query_embedding
  limit greatest(p_match_count, 1);
$$;
