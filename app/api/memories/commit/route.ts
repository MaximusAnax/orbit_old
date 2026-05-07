import { NextResponse } from "next/server";
import { embedText } from "@/lib/orbit/ai";
import { trackServerEvent } from "@/lib/orbit/events";
import { buildSearchText, calculateFollowUpAt, decideMatch } from "@/lib/orbit/normalize";
import { serializeVector } from "@/lib/orbit/vector";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import type { ProfileRecord } from "@/lib/types";
import { commitMemorySchema } from "@/lib/validators";

export async function POST(request: Request) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  }

  try {
    const body = await request.json();
    const input = commitMemorySchema.parse(body);
    const normalizedName = input.extraction.matchHints.normalizedName;

    const { data: existingProfiles } = await supabase
      .from("profiles")
      .select("*")
      .eq("normalized_name", normalizedName)
      .limit(5);

    const decision = decideMatch((existingProfiles ?? []) as ProfileRecord[], input.extraction, input.resolution);

    if (decision.mode === "needs_confirmation") {
      return NextResponse.json(
        {
          requiresResolution: true,
          candidates: decision.candidates,
        },
        { status: 409 },
      );
    }

    const interactionDate = new Date();
    const followUpAt = calculateFollowUpAt(interactionDate, input.extraction.suggestedFollowUpDays);
    const searchText = buildSearchText(input.extraction, input.rawText);
    const embedding = serializeVector(await embedText(searchText));

    let profileId = decision.selectedProfileId;

    if (!profileId) {
      const { data: createdProfile, error: profileError } = await supabase
        .from("profiles")
        .insert({
          user_id: user.id,
          full_name: input.extraction.contact.name,
          normalized_name: normalizedName,
          current_org: input.extraction.contact.org,
          job_role: input.extraction.contact.role,
          metadata: {
            source: "capture",
            context: input.extraction.interaction.context,
          },
          last_interaction_at: interactionDate.toISOString(),
          next_follow_up_at: followUpAt,
          follow_up_interval_days: input.extraction.suggestedFollowUpDays,
        })
        .select("*")
        .single();

      if (profileError || !createdProfile) {
        throw profileError ?? new Error("Unable to create profile.");
      }

      profileId = createdProfile.id;
    } else {
      const { error: updateError } = await supabase
        .from("profiles")
        .update({
          current_org: input.extraction.contact.org,
          job_role: input.extraction.contact.role,
          last_interaction_at: interactionDate.toISOString(),
          next_follow_up_at: followUpAt,
          follow_up_interval_days: input.extraction.suggestedFollowUpDays,
        })
        .eq("id", profileId);

      if (updateError) {
        throw updateError;
      }
    }

    const { data: interaction, error: interactionError } = await supabase
      .from("interactions")
      .insert({
        profile_id: profileId,
        user_id: user.id,
        raw_content: input.rawText,
        structured_summary: input.extraction.interaction.summary,
        search_text: searchText,
        tags: input.extraction.tags,
        sentiment: input.extraction.interaction.sentiment,
        suggested_follow_up_days: input.extraction.suggestedFollowUpDays,
        embedding,
        interaction_date: interactionDate.toISOString(),
      })
      .select("id")
      .single();

    if (interactionError || !interaction) {
      throw interactionError ?? new Error("Unable to create interaction.");
    }

    await trackServerEvent(supabase, {
      eventName: "memory_saved",
      anonymousId: request.headers.get("x-orbit-anonymous-id") ?? undefined,
      userId: user.id,
      payload: {
        profileId,
        interactionId: interaction.id,
      },
    });

    return NextResponse.json({
      profileId,
      interactionId: interaction.id,
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Unable to save memory.",
      },
      { status: 400 },
    );
  }
}
