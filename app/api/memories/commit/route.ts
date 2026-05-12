import { NextResponse } from "next/server";
import { embedText } from "@/lib/orbit/ai";
import { trackServerEvent } from "@/lib/orbit/events";
import { buildSearchText, calculateFollowUpAt, decideMatch, selectProfilesForMatching } from "@/lib/orbit/normalize";
import {
  claimPendingCapture,
  markPendingCaptureCommitted,
  parsePendingCaptureExtraction,
} from "@/lib/orbit/pending-captures";
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
    const anonymousId = request.headers.get("x-orbit-anonymous-id");
    const pendingCapture = await claimPendingCapture(input.captureId, anonymousId);

    if (
      pendingCapture?.status === "committed" &&
      pendingCapture.profile_id &&
      pendingCapture.interaction_id
    ) {
      return NextResponse.json({
        profileId: pendingCapture.profile_id,
        interactionId: pendingCapture.interaction_id,
        captureId: input.captureId,
        deduped: true,
      });
    }

    const extraction = input.extraction ?? (pendingCapture ? parsePendingCaptureExtraction(pendingCapture) : null);
    const rawText = input.rawText ?? pendingCapture?.raw_content ?? null;

    if (!extraction || !rawText) {
      return NextResponse.json(
        { error: "Pending capture could not be restored. Please extract the note again." },
        { status: 409 },
      );
    }

    const normalizedName = extraction.matchHints.normalizedName;

    const { data: existingProfiles } = await supabase
      .from("profiles")
      .select("*")
      .order("updated_at", { ascending: false })
      .limit(50);

    const candidateProfiles = selectProfilesForMatching((existingProfiles ?? []) as ProfileRecord[], extraction);
    const decision = decideMatch(candidateProfiles, extraction, input.resolution);

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
    const followUpAt = calculateFollowUpAt(interactionDate, extraction.suggestedFollowUpDays);
    const searchText = buildSearchText(extraction, rawText);
    const embedding = serializeVector(await embedText(searchText));

    let profileId = decision.selectedProfileId;

    if (!profileId) {
      const { data: createdProfile, error: profileError } = await supabase
        .from("profiles")
        .insert({
          user_id: user.id,
          full_name: extraction.contact.name,
          normalized_name: normalizedName,
          current_org: extraction.contact.org,
          job_role: extraction.contact.role,
          metadata: {
            source: "capture",
            context: extraction.interaction.context,
          },
          last_interaction_at: interactionDate.toISOString(),
          next_follow_up_at: followUpAt,
          follow_up_interval_days: extraction.suggestedFollowUpDays,
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
          current_org: extraction.contact.org,
          job_role: extraction.contact.role,
          last_interaction_at: interactionDate.toISOString(),
          next_follow_up_at: followUpAt,
          follow_up_interval_days: extraction.suggestedFollowUpDays,
        })
        .eq("id", profileId);

      if (updateError) {
        throw updateError;
      }
    }

    if (!profileId) {
      throw new Error("Unable to determine which profile to save.");
    }

    const { data: interaction, error: interactionError } = await supabase
      .from("interactions")
      .insert({
        profile_id: profileId,
        user_id: user.id,
        raw_content: rawText,
        structured_summary: extraction.interaction.summary,
        search_text: searchText,
        tags: extraction.tags,
        sentiment: extraction.interaction.sentiment,
        suggested_follow_up_days: extraction.suggestedFollowUpDays,
        embedding,
        interaction_date: interactionDate.toISOString(),
      })
      .select("id")
      .single();

    if (interactionError || !interaction) {
      throw interactionError ?? new Error("Unable to create interaction.");
    }

    await markPendingCaptureCommitted({
      captureId: input.captureId,
      userId: user.id,
      profileId,
      interactionId: interaction.id,
    }).catch(() => undefined);

    await trackServerEvent(supabase, {
      eventName: "memory_saved",
      anonymousId: anonymousId ?? undefined,
      userId: user.id,
      payload: {
        captureId: input.captureId,
        profileId,
        interactionId: interaction.id,
        timeToMemoryMs: input.captureStartedAtMs ? Date.now() - input.captureStartedAtMs : null,
      },
    });

    return NextResponse.json({
      captureId: input.captureId,
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
