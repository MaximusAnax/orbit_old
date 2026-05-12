import { NextResponse } from "next/server";
import { applyFollowUpAction } from "@/lib/orbit/reminders";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { followUpActionSchema } from "@/lib/validators";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
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
    const input = followUpActionSchema.parse(body);
    const { data: profile, error: profileError } = await supabase
      .from("profiles")
      .select("*")
      .eq("id", id)
      .eq("user_id", user.id)
      .single();

    if (profileError || !profile) {
      throw profileError ?? new Error("Profile not found.");
    }

    const transition = applyFollowUpAction(input, new Date(), profile.follow_up_interval_days ?? 21);
    const { data: updatedProfile, error: updateError } = await supabase
      .from("profiles")
      .update(transition.profileUpdates)
      .eq("id", id)
      .eq("user_id", user.id)
      .select("*")
      .single();

    if (updateError || !updatedProfile) {
      throw updateError ?? new Error("Unable to update follow-up.");
    }

    const { error: reminderError } = await supabase.from("reminders").insert({
      user_id: user.id,
      profile_id: id,
      status: transition.reminderStatus,
      due_at: transition.dueAt ?? new Date().toISOString(),
      payload: {
        action: input.action,
        note: input.action === "mark_contacted" ? input.note ?? null : null,
      },
    });

    if (reminderError) {
      throw reminderError;
    }

    await trackServerEvent(supabase, {
      eventName: "follow_up_action",
      userId: user.id,
      payload: {
        profileId: id,
        action: input.action,
      },
    });

    return NextResponse.json({ profile: updatedProfile });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to update follow-up." },
      { status: 400 },
    );
  }
}
