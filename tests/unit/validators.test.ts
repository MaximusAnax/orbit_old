import { describe, expect, it } from "vitest";
import { commitMemorySchema, extractRequestSchema, searchRequestSchema } from "@/lib/validators";

describe("request validation", () => {
  it("accepts valid extraction requests", () => {
    expect(() => extractRequestSchema.parse({ rawText: "Met Alex from Figma after dinner." })).not.toThrow();
  });

  it("rejects too-short search queries", () => {
    expect(() => searchRequestSchema.parse({ query: "a" })).toThrow();
  });

  it("accepts auto resolution on commit", () => {
    expect(() =>
      commitMemorySchema.parse({
        rawText: "Met Alex from Figma after dinner.",
        extraction: {
          contact: { name: "Alex", org: "Figma", role: "PM" },
          interaction: {
            summary: "Met Alex after dinner.",
            context: "Dinner",
            sentiment: "positive",
          },
          tags: ["Dinner"],
          suggestedFollowUpDays: 7,
          matchHints: {
            normalizedName: "alex",
            orgHint: "figma",
          },
        },
        resolution: { type: "auto" },
      }),
    ).not.toThrow();
  });
});
