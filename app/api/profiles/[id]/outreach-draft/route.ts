import { NextResponse } from "next/server";
import { createOutreachDraft } from "@/lib/orbit/action-layer";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import type { InteractionRecord, ProfileRecord } from "@/lib/types";

export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  }

  try {
    const { id } = await params;
    const [{ data: profile }, { data: interactions }] = await Promise.all([
      supabase.from("profiles").select("*").eq("id", id).eq("user_id", user.id).single(),
      supabase
        .from("interactions")
        .select("*")
        .eq("profile_id", id)
        .eq("user_id", user.id)
        .order("interaction_date", { ascending: false })
        .limit(5),
    ]);

    if (!profile) {
      throw new Error("Profile not found.");
    }

    const draft = await createOutreachDraft(profile as ProfileRecord, (interactions ?? []) as InteractionRecord[]);

    await trackServerEvent(supabase, {
      eventName: "outreach_draft_created",
      userId: user.id,
      payload: {
        profileId: id,
        interactions: interactions?.length ?? 0,
      },
    });

    return NextResponse.json({ draft });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to create draft." },
      { status: 400 },
    );
  }
}
