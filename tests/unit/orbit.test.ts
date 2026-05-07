import { describe, expect, it } from "vitest";
import { DEFAULT_FOLLOW_UP_DAYS } from "@/lib/constants";
import { calculateFollowUpAt, decideMatch, normalizeName, scoreProfileMatch } from "@/lib/orbit/normalize";
import { extractionResultSchema } from "@/lib/validators";
import type { ProfileRecord } from "@/lib/types";

const extraction = extractionResultSchema.parse({
  contact: {
    name: "Priya Singh",
    org: "Figma",
    role: "Product Ops Lead",
  },
  interaction: {
    summary: "Met Priya after a CMU alumni dinner and talked practical AI tools.",
    context: "CMU alumni dinner",
    sentiment: "positive",
  },
  tags: ["CMU", "AI Tools"],
  suggestedFollowUpDays: 10,
  matchHints: {
    normalizedName: "priya singh",
    orgHint: "figma",
  },
});

const profile = {
  id: "profile-1",
  user_id: "user-1",
  full_name: "Priya Singh",
  normalized_name: "priya singh",
  current_org: "Figma",
  job_role: "Product Ops Lead",
  metadata: {},
  last_interaction_at: null,
  next_follow_up_at: null,
  follow_up_interval_days: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
} satisfies ProfileRecord;

describe("orbit memory logic", () => {
  it("normalizes names consistently", () => {
    expect(normalizeName("  Priya Singh! ")).toBe("priya singh");
  });

  it("scores exact matches highly", () => {
    const candidate = scoreProfileMatch(profile, extraction);
    expect(candidate.score).toBeGreaterThanOrEqual(0.9);
  });

  it("auto-links a strong single candidate", () => {
    const decision = decideMatch([profile], extraction, { type: "auto" });
    expect(decision.mode).toBe("auto_link");
    expect(decision.selectedProfileId).toBe(profile.id);
  });

  it("uses the extracted follow-up window when present", () => {
    const followUpAt = calculateFollowUpAt(new Date("2026-05-07T00:00:00.000Z"), 10);
    expect(followUpAt).toBe("2026-05-17T00:00:00.000Z");
  });

  it("falls back to the default follow-up window", () => {
    const followUpAt = calculateFollowUpAt(new Date("2026-05-07T00:00:00.000Z"), null, null);
    const expected = new Date("2026-05-07T00:00:00.000Z");
    expected.setUTCDate(expected.getUTCDate() + DEFAULT_FOLLOW_UP_DAYS);
    expect(followUpAt).toBe(expected.toISOString());
  });
});
