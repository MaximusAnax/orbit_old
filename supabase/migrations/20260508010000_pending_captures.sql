create table if not exists public.pending_captures (
  id uuid primary key,
  user_id uuid references auth.users (id) on delete set null,
  anonymous_id text not null,
  raw_content text not null,
  extraction jsonb not null,
  status text not null default 'pending' check (status in ('pending', 'committed')),
  profile_id uuid references public.profiles (id) on delete set null,
  interaction_id uuid references public.interactions (id) on delete set null,
  committed_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists pending_captures_user_id_idx on public.pending_captures (user_id, created_at desc);
create index if not exists pending_captures_anonymous_id_idx on public.pending_captures (anonymous_id, created_at desc);

alter table public.pending_captures enable row level security;

drop policy if exists "pending_captures_select_own" on public.pending_captures;
create policy "pending_captures_select_own" on public.pending_captures
  for select using (auth.uid() = user_id);

drop policy if exists "pending_captures_insert_pre_auth" on public.pending_captures;
create policy "pending_captures_insert_pre_auth" on public.pending_captures
  for insert with check (auth.uid() = user_id or user_id is null);

drop policy if exists "pending_captures_update_session" on public.pending_captures;
create policy "pending_captures_update_session" on public.pending_captures
  for update using (auth.uid() = user_id or user_id is null)
  with check (auth.uid() = user_id or user_id is null);

drop trigger if exists pending_captures_set_updated_at on public.pending_captures;
create trigger pending_captures_set_updated_at
before update on public.pending_captures
for each row execute function public.set_updated_at();

create or replace function public.claim_pending_capture(
  p_capture_id uuid,
  p_anonymous_id text default null
)
returns setof public.pending_captures
language plpgsql
security definer
set search_path = public
as $$
declare
  claimed public.pending_captures%rowtype;
begin
  if auth.uid() is null then
    raise exception 'Authentication required';
  end if;

  update public.pending_captures
  set user_id = coalesce(user_id, auth.uid())
  where id = p_capture_id
    and (
      user_id = auth.uid()
      or (
        user_id is null
        and p_anonymous_id is not null
        and anonymous_id = p_anonymous_id
      )
    )
  returning * into claimed;

  if claimed.id is null then
    return;
  end if;

  return next claimed;
end;
$$;

grant execute on function public.claim_pending_capture(uuid, text) to authenticated;
