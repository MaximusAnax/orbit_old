import { NextResponse } from "next/server";
import { verifyUnsubscribeToken } from "@/lib/orbit/notifications";
import { createSupabaseServiceRoleClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret) {
    return NextResponse.json({ error: "Unsubscribe is not configured." }, { status: 500 });
  }

  const url = new URL(request.url);
  const userId = url.searchParams.get("userId");
  const token = url.searchParams.get("token");

  if (!userId || !token || !verifyUnsubscribeToken(userId, token, secret)) {
    return NextResponse.json({ error: "Invalid or expired unsubscribe link." }, { status: 400 });
  }

  const supabase = createSupabaseServiceRoleClient();
  const { error } = await supabase.from("notification_preferences").upsert(
    {
      user_id: userId,
      daily_digest_enabled: false,
      unsubscribed_at: new Date().toISOString(),
    },
    { onConflict: "user_id" },
  );

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }

  return new Response(
    "<!doctype html><html><body><h1>You're unsubscribed</h1><p>Orbit daily reminder emails are now turned off.</p></body></html>",
    {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
      },
    },
  );
}
