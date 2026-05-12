import { NextResponse } from "next/server";
import { extractMemory } from "@/lib/orbit/ai";
import { trackServerEvent } from "@/lib/orbit/events";
import { persistPendingCapture } from "@/lib/orbit/pending-captures";
import { createPreviewPatches } from "@/lib/orbit/preview";
import { serializeSseEvent } from "@/lib/orbit/sse";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { extractRequestSchema } from "@/lib/validators";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const startedAt = Date.now();
    const { rawText, stream, captureId: requestedCaptureId, captureStartedAtMs } = extractRequestSchema.parse(body);
    const anonymousId = request.headers.get("x-orbit-anonymous-id") ?? "";
    const captureId = requestedCaptureId ?? crypto.randomUUID();

    if (stream) {
      const supabase = await createSupabaseServerClient();
      const {
        data: { user },
      } = await supabase.auth.getUser();
      const encoder = new TextEncoder();

      const responseStream = new ReadableStream({
        async start(controller) {
          const send = (event: string, data: unknown) => {
            controller.enqueue(encoder.encode(serializeSseEvent(event, data)));
          };

          try {
            send("meta", { captureId });

            for (const patch of createPreviewPatches(rawText)) {
              send("preview", { captureId, patch });
            }

            const extraction = await extractMemory(rawText);

            if (anonymousId) {
              await persistPendingCapture({
                captureId,
                anonymousId,
                rawText,
                extraction,
                userId: user?.id,
              });
            }

            await trackServerEvent(supabase, {
              eventName: "extract_succeeded",
              anonymousId: anonymousId || undefined,
              userId: user?.id,
              payload: {
                captureId,
                durationMs: Date.now() - startedAt,
                captureAgeMs: captureStartedAtMs ? Date.now() - captureStartedAtMs : null,
                hasOrg: Boolean(extraction.contact.org),
                hasRole: Boolean(extraction.contact.role),
                tags: extraction.tags.length,
              },
            });

            send("final", { captureId, extraction });
          } catch (error) {
            send("error", {
              error: error instanceof Error ? error.message : "Unable to extract memory.",
            });
          } finally {
            controller.close();
          }
        },
      });

      return new Response(responseStream, {
        headers: {
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
          "Content-Type": "text/event-stream; charset=utf-8",
        },
      });
    }

    const extraction = await extractMemory(rawText);
    const supabase = await createSupabaseServerClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (anonymousId) {
      await persistPendingCapture({
        captureId,
        anonymousId,
        rawText,
        extraction,
        userId: user?.id,
      });
    }

    await trackServerEvent(supabase, {
      eventName: "extract_succeeded",
      anonymousId: anonymousId || undefined,
      userId: user?.id,
      payload: {
        captureId,
        durationMs: Date.now() - startedAt,
        captureAgeMs: captureStartedAtMs ? Date.now() - captureStartedAtMs : null,
        hasOrg: Boolean(extraction.contact.org),
        hasRole: Boolean(extraction.contact.role),
        tags: extraction.tags.length,
      },
    });

    return NextResponse.json({ captureId, extraction });
  } catch (error) {
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Unable to extract memory.",
      },
      { status: 400 },
    );
  }
}
