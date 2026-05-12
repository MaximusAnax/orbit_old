import { describe, expect, it } from "vitest";
import { commitMemorySchema, extractRequestSchema, searchRequestSchema } from "@/lib/validators";

describe("request validation", () => {
  it("accepts valid extraction requests", () => {
    expect(() =>
      extractRequestSchema.parse({
        rawText: "Met Alex from Figma after dinner.",
        captureId: "8be8ad0b-84cb-4db1-ac0f-fd841d525de4",
        stream: true,
      }),
    ).not.toThrow();
  });

  it("rejects too-short search queries", () => {
    expect(() => searchRequestSchema.parse({ query: "a" })).toThrow();
  });

  it("accepts auto resolution on commit", () => {
    expect(() =>
      commitMemorySchema.parse({
        captureId: "8be8ad0b-84cb-4db1-ac0f-fd841d525de4",
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

  it("accepts commit recovery using only the capture id", () => {
    expect(() =>
      commitMemorySchema.parse({
        captureId: "8be8ad0b-84cb-4db1-ac0f-fd841d525de4",
        resolution: { type: "auto" },
      }),
    ).not.toThrow();
  });

  it("rejects partial commit payloads that omit the extraction", () => {
    expect(() =>
      commitMemorySchema.parse({
        captureId: "8be8ad0b-84cb-4db1-ac0f-fd841d525de4",
        rawText: "Met Alex from Figma after dinner.",
      }),
    ).toThrow();
  });
});
