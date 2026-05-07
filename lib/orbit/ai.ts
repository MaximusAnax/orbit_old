import OpenAI from "openai";
import { EMBEDDING_MODEL, EXTRACTION_MODEL, DEFAULT_FOLLOW_UP_DAYS } from "@/lib/constants";
import { extractionResultSchema, type ExtractionResult } from "@/lib/validators";
import { normalizeName, normalizeOrg } from "@/lib/orbit/normalize";

const extractionJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["contact", "interaction", "tags", "suggestedFollowUpDays", "matchHints"],
  properties: {
    contact: {
      type: "object",
      additionalProperties: false,
      required: ["name", "org", "role"],
      properties: {
        name: { type: "string" },
        org: { type: ["string", "null"] },
        role: { type: ["string", "null"] },
      },
    },
    interaction: {
      type: "object",
      additionalProperties: false,
      required: ["summary", "context", "sentiment"],
      properties: {
        summary: { type: "string" },
        context: { type: "string" },
        sentiment: {
          type: "string",
          enum: ["positive", "neutral", "mixed", "negative"],
        },
      },
    },
    tags: {
      type: "array",
      items: { type: "string" },
    },
    suggestedFollowUpDays: { type: "integer" },
    matchHints: {
      type: "object",
      additionalProperties: false,
      required: ["normalizedName", "orgHint"],
      properties: {
        normalizedName: { type: "string" },
        orgHint: { type: ["string", "null"] },
      },
    },
  },
} as const;

function getOpenAIClient() {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) return null;
  return new OpenAI({ apiKey });
}

function inferSentiment(rawText: string): ExtractionResult["interaction"]["sentiment"] {
  const lower = rawText.toLowerCase();
  if (/(excited|great|warm|helpful|loved|promising|fun)/.test(lower)) return "positive";
  if (/(awkward|cold|stalled|frustrated|missed|upset)/.test(lower)) return "negative";
  if (/(but|however|mixed|unclear)/.test(lower)) return "mixed";
  return "neutral";
}

function heuristicallyExtract(rawText: string): ExtractionResult {
  const nameMatch =
    rawText.match(/\b(?:met|with|about|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})/) ??
    rawText.match(/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b/);
  const orgMatch = rawText.match(/\b(?:at|from)\s+([A-Z][A-Za-z0-9&.\- ]{1,60})/);
  const roleMatch = rawText.match(/\b(?:who is|she's|he's|they're|works as|as)\s+([^.,;\n]{2,60})/i);

  const name = nameMatch?.[1]?.trim() || "Unknown contact";
  const org = orgMatch?.[1]?.trim() || null;
  const role = roleMatch?.[1]?.trim() || null;
  const context = rawText.split(/[.!?]/)[0]?.trim() || rawText.trim();
  const tags = Array.from(
    new Set(
      rawText
        .match(/#[a-z0-9_-]+|[A-Z][a-z]+(?:[A-Z][a-z]+)+/g)
        ?.map((token) => token.replace(/^#/, "").slice(0, 32)) ?? [],
    ),
  ).slice(0, 5);

  return extractionResultSchema.parse({
    contact: { name, org, role },
    interaction: {
      summary: rawText.trim().slice(0, 220),
      context,
      sentiment: inferSentiment(rawText),
    },
    tags,
    suggestedFollowUpDays: /follow up|intro|investor|candidate|customer/i.test(rawText)
      ? 7
      : DEFAULT_FOLLOW_UP_DAYS,
    matchHints: {
      normalizedName: normalizeName(name),
      orgHint: normalizeOrg(org),
    },
  });
}

export async function extractMemory(rawText: string) {
  const client = getOpenAIClient();

  if (!client) {
    return heuristicallyExtract(rawText);
  }

  const response = await client.responses.create({
    model: EXTRACTION_MODEL,
    input: [
      {
        role: "system",
        content: [
          {
            type: "input_text",
            text:
              "Extract contact memory details from the user's note. Keep tags short, infer a humane follow-up window, and return only valid JSON that matches the schema.",
          },
        ],
      },
      {
        role: "user",
        content: [{ type: "input_text", text: rawText }],
      },
    ],
    text: {
      format: {
        type: "json_schema",
        name: "orbit_memory_extraction",
        strict: true,
        schema: extractionJsonSchema,
      },
    },
  } as never);

  const parsed = JSON.parse(response.output_text);
  return extractionResultSchema.parse({
    ...parsed,
    matchHints: {
      normalizedName: normalizeName(parsed.contact.name),
      orgHint: normalizeOrg(parsed.contact.org),
    },
  });
}

function pseudoEmbedding(text: string, dimensions = 1536) {
  const vector = new Array<number>(dimensions).fill(0);

  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    const slot = index % dimensions;
    vector[slot] += ((code % 97) - 48) / 100;
  }

  const magnitude = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0)) || 1;
  return vector.map((value) => Number((value / magnitude).toFixed(6)));
}

export async function embedText(text: string) {
  const client = getOpenAIClient();

  if (!client) {
    return pseudoEmbedding(text);
  }

  const response = await client.embeddings.create({
    model: EMBEDDING_MODEL,
    input: text,
  });

  return response.data[0]?.embedding ?? pseudoEmbedding(text);
}
