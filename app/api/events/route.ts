import { NextResponse } from "next/server";
import { trackServerEvent } from "@/lib/orbit/events";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { trackEventSchema } from "@/lib/validators";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const input = trackEventSchema.parse(body);
    const supabase = await createSupabaseServerClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    await trackServerEvent(supabase, {
      eventName: input.eventName,
      anonymousId: input.anonymousId,
      payload: input.payload,
      userId: user?.id,
    });

    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ ok: false }, { status: 400 });
  }
}
