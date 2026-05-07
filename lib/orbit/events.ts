import type { SupabaseClient } from "@supabase/supabase-js";

interface TrackEventInput {
  eventName: string;
  payload?: Record<string, unknown>;
  anonymousId?: string;
  userId?: string | null;
}

export async function trackServerEvent(supabase: SupabaseClient, input: TrackEventInput) {
  await supabase.from("events").insert({
    event_name: input.eventName,
    anonymous_id: input.anonymousId ?? null,
    payload: input.payload ?? {},
    user_id: input.userId ?? null,
  });
}
