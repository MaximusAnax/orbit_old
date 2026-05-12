"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export function RelationshipActions({ profileId }: { profileId: string }) {
  const router = useRouter();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  async function post(path: string) {
    setError(null);
    const response = await fetch(`/api/profiles/${profileId}/${path}`, { method: "POST" });
    const payload = await response.json();

    if (!response.ok) {
      setError(payload.error ?? "Action failed.");
      return;
    }

    if (payload.draft) {
      setDraft(payload.draft);
      return;
    }

    startTransition(() => router.refresh());
  }

  return (
    <section className="mt-6 glass rounded-[1.75rem] p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Action layer</p>
          <h2 className="section-title mt-2 text-3xl">Next move</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="rounded-full border border-[var(--line)] bg-white/70 px-4 py-2 text-sm font-semibold transition hover:bg-white disabled:opacity-50"
            disabled={isPending}
            onClick={() => void post("enrich")}
            type="button"
          >
            Refresh context
          </button>
          <button
            className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
            disabled={isPending}
            onClick={() => void post("outreach-draft")}
            type="button"
          >
            Draft follow-up
          </button>
        </div>
      </div>

      {draft ? (
        <div className="mt-5 rounded-[1.25rem] border border-[var(--line)] bg-white/75 p-4">
          <p className="whitespace-pre-wrap text-sm leading-7 text-[var(--foreground)]">{draft}</p>
        </div>
      ) : null}
      {error ? <p className="mt-3 text-sm text-[#a54634]">{error}</p> : null}
    </section>
  );
}
