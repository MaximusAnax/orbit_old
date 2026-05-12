import { createHmac, timingSafeEqual } from "node:crypto";
import type { NotificationPreferenceRecord, ProfileRecord } from "@/lib/types";

export const UNSUBSCRIBE_TOKEN_TTL_MS = 1000 * 60 * 60 * 24 * 30;

interface PreferenceLike {
  daily_digest_enabled?: boolean | null;
  paused_until?: string | null;
  unsubscribed_at?: string | null;
}

export function evaluateNotificationPreference(
  preference: PreferenceLike | null | undefined,
  now = new Date(),
) {
  if (preference?.unsubscribed_at) {
    return { allowed: false, skippedReason: "unsubscribed" } as const;
  }

  if (preference?.daily_digest_enabled === false) {
    return { allowed: false, skippedReason: "daily_digest_disabled" } as const;
  }

  if (preference?.paused_until && new Date(preference.paused_until).getTime() > now.getTime()) {
    return { allowed: false, skippedReason: "paused" } as const;
  }

  return { allowed: true, skippedReason: null } as const;
}

function signatureFor(userId: string, expiresAtMs: number, secret: string) {
  return createHmac("sha256", secret).update(`${userId}.${expiresAtMs}`).digest("hex");
}

export function createUnsubscribeToken(userId: string, secret: string, now = new Date()) {
  const expiresAtMs = now.getTime() + UNSUBSCRIBE_TOKEN_TTL_MS;
  return `${expiresAtMs}.${signatureFor(userId, expiresAtMs, secret)}`;
}

export function verifyUnsubscribeToken(userId: string, token: string, secret: string, now = new Date()) {
  const [expiresAtRaw, signature] = token.split(".");
  const expiresAtMs = Number(expiresAtRaw);

  if (!Number.isFinite(expiresAtMs) || !signature || expiresAtMs < now.getTime()) {
    return false;
  }

  const expected = signatureFor(userId, expiresAtMs, secret);
  const expectedBuffer = Buffer.from(expected);
  const actualBuffer = Buffer.from(signature);

  return expectedBuffer.length === actualBuffer.length && timingSafeEqual(expectedBuffer, actualBuffer);
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function buildReminderEmail(input: {
  profiles: ProfileRecord[];
  appUrl: string;
  unsubscribeUrl: string;
}) {
  const subject = input.profiles.length === 1
    ? "One warm follow-up for today"
    : `${input.profiles.length} warm follow-ups for today`;

  const lines = input.profiles.map((profile) => {
    const role = [profile.job_role, profile.current_org].filter(Boolean).join(" at ");
    return role ? `${profile.full_name} (${role})` : profile.full_name;
  });

  const htmlItems = lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("");
  const textItems = lines.map((line) => `- ${line}`).join("\n");

  return {
    subject,
    html: [
      "<p>A few relationships are ready for a thoughtful follow-up:</p>",
      `<ul>${htmlItems}</ul>`,
      `<p><a href="${escapeHtml(input.appUrl)}">Open Orbit</a></p>`,
      `<p style="color:#6b7280;font-size:12px;"><a href="${escapeHtml(input.unsubscribeUrl)}">Unsubscribe from daily reminders</a></p>`,
    ].join(""),
    text: [
      "A few relationships are ready for a thoughtful follow-up:",
      "",
      textItems,
      "",
      `Open Orbit: ${input.appUrl}`,
      `Unsubscribe: ${input.unsubscribeUrl}`,
    ].join("\n"),
  };
}

export function mapPreferenceByUserId(preferences: NotificationPreferenceRecord[]) {
  return new Map(preferences.map((preference) => [preference.user_id, preference]));
}
