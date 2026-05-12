import OpenAI from "openai";
import { NextResponse } from "next/server";
import { runReliableAiCall } from "@/lib/orbit/ai";
import { IMAGE_UPLOAD_LIMIT_BYTES, fallbackCardText, validateUploadedFile } from "@/lib/orbit/uploads";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";

const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

export async function POST(request: Request) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const anonymousId = request.headers.get("x-orbit-anonymous-id") ?? undefined;

  try {
    const formData = await request.formData();
    const file = formData.get("card");

    if (!(file instanceof File)) {
      return NextResponse.json({ error: "Card image is required." }, { status: 400 });
    }

    validateUploadedFile(file, {
      allowedTypes: ALLOWED_IMAGE_TYPES,
      maxBytes: IMAGE_UPLOAD_LIMIT_BYTES,
    });

    const usedFallback = !process.env.OPENAI_API_KEY;
    const text = usedFallback ? fallbackCardText(file) : await extractCardWithOpenAI(file);
    const review = {
      status: text.trim().length < 16 || usedFallback ? "needs_review" : "ready",
      confidence: text.trim().length < 16 || usedFallback ? "low" : "medium",
      reason: usedFallback
        ? "OpenAI is not configured, so Orbit used local development OCR text."
        : text.trim().length < 16
          ? "Card extraction returned too little text to trust automatically."
          : null,
    };

    await trackServerEvent(supabase, {
      eventName: "card_capture_processed",
      anonymousId,
      userId: user?.id,
      payload: {
        fileType: file.type,
        fileSize: file.size,
        usedFallback,
        reviewStatus: review.status,
      },
    });

    return NextResponse.json({ text, review });
  } catch (error) {
    await trackServerEvent(supabase, {
      eventName: "card_capture_failed",
      anonymousId,
      userId: user?.id,
      payload: {
        error: error instanceof Error ? error.message : "Unable to process card.",
      },
    });

    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to process card." },
      { status: 400 },
    );
  }
}

async function extractCardWithOpenAI(file: File) {
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const bytes = Buffer.from(await file.arrayBuffer());
  const dataUrl = `data:${file.type};base64,${bytes.toString("base64")}`;
  const response = await runReliableAiCall(
    () =>
      client.responses.create({
        model: "gpt-4o-mini",
        input: [
          {
            role: "user",
            content: [
              {
                type: "input_text",
                text: "Extract the visible contact details from this business card as plain text. Include name, role, company, email, phone, and any memorable context if present.",
              },
              {
                type: "input_image",
                image_url: dataUrl,
              },
            ],
          },
        ],
      } as never),
    { operationName: "business card extraction", timeoutMs: 30_000, retries: 1 },
  );

  return response.output_text;
}
