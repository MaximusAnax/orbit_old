import OpenAI from "openai";
import { NextResponse } from "next/server";
import { runReliableAiCall } from "@/lib/orbit/ai";
import { AUDIO_UPLOAD_LIMIT_BYTES, fallbackTranscript, validateUploadedFile } from "@/lib/orbit/uploads";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";

const ALLOWED_AUDIO_TYPES = ["audio/mpeg", "audio/mp4", "audio/wav", "audio/webm", "audio/x-m4a"];

export async function POST(request: Request) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const anonymousId = request.headers.get("x-orbit-anonymous-id") ?? undefined;

  try {
    const formData = await request.formData();
    const file = formData.get("audio");

    if (!(file instanceof File)) {
      return NextResponse.json({ error: "Audio file is required." }, { status: 400 });
    }

    validateUploadedFile(file, {
      allowedTypes: ALLOWED_AUDIO_TYPES,
      maxBytes: AUDIO_UPLOAD_LIMIT_BYTES,
    });

    const usedFallback = !process.env.OPENAI_API_KEY;
    const transcript = usedFallback ? fallbackTranscript(file) : await transcribeWithOpenAI(file);
    const review = {
      status: transcript.trim().length < 12 || usedFallback ? "needs_review" : "ready",
      confidence: transcript.trim().length < 12 || usedFallback ? "low" : "medium",
      reason: usedFallback
        ? "OpenAI is not configured, so Orbit used a local development transcript."
        : transcript.trim().length < 12
          ? "Transcript was too short to trust automatically."
          : null,
    };

    await trackServerEvent(supabase, {
      eventName: "audio_capture_processed",
      anonymousId,
      userId: user?.id,
      payload: {
        fileType: file.type,
        fileSize: file.size,
        usedFallback,
        reviewStatus: review.status,
      },
    });

    return NextResponse.json({ transcript, review });
  } catch (error) {
    await trackServerEvent(supabase, {
      eventName: "audio_capture_failed",
      anonymousId,
      userId: user?.id,
      payload: {
        error: error instanceof Error ? error.message : "Unable to process audio.",
      },
    });

    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to process audio." },
      { status: 400 },
    );
  }
}

async function transcribeWithOpenAI(file: File) {
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const response = await runReliableAiCall(
    () =>
      client.audio.transcriptions.create({
        file,
        model: "whisper-1",
      }),
    { operationName: "audio transcription", timeoutMs: 30_000, retries: 1 },
  );

  return response.text;
}
