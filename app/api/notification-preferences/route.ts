import { NextResponse } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { notificationPreferenceUpdateSchema } from "@/lib/validators";

export async function GET() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  }

  const { data, error } = await supabase
    .from("notification_preferences")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }

  return NextResponse.json({
    preferences: data ?? {
      user_id: user.id,
      daily_digest_enabled: true,
      paused_until: null,
      unsubscribed_at: null,
      timezone: "UTC",
    },
  });
}

export async function PATCH(request: Request) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  }

  try {
    const input = notificationPreferenceUpdateSchema.parse(await request.json());
    const updates: Record<string, unknown> = {
      user_id: user.id,
    };

    if (input.dailyDigestEnabled !== undefined) {
      updates.daily_digest_enabled = input.dailyDigestEnabled;
      if (input.dailyDigestEnabled) {
        updates.unsubscribed_at = null;
      }
    }

    if (input.pausedUntil !== undefined) {
      updates.paused_until = input.pausedUntil;
    }

    if (input.timezone !== undefined) {
      updates.timezone = input.timezone;
    }

    const { data, error } = await supabase
      .from("notification_preferences")
      .upsert(updates, { onConflict: "user_id" })
      .select("*")
      .single();

    if (error) {
      throw error;
    }

    return NextResponse.json({ preferences: data });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to update notification preferences." },
      { status: 400 },
    );
  }
}
