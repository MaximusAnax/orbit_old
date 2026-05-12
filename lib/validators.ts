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
  captureId: z.string().uuid().optional(),
  stream: z.boolean().optional(),
  captureStartedAtMs: z.number().int().nonnegative().optional(),
});

export const commitResolutionSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("create_new") }),
  z.object({
    type: z.literal("link_existing"),
    profileId: z.string().uuid(),
  }),
  z.object({ type: z.literal("auto") }),
]);

export const commitMemorySchema = z
  .object({
    captureId: z.string().uuid(),
    rawText: z.string().min(8).max(4_000).optional(),
    extraction: extractionResultSchema.optional(),
    resolution: commitResolutionSchema.optional(),
    captureStartedAtMs: z.number().int().nonnegative().optional(),
  })
  .refine((value) => (value.rawText ? Boolean(value.extraction) : !value.extraction), {
    message: "rawText and extraction must be provided together.",
    path: ["extraction"],
  });

export const searchRequestSchema = z.object({
  query: z.string().min(2).max(240),
});

export const profileUpdateSchema = z.object({
  fullName: z.string().min(1).max(120).optional(),
  currentOrg: z.string().max(120).nullable().optional(),
  jobRole: z.string().max(120).nullable().optional(),
  followUpIntervalDays: z.number().int().min(1).max(180).nullable().optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

export const followUpActionSchema = z.discriminatedUnion("action", [
  z.object({
    action: z.literal("mark_contacted"),
    note: z.string().max(500).optional(),
  }),
  z.object({
    action: z.literal("snooze"),
    days: z.number().int().min(1).max(90),
  }),
  z.object({
    action: z.literal("set_cadence"),
    days: z.number().int().min(1).max(180),
  }),
  z.object({
    action: z.literal("pause"),
  }),
]);

export const trackEventSchema = z.object({
  eventName: z.string().min(1).max(80),
  anonymousId: z.string().max(120).optional(),
  payload: z.record(z.string(), z.unknown()).optional(),
});

export const notificationPreferenceUpdateSchema = z.object({
  dailyDigestEnabled: z.boolean().optional(),
  pausedUntil: z.string().datetime().nullable().optional(),
  timezone: z.string().min(1).max(80).optional(),
});

export type ExtractionResult = z.infer<typeof extractionResultSchema>;
export type CommitResolution = z.infer<typeof commitResolutionSchema>;
export type ProfileUpdateInput = z.infer<typeof profileUpdateSchema>;
export type FollowUpActionInput = z.infer<typeof followUpActionSchema>;
export type NotificationPreferenceUpdateInput = z.infer<typeof notificationPreferenceUpdateSchema>;
