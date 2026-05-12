drop function if exists public.search_interactions(vector(1536), integer);

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
  search_text text,
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
    i.search_text,
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
