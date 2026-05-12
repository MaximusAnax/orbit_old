import OpenAI from "openai";
import { runReliableAiCall } from "@/lib/orbit/ai";
import type { InteractionRecord, ProfileRecord } from "@/lib/types";

export function buildEnrichmentMetadata(profile: ProfileRecord) {
  const slug = [profile.full_name, profile.current_org].filter(Boolean).join(" ").toLowerCase().replace(/[^a-z0-9]+/g, "-");

  return {
    source: "orbit_enrichment",
    confidence: profile.current_org ? "medium" : "low",
    suggestedSearch: [profile.full_name, profile.current_org, profile.job_role].filter(Boolean).join(" "),
    publicLinks: slug
      ? {
          linkedinSearch: `https://www.linkedin.com/search/results/all/?keywords=${encodeURIComponent(slug.replace(/-/g, " "))}`,
        }
      : {},
  };
}

export async function createOutreachDraft(profile: ProfileRecord, interactions: InteractionRecord[]) {
  const context = interactions
    .slice(0, 3)
    .map((interaction) => `- ${interaction.structured_summary}`)
    .join("\n");

  if (!process.env.OPENAI_API_KEY) {
    return `Hi ${profile.full_name.split(" ")[0] ?? profile.full_name},\n\nI was thinking about our conversation${context ? `, especially: ${interactions[0]?.structured_summary}` : ""} Would be lovely to reconnect soon.\n\nBest,`;
  }

  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const response = await runReliableAiCall(
    () =>
      client.responses.create({
        model: "gpt-4o-mini",
        input: [
          {
            role: "system",
            content: [
              {
                type: "input_text",
                text: "Write a concise, warm follow-up draft. Do not invent facts. Return only the message body.",
              },
            ],
          },
          {
            role: "user",
            content: [
              {
                type: "input_text",
                text: `Contact: ${profile.full_name}\nRole: ${profile.job_role ?? "unknown"}\nCompany: ${profile.current_org ?? "unknown"}\nRecent context:\n${context || "No interactions yet."}`,
              },
            ],
          },
        ],
      } as never),
    { operationName: "outreach draft generation", timeoutMs: 20_000, retries: 1 },
  );

  return response.output_text;
}

export function advancedRecallFlags() {
  return {
    graph: process.env.FEATURE_GRAPH_RECALL === "true",
    voiceSearch: process.env.FEATURE_VOICE_SEARCH === "true",
    externalSync: process.env.FEATURE_EXTERNAL_SYNC === "true",
  };
}
