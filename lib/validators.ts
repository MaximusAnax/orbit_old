import { z } from "zod";

const sentimentSchema = z.enum(["positive", "neutral", "mixed", "negative"]);

export const extractionResultSchema = z.object({
  contact: z.object({
    name: z.string().min(1).max(120),
    org: z.string().max(120).nullable(),
    role: z.string().max(120).nullable(),
  }),
  interaction: z.object({
    summary: z.string().min(1).max(280),
    context: z.string().min(1).max(280),
    sentiment: sentimentSchema,
  }),
  tags: z.array(z.string().min(1).max(40)).max(8),
  suggestedFollowUpDays: z.number().int().min(1).max(180),
  matchHints: z.object({
    normalizedName: z.string().min(1).max(120),
    orgHint: z.string().max(120).nullable(),
  }),
});

export const extractRequestSchema = z.object({
  rawText: z.string().min(8).max(4_000),
});

export const commitResolutionSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("create_new") }),
  z.object({
    type: z.literal("link_existing"),
    profileId: z.string().uuid(),
  }),
  z.object({ type: z.literal("auto") }),
]);

export const commitMemorySchema = z.object({
  rawText: z.string().min(8).max(4_000),
  extraction: extractionResultSchema,
  resolution: commitResolutionSchema.optional(),
});

export const searchRequestSchema = z.object({
  query: z.string().min(2).max(240),
});

export const trackEventSchema = z.object({
  eventName: z.string().min(1).max(80),
  anonymousId: z.string().max(120).optional(),
  payload: z.record(z.string(), z.unknown()).optional(),
});

export type ExtractionResult = z.infer<typeof extractionResultSchema>;
export type CommitResolution = z.infer<typeof commitResolutionSchema>;
