import { redirect } from "next/navigation";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import type { InteractionRecord, ProfileRecord } from "@/lib/types";

export async function requireUser() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/");
  }

  return { supabase, user };
}

export async function getDashboardData() {
  const { supabase } = await requireUser();
  const now = new Date().toISOString();

  const [{ data: overdue }, { data: upcoming }, { data: recent }] = await Promise.all([
    supabase
      .from("profiles")
      .select("*")
      .lte("next_follow_up_at", now)
      .order("next_follow_up_at", { ascending: true })
      .limit(8),
    supabase
      .from("profiles")
      .select("*")
      .gt("next_follow_up_at", now)
      .order("next_follow_up_at", { ascending: true })
      .limit(8),
    supabase
      .from("interactions")
      .select("*, profiles!inner(*)")
      .order("interaction_date", { ascending: false })
      .limit(10),
  ]);

  return {
    overdue: (overdue ?? []) as ProfileRecord[],
    upcoming: (upcoming ?? []) as ProfileRecord[],
    recent: (recent ?? []) as Array<
      InteractionRecord & {
        profiles: ProfileRecord;
      }
    >,
  };
}

export async function getProfileById(profileId: string) {
  const { supabase } = await requireUser();

  const [{ data: profile }, { data: interactions }] = await Promise.all([
    supabase.from("profiles").select("*").eq("id", profileId).single(),
    supabase
      .from("interactions")
      .select("*")
      .eq("profile_id", profileId)
      .order("interaction_date", { ascending: false }),
  ]);

  return {
    profile: profile as ProfileRecord | null,
    interactions: (interactions ?? []) as InteractionRecord[],
  };
}
