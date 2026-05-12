import { createSupabaseServerClient } from "@/lib/supabase/server";
import type { PendingCaptureRecord } from "@/lib/types";
import { extractionResultSchema, type ExtractionResult } from "@/lib/validators";

export async function persistPendingCapture(input: {
  captureId: string;
  anonymousId: string;
  rawText: string;
  extraction: ExtractionResult;
  userId?: string | null;
}) {
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.from("pending_captures").upsert({
    id: input.captureId,
    anonymous_id: input.anonymousId,
    raw_content: input.rawText,
    extraction: input.extraction,
    user_id: input.userId ?? null,
    status: "pending",
  });

  if (error) {
    throw error;
  }
}

export async function claimPendingCapture(captureId: string, anonymousId: string | null) {
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase.rpc("claim_pending_capture", {
    p_capture_id: captureId,
    p_anonymous_id: anonymousId,
  });

  if (error) {
    throw error;
  }

  return ((data ?? [])[0] ?? null) as PendingCaptureRecord | null;
}

export async function markPendingCaptureCommitted(input: {
  captureId: string;
  userId: string;
  profileId: string;
  interactionId: string;
}) {
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase
    .from("pending_captures")
    .update({
      user_id: input.userId,
      status: "committed",
      profile_id: input.profileId,
      interaction_id: input.interactionId,
      committed_at: new Date().toISOString(),
    })
    .eq("id", input.captureId);

  if (error) {
    throw error;
  }
}

export function parsePendingCaptureExtraction(record: Pick<PendingCaptureRecord, "extraction">) {
  return extractionResultSchema.parse(record.extraction);
}
