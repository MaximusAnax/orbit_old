-- Orbit staging ops report.
-- Run in Supabase SQL editor to inspect hardening metrics before release.

select
  event_name,
  count(*) as event_count,
  max(created_at) as last_seen_at
from public.events
where created_at > now() - interval '7 days'
group by event_name
order by event_count desc;

select
  status,
  count(*) as reminder_count,
  max(created_at) as last_recorded_at
from public.reminders
where created_at > now() - interval '7 days'
group by status
order by reminder_count desc;

select
  count(*) filter (where payload ? 'timeToMemoryMs') as saved_memories_with_timing,
  percentile_cont(0.5) within group (order by ((payload->>'timeToMemoryMs')::numeric)) as p50_time_to_memory_ms,
  percentile_cont(0.9) within group (order by ((payload->>'timeToMemoryMs')::numeric)) as p90_time_to_memory_ms
from public.events
where event_name = 'memory_saved'
  and payload ? 'timeToMemoryMs'
  and created_at > now() - interval '7 days';
