import { NextResponse } from "next/server";
import { normalizeName } from "@/lib/orbit/normalize";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { profileUpdateSchema } from "@/lib/validators";

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  }

  try {
    const { id } = await params;
    const body = await request.json();
    const input = profileUpdateSchema.parse(body);
    const updates: Record<string, unknown> = {};

    if (input.fullName !== undefined) {
      updates.full_name = input.fullName;
      updates.normalized_name = normalizeName(input.fullName);
    }

    if (input.currentOrg !== undefined) {
      updates.current_org = input.currentOrg || null;
    }

    if (input.jobRole !== undefined) {
      updates.job_role = input.jobRole || null;
    }

    if (input.followUpIntervalDays !== undefined) {
      updates.follow_up_interval_days = input.followUpIntervalDays;
    }

    if (input.metadata !== undefined) {
      updates.metadata = input.metadata;
    }

    const { data: profile, error } = await supabase
      .from("profiles")
      .update(updates)
      .eq("id", id)
      .eq("user_id", user.id)
      .select("*")
      .single();

    if (error || !profile) {
      throw error ?? new Error("Unable to update profile.");
    }

    await trackServerEvent(supabase, {
      eventName: "profile_updated",
      userId: user.id,
      payload: {
        profileId: id,
        fields: Object.keys(updates),
      },
    });

    return NextResponse.json({ profile });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to update profile." },
      { status: 400 },
    );
  }
}
