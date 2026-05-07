import { NextResponse } from "next/server";
import { embedText } from "@/lib/orbit/ai";
import { trackServerEvent } from "@/lib/orbit/events";
import { serializeVector } from "@/lib/orbit/vector";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import type { SearchInteractionRow, SearchResultGroup } from "@/lib/types";
import { searchRequestSchema } from "@/lib/validators";

export async function POST(request: Request) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  }

  try {
    const body = await request.json();
    const { query } = searchRequestSchema.parse(body);
    const embedding = serializeVector(await embedText(query));

    const { data, error } = await supabase.rpc("search_interactions", {
      p_query_embedding: embedding,
      p_match_count: 8,
    });

    if (error) {
      throw error;
    }

    const grouped = new Map<string, SearchResultGroup>();

    for (const row of (data ?? []) as SearchInteractionRow[]) {
      const existing = grouped.get(row.profile_id);
      const match = {
        interactionId: row.interaction_id,
        summary: row.structured_summary,
        rawContent: row.raw_content,
        tags: row.tags,
        sentiment: row.sentiment,
        interactionDate: row.interaction_date,
        similarity: row.similarity,
      };

      if (!existing) {
        grouped.set(row.profile_id, {
          profileId: row.profile_id,
          fullName: row.full_name,
          currentOrg: row.current_org,
          currentRole: row.job_role,
          topSimilarity: row.similarity,
          matches: [match],
        });
        continue;
      }

      existing.matches.push(match);
      existing.topSimilarity = Math.max(existing.topSimilarity, row.similarity);
    }

    const results = Array.from(grouped.values()).sort((a, b) => b.topSimilarity - a.topSimilarity);

    await trackServerEvent(supabase, {
      eventName: "search_run",
      userId: user.id,
      payload: {
        queryLength: query.length,
        results: results.length,
      },
    });

    return NextResponse.json({ results });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unable to search memories." },
      { status: 400 },
    );
  }
}
