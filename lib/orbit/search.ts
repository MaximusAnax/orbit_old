import type { SearchInteractionRow, SearchResultGroup } from "@/lib/types";

const searchCache = new Map<string, { expiresAt: number; results: SearchResultGroup[] }>();
const CACHE_TTL_MS = 5 * 60 * 1000;

export function groupAndRankSearchRows(rows: SearchInteractionRow[], query: string): SearchResultGroup[] {
  const queryTokens = tokenize(query);
  const grouped = new Map<string, SearchResultGroup>();

  for (const row of rows) {
    const boosts = calculateStructuredBoosts(row, queryTokens);
    const hybridSimilarity = Math.min(0.99, Number((row.similarity + boosts.score).toFixed(4)));
    const existing = grouped.get(row.profile_id);
    const match = {
      interactionId: row.interaction_id,
      summary: row.structured_summary,
      rawContent: row.raw_content,
      tags: row.tags,
      sentiment: row.sentiment,
      interactionDate: row.interaction_date,
      similarity: hybridSimilarity,
    };

    if (!existing) {
      grouped.set(row.profile_id, {
        profileId: row.profile_id,
        fullName: row.full_name,
        currentOrg: row.current_org,
        currentRole: row.job_role,
        topSimilarity: hybridSimilarity,
        whyMatched: boosts.reasons.length ? boosts.reasons : ["Semantic memory match"],
        matches: [match],
      });
      continue;
    }

    existing.matches.push(match);
    existing.topSimilarity = Math.max(existing.topSimilarity, hybridSimilarity);
    existing.whyMatched = Array.from(new Set([...existing.whyMatched, ...boosts.reasons])).slice(0, 4);
  }

  return Array.from(grouped.values()).sort((a, b) => b.topSimilarity - a.topSimilarity);
}

export async function getCachedSearchResults(cacheKey: string) {
  const upstash = await getUpstash<SearchResultGroup[]>(cacheKey);
  if (upstash) return upstash;

  const cached = searchCache.get(cacheKey);
  if (!cached || cached.expiresAt < Date.now()) {
    searchCache.delete(cacheKey);
    return null;
  }

  return cached.results;
}

export async function setCachedSearchResults(cacheKey: string, results: SearchResultGroup[]) {
  searchCache.set(cacheKey, {
    expiresAt: Date.now() + CACHE_TTL_MS,
    results,
  });

  await setUpstash(cacheKey, results);
}

export function createSearchCacheKey(userId: string, query: string) {
  return `search:${userId}:${query.trim().toLowerCase().replace(/\s+/g, " ")}`;
}

function calculateStructuredBoosts(row: SearchInteractionRow, queryTokens: Set<string>) {
  let score = 0;
  const reasons: string[] = [];
  const tags = row.tags.map((tag) => tag.toLowerCase());
  const orgTokens = tokenize(row.current_org ?? "");
  const roleTokens = tokenize(row.job_role ?? "");
  const textTokens = tokenize([row.structured_summary, row.raw_content, row.search_text ?? ""].join(" "));

  if (tags.some((tag) => queryTokens.has(tag) || [...queryTokens].some((token) => tag.includes(token)))) {
    score += 0.08;
    reasons.push("Tag overlap");
  }

  if (hasOverlap(queryTokens, orgTokens)) {
    score += 0.07;
    reasons.push("Organization match");
  }

  if (hasOverlap(queryTokens, roleTokens)) {
    score += 0.05;
    reasons.push("Role match");
  }

  if (hasOverlap(queryTokens, textTokens)) {
    score += 0.04;
    reasons.push("Memory text overlap");
  }

  return { score, reasons };
}

function hasOverlap(left: Set<string>, right: Set<string>) {
  for (const value of left) {
    if (right.has(value)) return true;
  }

  return false;
}

function tokenize(value: string) {
  return new Set(
    value
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((token) => token.length > 1),
  );
}

async function getUpstash<T>(key: string) {
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;

  try {
    const response = await fetch(`${url}/get/${encodeURIComponent(key)}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    const payload = (await response.json()) as { result?: string | null };
    return payload.result ? (JSON.parse(payload.result) as T) : null;
  } catch {
    return null;
  }
}

async function setUpstash(key: string, value: SearchResultGroup[]) {
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return;

  try {
    await fetch(`${url}/set/${encodeURIComponent(key)}/${encodeURIComponent(JSON.stringify(value))}?EX=300`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    // Cache failures should never block recall.
  }
}
