import { NextResponse } from "next/server";
import { embedText } from "@/lib/orbit/ai";
import { trackServerEvent } from "@/lib/orbit/events";
import {
  createSearchCacheKey,
  getCachedSearchResults,
  groupAndRankSearchRows,
  setCachedSearchResults,
} from "@/lib/orbit/search";
import { serializeVector } from "@/lib/orbit/vector";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import type { SearchInteractionRow } from "@/lib/types";
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
    const cacheKey = createSearchCacheKey(user.id, query);
    const cachedResults = await getCachedSearchResults(cacheKey);

    if (cachedResults) {
      await trackServerEvent(supabase, {
        eventName: "search_run",
        userId: user.id,
        payload: {
          queryLength: query.length,
          results: cachedResults.length,
          cacheHit: true,
        },
      });

      return NextResponse.json({ results: cachedResults, cacheHit: true });
    }

    const embedding = serializeVector(await embedText(query));

    const { data, error } = await supabase.rpc("search_interactions", {
      p_query_embedding: embedding,
      p_match_count: 8,
    });

    if (error) {
      throw error;
    }

    const results = groupAndRankSearchRows((data ?? []) as SearchInteractionRow[], query);
    await setCachedSearchResults(cacheKey, results);

    await trackServerEvent(supabase, {
      eventName: "search_run",
      userId: user.id,
      payload: {
        queryLength: query.length,
        results: results.length,
        cacheHit: false,
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
