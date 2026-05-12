import { describe, expect, it } from "vitest";
import { createSearchCacheKey, groupAndRankSearchRows } from "@/lib/orbit/search";
import type { SearchInteractionRow } from "@/lib/types";

const baseRow = {
  interaction_id: "interaction-1",
  profile_id: "profile-1",
  full_name: "Priya Singh",
  current_org: "Figma",
  job_role: "Product Ops Lead",
  structured_summary: "Talked about practical AI tools and ML infra founders.",
  search_text: "Priya Figma Product Ops CMU ML infra",
  raw_content: "Met Priya at the CMU alumni dinner.",
  tags: ["CMU", "ML Infra"],
  sentiment: "positive",
  interaction_date: "2026-05-08T00:00:00.000Z",
  similarity: 0.7,
} satisfies SearchInteractionRow;

describe("search ranking", () => {
  it("adds structured explanations and boosts matching rows", () => {
    const results = groupAndRankSearchRows([baseRow], "figma ml infra");

    expect(results[0]?.whyMatched).toContain("Organization match");
    expect(results[0]?.whyMatched).toContain("Tag overlap");
    expect(results[0]?.topSimilarity).toBeGreaterThan(baseRow.similarity);
  });

  it("builds stable cache keys from equivalent query spacing", () => {
    expect(createSearchCacheKey("user-1", "  ML   Infra ")).toBe(createSearchCacheKey("user-1", "ml infra"));
  });
});
