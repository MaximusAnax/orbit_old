import { describe, expect, it } from "vitest";
import { createPreviewPatches, mergeExtractionPreview, previewFromExtraction } from "@/lib/orbit/preview";
import { parseSseBuffer, serializeSseEvent } from "@/lib/orbit/sse";
import { extractionResultSchema } from "@/lib/validators";

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

describe("streamed extraction helpers", () => {
  it("creates heuristic preview patches from raw text", () => {
    const patches = createPreviewPatches(
      "Met Priya Singh from Figma after the CMU alumni dinner. She leads product ops.",
    );

    expect(patches).not.toHaveLength(0);
    expect(patches[0]?.contact?.name).toContain("Priya");
  });

  it("merges preview patches into a stable preview state", () => {
    const merged = createPreviewPatches(
      "Met Priya Singh from Figma after the CMU alumni dinner. She leads product ops.",
    ).reduce((current, patch) => mergeExtractionPreview(current, patch), null);

    expect(merged?.contact.name).toBe("Priya Singh");
    expect(merged?.interaction.context).toContain("CMU alumni dinner");
  });

  it("serializes and parses SSE events without losing the payload", () => {
    const serialized =
      serializeSseEvent("meta", { captureId: "abc" }) +
      serializeSseEvent("final", { captureId: "abc", extraction: previewFromExtraction(extraction) });
    const parsed = parseSseBuffer(serialized);

    expect(parsed.remainder).toBe("");
    expect(parsed.events).toHaveLength(2);
    expect(parsed.events[0]?.event).toBe("meta");
    expect(parsed.events[1]?.event).toBe("final");
  });
});
