"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LOCAL_STORAGE_KEYS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { ExtractionResult } from "@/lib/validators";
import type { MatchCandidate } from "@/lib/orbit/normalize";

interface PendingCommitPayload {
  captureId: string;
  rawText: string;
  extraction: ExtractionResult;
}

export function PostAuthCommitter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"idle" | "saving" | "needs_resolution">("idle");
  const [candidates, setCandidates] = useState<MatchCandidate[]>([]);
  const [pendingCommit, setPendingCommit] = useState<PendingCommitPayload | null>(null);
  const [pendingCaptureId, setPendingCaptureId] = useState<string | null>(null);

  const commit = useCallback(
    async (
      payload: PendingCommitPayload | null,
      captureId: string,
      resolution: { type: "auto" } | { type: "create_new" } | { type: "link_existing"; profileId: string },
    ) => {
      setStatus("saving");
      const captureStartedAtMs = Number(window.localStorage.getItem(LOCAL_STORAGE_KEYS.captureStartedAt) ?? Date.now());
      const anonymousId = window.localStorage.getItem(LOCAL_STORAGE_KEYS.anonymousId);

      const response = await fetch("/api/memories/commit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(anonymousId ? { "x-orbit-anonymous-id": anonymousId } : {}),
        },
        body: JSON.stringify({
          captureId,
          rawText: payload?.rawText,
          extraction: payload?.extraction,
          resolution,
          captureStartedAtMs,
        }),
      });

      const data = await response.json();

      if (response.status === 409 && data.requiresResolution) {
        setCandidates(data.candidates ?? []);
        setStatus("needs_resolution");
        return;
      }

      if (!response.ok) {
        setStatus("idle");
        router.replace("/app?error=commit");
        return;
      }

      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.pendingCommit);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftRawText);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftExtraction);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftCaptureId);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.captureStartedAt);
      router.push(`/profiles/${data.profileId}?saved=1`);
    },
    [router],
  );

  useEffect(() => {
    if (searchParams.get("postAuth") !== "1") return;

    const captureId = searchParams.get("captureId");
    const stored = window.localStorage.getItem(LOCAL_STORAGE_KEYS.pendingCommit);
    if (!stored && !captureId) {
      router.replace("/app");
      return;
    }

    const parsed = stored ? (JSON.parse(stored) as PendingCommitPayload) : null;
    const nextCaptureId = parsed?.captureId ?? captureId;
    if (!nextCaptureId) {
      router.replace("/app");
      return;
    }

    setPendingCommit(parsed);
    setPendingCaptureId(nextCaptureId);
    void commit(parsed, nextCaptureId, { type: "auto" });
  }, [router, searchParams, commit]);

  if (status === "idle") return null;

  return (
    <div className="glass mb-6 rounded-[1.75rem] p-5">
      {status === "saving" ? (
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Saving memory</p>
            <p className="mt-2 text-sm text-[var(--muted)]">Orbit is linking this capture to the right person and writing it into your timeline.</p>
          </div>
          <div className="h-9 w-9 animate-spin rounded-full border-2 border-[var(--accent-soft)] border-t-[var(--accent)]" />
        </div>
      ) : null}

      {status === "needs_resolution" && pendingCaptureId ? (
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Quick confirmation</p>
          <h3 className="section-title mt-2 text-2xl">This note might match someone you already know.</h3>
          <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
            Pick the existing profile if it’s the same person, or create a fresh one if this is a different contact.
          </p>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {candidates.map((candidate) => (
              <button
                key={candidate.profileId}
                className={cn(
                  "rounded-[1.25rem] border border-[var(--line)] bg-white/70 p-4 text-left transition hover:border-[var(--accent)] hover:bg-white",
                )}
                onClick={() => {
                  void commit(pendingCommit, pendingCaptureId, { type: "link_existing", profileId: candidate.profileId });
                }}
              >
                <div className="font-semibold text-[var(--foreground)]">{candidate.fullName}</div>
                <p className="mt-1 text-sm text-[var(--muted)]">
                  {[candidate.currentRole, candidate.currentOrg].filter(Boolean).join(" · ") || "Existing profile"}
                </p>
                <p className="mt-3 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">{Math.round(candidate.score * 100)}% confidence</p>
                <p className="mt-2 text-sm text-[var(--muted)]">{candidate.reason}</p>
              </button>
            ))}
          </div>

          <button
            className="mt-4 rounded-full border border-[var(--line)] px-4 py-2 text-sm font-semibold transition hover:bg-white/80"
            onClick={() => {
              void commit(pendingCommit, pendingCaptureId, { type: "create_new" });
            }}
          >
            Create a new profile instead
          </button>
        </div>
      ) : null}
    </div>
  );
}
