import type { Sentiment } from "@/lib/types";
import type { ExtractionResult } from "@/lib/validators";

export interface ExtractionPreview {
  contact: {
    name: string | null;
    org: string | null;
    role: string | null;
  };
  interaction: {
    context: string | null;
    sentiment: Sentiment | null;
  };
  suggestedFollowUpDays: number | null;
  tags: string[];
}

export type ExtractionPreviewPatch = Partial<{
  contact: Partial<ExtractionPreview["contact"]>;
  interaction: Partial<ExtractionPreview["interaction"]>;
  suggestedFollowUpDays: number | null;
  tags: string[];
}>;

export function createEmptyExtractionPreview(): ExtractionPreview {
  return {
    contact: {
      name: null,
      org: null,
      role: null,
    },
    interaction: {
      context: null,
      sentiment: null,
    },
    suggestedFollowUpDays: null,
    tags: [],
  };
}

export function previewFromExtraction(extraction: ExtractionResult): ExtractionPreview {
  return {
    contact: {
      name: extraction.contact.name,
      org: extraction.contact.org,
      role: extraction.contact.role,
    },
    interaction: {
      context: extraction.interaction.context,
      sentiment: extraction.interaction.sentiment,
    },
    suggestedFollowUpDays: extraction.suggestedFollowUpDays,
    tags: extraction.tags,
  };
}

export function mergeExtractionPreview(
  current: ExtractionPreview | null,
  patch: ExtractionPreviewPatch,
): ExtractionPreview {
  return {
    contact: {
      ...(current?.contact ?? createEmptyExtractionPreview().contact),
      ...(patch.contact ?? {}),
    },
    interaction: {
      ...(current?.interaction ?? createEmptyExtractionPreview().interaction),
      ...(patch.interaction ?? {}),
    },
    suggestedFollowUpDays: patch.suggestedFollowUpDays ?? current?.suggestedFollowUpDays ?? null,
    tags: patch.tags ?? current?.tags ?? [],
  };
}

export function createPreviewPatches(rawText: string): ExtractionPreviewPatch[] {
  const preview = createHeuristicPreview(rawText);
  const patches: Array<ExtractionPreviewPatch | null> = [
    preview.contact.name ? { contact: { name: preview.contact.name } } : null,
    preview.contact.org || preview.contact.role
      ? {
          contact: {
            org: preview.contact.org,
            role: preview.contact.role,
          },
        }
      : null,
    preview.interaction.context || preview.suggestedFollowUpDays || preview.tags.length || preview.interaction.sentiment
      ? {
          interaction: preview.interaction,
          suggestedFollowUpDays: preview.suggestedFollowUpDays,
          tags: preview.tags,
        }
      : null,
  ];

  return patches.filter((patch): patch is ExtractionPreviewPatch => patch !== null);
}

function createHeuristicPreview(rawText: string): ExtractionPreview {
  const preview = createEmptyExtractionPreview();
  const nameMatch =
    rawText.match(/\b(?:met|with|about|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})/i) ??
    rawText.match(/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b/);
  const orgMatch = rawText.match(/\b(?:at|from)\s+([A-Z][A-Za-z0-9&.\- ]{1,60})/);
  const roleMatch = rawText.match(/\b(?:who is|she's|he's|they're|works as|as)\s+([^.,;\n]{2,60})/i);

  preview.contact.name = nameMatch?.[1]?.trim().replace(/\s+(?:from|at)$/i, "") || null;
  preview.contact.org = orgMatch?.[1]?.trim() || null;
  preview.contact.role = roleMatch?.[1]?.trim() || null;
  preview.interaction.context = rawText.split(/[.!?]/)[0]?.trim() || null;
  preview.interaction.sentiment = inferPreviewSentiment(rawText);
  preview.tags = Array.from(
    new Set(
      rawText
        .match(/#[a-z0-9_-]+|[A-Z][a-z]+(?:[A-Z][a-z]+)+/g)
        ?.map((token) => token.replace(/^#/, "").slice(0, 32)) ?? [],
    ),
  ).slice(0, 5);
  preview.suggestedFollowUpDays = /follow up|intro|investor|candidate|customer/i.test(rawText) ? 7 : 21;

  return preview;
}

function inferPreviewSentiment(rawText: string): Sentiment {
  const lower = rawText.toLowerCase();
  if (/(excited|great|warm|helpful|loved|promising|fun)/.test(lower)) return "positive";
  if (/(awkward|cold|stalled|frustrated|missed|upset)/.test(lower)) return "negative";
  if (/(but|however|mixed|unclear)/.test(lower)) return "mixed";
  return "neutral";
}
