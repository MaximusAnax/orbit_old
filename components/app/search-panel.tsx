"use client";

import Link from "next/link";
import { useDeferredValue, useEffect, useState } from "react";
import type { SearchResultGroup } from "@/lib/types";
import { formatLongDate } from "@/lib/utils";

async function trackSearchResultOpened(profileId: string) {
  await fetch("/api/events", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      eventName: "search_result_opened",
      payload: { profileId },
    }),
  }).catch(() => undefined);
}

export function SearchPanel() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultGroup[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    if (deferredQuery.trim().length < 2) {
      setResults([]);
      setError(null);
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setIsSearching(true);
      try {
        const response = await fetch("/api/search", {
          method: "POST",
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ query: deferredQuery }),
        });

        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error ?? "Search failed.");
        }

        setResults(payload.results ?? []);
        setError(null);
      } catch (caught) {
        if ((caught as Error).name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "Search failed.");
      } finally {
        setIsSearching(false);
      }
    }, 350);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [deferredQuery]);

  return (
    <section className="glass rounded-[2rem] p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Semantic recall</p>
          <h2 className="section-title mt-2 text-3xl">Search by vibe, event, or loose memory.</h2>
        </div>
        <div className="rounded-full border border-[var(--line)] px-3 py-1 text-xs text-[var(--muted)]">
          {isSearching ? "Searching..." : "Vector-backed"}
        </div>
      </div>

      <input
        className="mt-5 w-full rounded-[1.25rem] border border-[var(--line)] bg-white/78 px-4 py-3 outline-none focus:border-[var(--accent)]"
        placeholder="People I met at TartanHacks who care about ML infra"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {error ? <p className="mt-4 text-sm text-[#a54634]">{error}</p> : null}

      <div className="mt-5 grid gap-4">
        {results.map((result) => (
          <article key={result.profileId} className="rounded-[1.5rem] border border-[var(--line)] bg-white/75 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <Link
                  className="section-title text-2xl transition hover:text-[var(--accent)]"
                  href={`/profiles/${result.profileId}`}
                  onClick={() => {
                    void trackSearchResultOpened(result.profileId);
                  }}
                >
                  {result.fullName}
                </Link>
                <p className="mt-2 text-sm text-[var(--muted)]">
                  {[result.currentRole, result.currentOrg].filter(Boolean).join(" · ") || "Profile inferred from captured notes"}
                </p>
              </div>
              <span className="rounded-full bg-[var(--accent-soft)] px-3 py-1 text-xs font-semibold text-[var(--accent)]">
                {Math.round(result.topSimilarity * 100)}% match
              </span>
            </div>

            {result.whyMatched.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {result.whyMatched.map((reason) => (
                  <span key={reason} className="rounded-full border border-[var(--line)] bg-white/70 px-2.5 py-1 text-xs text-[var(--muted)]">
                    {reason}
                  </span>
                ))}
              </div>
            ) : null}

            <div className="mt-4 grid gap-3">
              {result.matches.slice(0, 2).map((match) => (
                <div key={match.interactionId} className="rounded-[1.15rem] border border-[var(--line)] bg-white p-4">
                  <div className="flex items-center justify-between gap-4 text-sm text-[var(--muted)]">
                    <span>{formatLongDate(match.interactionDate)}</span>
                    <span>{match.sentiment}</span>
                  </div>
                  <p className="mt-3 leading-7 text-[var(--foreground)]">{match.summary}</p>
                  {match.tags.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {match.tags.map((tag) => (
                        <span key={tag} className="rounded-full border border-[var(--line)] px-2.5 py-1 text-xs text-[var(--muted)]">
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </article>
        ))}

        {!results.length && query.trim().length >= 2 && !isSearching ? (
          <p className="rounded-[1.5rem] border border-dashed border-[var(--line)] px-4 py-6 text-center text-sm text-[var(--muted)]">
            No matches yet. Capture a few memories first, then search by context, place, or topic.
          </p>
        ) : null}
      </div>
    </section>
  );
}
