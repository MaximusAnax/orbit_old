import { NextResponse } from "next/server";
import { extractMemory } from "@/lib/orbit/ai";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { extractRequestSchema } from "@/lib/validators";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { rawText } = extractRequestSchema.parse(body);
    const extraction = await extractMemory(rawText);
    const supabase = await createSupabaseServerClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    await trackServerEvent(supabase, {
      eventName: "extract_succeeded",
      anonymousId: request.headers.get("x-orbit-anonymous-id") ?? undefined,
      userId: user?.id,
      payload: {
        hasOrg: Boolean(extraction.contact.org),
        hasRole: Boolean(extraction.contact.role),
        tags: extraction.tags.length,
      },
    });

    return NextResponse.json({ extraction });
  } catch (error) {
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Unable to extract memory.",
      },
      { status: 400 },
    );
  }
}
