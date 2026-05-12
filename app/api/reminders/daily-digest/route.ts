import { NextResponse } from "next/server";
import { trackServerEvent } from "@/lib/orbit/events";
import {
  buildReminderEmail,
  createUnsubscribeToken,
  evaluateNotificationPreference,
  mapPreferenceByUserId,
} from "@/lib/orbit/notifications";
import { shouldSendDailyReminder } from "@/lib/orbit/reminders";
import { sendResendEmail } from "@/lib/orbit/resend";
import { createSupabaseServiceRoleClient } from "@/lib/supabase/server";
import type { NotificationPreferenceRecord, ProfileRecord, ReminderRecord } from "@/lib/types";

function groupProfilesByUser(profiles: ProfileRecord[]) {
  const grouped = new Map<string, ProfileRecord[]>();

  for (const profile of profiles) {
    const group = grouped.get(profile.user_id) ?? [];
    group.push(profile);
    grouped.set(profile.user_id, group);
  }

  return grouped;
}

function todayStartIso(now: Date) {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())).toISOString();
}

async function insertReminderRows(input: {
  supabase: ReturnType<typeof createSupabaseServiceRoleClient>;
  profiles: ProfileRecord[];
  status: "sent" | "failed" | "skipped";
  now: Date;
  payload: Record<string, unknown>;
}) {
  if (!input.profiles.length) return null;

  return input.supabase.from("reminders").insert(
    input.profiles.map((profile) => ({
      user_id: profile.user_id,
      profile_id: profile.id,
      status: input.status,
      due_at: profile.next_follow_up_at ?? input.now.toISOString(),
      sent_at: input.status === "sent" ? input.now.toISOString() : null,
      payload: input.payload,
    })),
  );
}

export async function POST(request: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret) {
    return NextResponse.json({ error: "CRON_SECRET is not configured." }, { status: 500 });
  }

  if (request.headers.get("authorization") !== `Bearer ${secret}`) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const resendApiKey = process.env.RESEND_API_KEY;
  const reminderFromEmail = process.env.REMINDER_FROM_EMAIL;
  const appUrl = process.env.NEXT_PUBLIC_APP_URL;

  if (!resendApiKey || !reminderFromEmail || !appUrl) {
    return NextResponse.json(
      { error: "RESEND_API_KEY, REMINDER_FROM_EMAIL, and NEXT_PUBLIC_APP_URL are required." },
      { status: 500 },
    );
  }

  try {
    const supabase = createSupabaseServiceRoleClient();
    const now = new Date();
    const todayStart = todayStartIso(now);

    const { data: dueProfiles, error: profileError } = await supabase
      .from("profiles")
      .select("*")
      .not("next_follow_up_at", "is", null)
      .lte("next_follow_up_at", now.toISOString())
      .limit(500);

    if (profileError) {
      return NextResponse.json({ error: profileError.message }, { status: 400 });
    }

    const due = ((dueProfiles ?? []) as ProfileRecord[]).filter((profile) =>
      shouldSendDailyReminder({
        nextFollowUpAt: profile.next_follow_up_at,
        alreadySentToday: false,
        now,
      }),
    );

    if (!due.length) {
      return NextResponse.json({ sent: 0, failed: 0, skipped: 0 });
    }

    const { data: existingReminders } = await supabase
      .from("reminders")
      .select("*")
      .in(
        "profile_id",
        due.map((profile) => profile.id),
      )
      .in("status", ["sent", "skipped"])
      .gte("created_at", todayStart);

    const alreadyHandledProfileIds = new Set(
      ((existingReminders ?? []) as ReminderRecord[]).map((reminder) => reminder.profile_id),
    );
    const pending = due.filter((profile) => !alreadyHandledProfileIds.has(profile.id));
    const userIds = Array.from(new Set(pending.map((profile) => profile.user_id)));

    if (!pending.length || !userIds.length) {
      return NextResponse.json({ sent: 0, failed: 0, skipped: due.length });
    }

    const { data: preferences } = await supabase
      .from("notification_preferences")
      .select("*")
      .in("user_id", userIds);
    const preferenceByUserId = mapPreferenceByUserId((preferences ?? []) as NotificationPreferenceRecord[]);
    const grouped = groupProfilesByUser(pending);

    let sent = 0;
    let failed = 0;
    let skipped = due.length - pending.length;

    for (const [userId, profiles] of grouped.entries()) {
      const preference = preferenceByUserId.get(userId);
      const preferenceDecision = evaluateNotificationPreference(preference, now);

      if (!preferenceDecision.allowed) {
        await insertReminderRows({
          supabase,
          profiles,
          status: "skipped",
          now,
          payload: {
            channel: "email",
            provider: "resend",
            skippedReason: preferenceDecision.skippedReason,
          },
        });
        skipped += profiles.length;
        continue;
      }

      const { data: authUser, error: userError } = await supabase.auth.admin.getUserById(userId);
      const recipient = authUser.user?.email ?? null;

      if (userError || !recipient) {
        await insertReminderRows({
          supabase,
          profiles,
          status: "skipped",
          now,
          payload: {
            channel: "email",
            provider: "resend",
            skippedReason: userError?.message ?? "missing_recipient_email",
          },
        });
        skipped += profiles.length;
        continue;
      }

      const unsubscribeUrl = new URL("/api/notifications/unsubscribe", appUrl);
      unsubscribeUrl.searchParams.set("userId", userId);
      unsubscribeUrl.searchParams.set("token", createUnsubscribeToken(userId, secret, now));
      const email = buildReminderEmail({
        profiles,
        appUrl,
        unsubscribeUrl: unsubscribeUrl.toString(),
      });

      try {
        const result = await sendResendEmail({
          apiKey: resendApiKey,
          from: reminderFromEmail,
          to: recipient,
          subject: email.subject,
          html: email.html,
          text: email.text,
          idempotencyKey: `daily-digest-${userId}-${todayStart.slice(0, 10)}`,
        });

        await insertReminderRows({
          supabase,
          profiles,
          status: "sent",
          now,
          payload: {
            channel: "email",
            provider: "resend",
            providerMessageId: result.id,
            recipient,
            subject: email.subject,
          },
        });

        await trackServerEvent(supabase, {
          eventName: "daily_reminder_sent",
          userId,
          payload: {
            provider: "resend",
            profileIds: profiles.map((profile) => profile.id),
            providerMessageId: result.id,
          },
        });
        sent += profiles.length;
      } catch (error) {
        await insertReminderRows({
          supabase,
          profiles,
          status: "failed",
          now,
          payload: {
            channel: "email",
            provider: "resend",
            recipient,
            subject: email.subject,
            error: error instanceof Error ? error.message : "Unable to send reminder email.",
          },
        });
        failed += profiles.length;
      }
    }

    return NextResponse.json({ sent, failed, skipped });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to generate daily digest." },
      { status: 500 },
    );
  }
}
