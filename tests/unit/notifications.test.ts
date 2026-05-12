import { describe, expect, it } from "vitest";
import {
  buildReminderEmail,
  createUnsubscribeToken,
  evaluateNotificationPreference,
  verifyUnsubscribeToken,
} from "@/lib/orbit/notifications";
import { sendResendEmail } from "@/lib/orbit/resend";
import type { ProfileRecord } from "@/lib/types";

const profile = {
  id: "profile-1",
  user_id: "user-1",
  full_name: "Priya Singh",
  normalized_name: "priya singh",
  current_org: "Figma",
  job_role: "Product Ops Lead",
  metadata: {},
  last_interaction_at: null,
  next_follow_up_at: "2026-05-08T00:00:00.000Z",
  follow_up_interval_days: 14,
  created_at: "2026-05-01T00:00:00.000Z",
  updated_at: "2026-05-01T00:00:00.000Z",
} satisfies ProfileRecord;

describe("notification preferences", () => {
  it("allows reminders when no explicit preference exists", () => {
    expect(evaluateNotificationPreference(null)).toEqual({ allowed: true, skippedReason: null });
  });

  it("skips disabled, paused, and unsubscribed users", () => {
    const now = new Date("2026-05-08T00:00:00.000Z");

    expect(evaluateNotificationPreference({ daily_digest_enabled: false }, now)).toEqual({
      allowed: false,
      skippedReason: "daily_digest_disabled",
    });
    expect(evaluateNotificationPreference({ paused_until: "2026-05-09T00:00:00.000Z" }, now)).toEqual({
      allowed: false,
      skippedReason: "paused",
    });
    expect(evaluateNotificationPreference({ unsubscribed_at: "2026-05-07T00:00:00.000Z" }, now)).toEqual({
      allowed: false,
      skippedReason: "unsubscribed",
    });
  });

  it("creates expiring unsubscribe tokens", () => {
    const secret = "super-secret";
    const token = createUnsubscribeToken("user-1", secret, new Date("2026-05-08T00:00:00.000Z"));

    expect(verifyUnsubscribeToken("user-1", token, secret, new Date("2026-05-09T00:00:00.000Z"))).toBe(true);
    expect(verifyUnsubscribeToken("user-2", token, secret, new Date("2026-05-09T00:00:00.000Z"))).toBe(false);
    expect(verifyUnsubscribeToken("user-1", token, secret, new Date("2026-06-09T00:00:00.000Z"))).toBe(false);
  });
});

describe("reminder email delivery", () => {
  it("builds one grouped digest email", () => {
    const email = buildReminderEmail({
      profiles: [profile, { ...profile, id: "profile-2", full_name: "Jordan Lee" }],
      appUrl: "https://orbit.example.com/app",
      unsubscribeUrl: "https://orbit.example.com/api/notifications/unsubscribe?token=abc",
    });

    expect(email.subject).toBe("2 warm follow-ups for today");
    expect(email.text).toContain("Priya Singh");
    expect(email.text).toContain("Jordan Lee");
    expect(email.html).toContain("Unsubscribe from daily reminders");
  });

  it("sends email through Resend with an idempotency key", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });
      return Response.json({ id: "email-1" });
    };

    const result = await sendResendEmail(
      {
        apiKey: "re_test",
        from: "Orbit <reminders@example.com>",
        to: "user@example.com",
        subject: "Hello",
        html: "<p>Hello</p>",
        text: "Hello",
        idempotencyKey: "daily-digest-user-1-2026-05-08",
      },
      fetchImpl,
    );

    expect(result.id).toBe("email-1");
    expect(calls[0]?.url).toBe("https://api.resend.com/emails");
    expect(calls[0]?.init.headers).toMatchObject({
      Authorization: "Bearer re_test",
      "Idempotency-Key": "daily-digest-user-1-2026-05-08",
    });
  });

  it("surfaces Resend failures", async () => {
    const fetchImpl = async () => Response.json({ message: "Bad API key" }, { status: 403 });

    await expect(
      sendResendEmail(
        {
          apiKey: "re_bad",
          from: "Orbit <reminders@example.com>",
          to: "user@example.com",
          subject: "Hello",
          html: "<p>Hello</p>",
          text: "Hello",
        },
        fetchImpl,
      ),
    ).rejects.toThrow("Bad API key");
  });
});
