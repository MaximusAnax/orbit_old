import { describe, expect, it } from "vitest";
import { advancedRecallFlags, buildEnrichmentMetadata, createOutreachDraft } from "@/lib/orbit/action-layer";
import type { InteractionRecord, ProfileRecord } from "@/lib/types";

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
  created_at: "2026-05-08T00:00:00.000Z",
  updated_at: "2026-05-08T00:00:00.000Z",
} satisfies ProfileRecord;

const interaction = {
  id: "interaction-1",
  profile_id: "profile-1",
  user_id: "user-1",
  raw_content: "Met Priya at the CMU alumni dinner.",
  structured_summary: "Talked about practical AI tools.",
  search_text: "Priya Figma AI",
  tags: ["AI"],
  sentiment: "positive",
  suggested_follow_up_days: 7,
  interaction_date: "2026-05-08T00:00:00.000Z",
  created_at: "2026-05-08T00:00:00.000Z",
} satisfies InteractionRecord;

describe("action layer", () => {
  it("builds enrichment metadata with provenance", () => {
    const enrichment = buildEnrichmentMetadata(profile);

    expect(enrichment.source).toBe("orbit_enrichment");
    expect(enrichment.suggestedSearch).toContain("Priya Singh");
  });

  it("creates a fallback outreach draft without an API key", async () => {
    const previous = process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_API_KEY;

    const draft = await createOutreachDraft(profile, [interaction]);

    process.env.OPENAI_API_KEY = previous;
    expect(draft).toContain("Hi Priya");
    expect(draft).toContain("practical AI tools");
  });

  it("keeps advanced recall features opt-in", () => {
    expect(advancedRecallFlags()).toEqual({
      graph: false,
      voiceSearch: false,
      externalSync: false,
    });
  });
});
