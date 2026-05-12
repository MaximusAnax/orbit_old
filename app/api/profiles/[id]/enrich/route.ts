import { NextResponse } from "next/server";
import { buildEnrichmentMetadata } from "@/lib/orbit/action-layer";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import type { ProfileRecord } from "@/lib/types";

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
    const { data: profile, error } = await supabase
      .from("profiles")
      .select("*")
      .eq("id", id)
      .eq("user_id", user.id)
      .single();

    if (error || !profile) {
      throw error ?? new Error("Profile not found.");
    }

    const enrichment = buildEnrichmentMetadata(profile as ProfileRecord);
    const metadata = {
      ...((profile as ProfileRecord).metadata ?? {}),
      enrichment,
    };

    const { data: updatedProfile, error: updateError } = await supabase
      .from("profiles")
      .update({ metadata })
      .eq("id", id)
      .eq("user_id", user.id)
      .select("*")
      .single();

    if (updateError || !updatedProfile) {
      throw updateError ?? new Error("Unable to enrich profile.");
    }

    await supabase.from("enrichment_jobs").insert({
      user_id: user.id,
      profile_id: id,
      status: "completed",
      payload: enrichment,
    });

    await trackServerEvent(supabase, {
      eventName: "profile_enriched",
      userId: user.id,
      payload: { profileId: id, confidence: enrichment.confidence },
    });

    return NextResponse.json({ profile: updatedProfile });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to enrich profile." },
      { status: 400 },
    );
  }
}
