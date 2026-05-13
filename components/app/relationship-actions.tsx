"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { PenLine, RefreshCw } from "lucide-react";
import { Button, Panel } from "@/components/ui/primitives";

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
    <Panel className="mt-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Action layer</p>
          <h2 className="section-title mt-1 text-2xl font-black">Next move</h2>
          <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted)]">
            Refresh context, then draft a specific follow-up that stays grounded in saved memories.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={isPending}
            onClick={() => void post("enrich")}
            type="button"
          >
            <RefreshCw aria-hidden="true" className="size-4" />
            Refresh context
          </Button>
          <Button
            tone="primary"
            disabled={isPending}
            onClick={() => void post("outreach-draft")}
            type="button"
          >
            <PenLine aria-hidden="true" className="size-4" />
            Draft follow-up
          </Button>
        </div>
      </div>

      {draft ? (
        <div className="mt-5 rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-4">
          <p className="text-sm font-bold text-[var(--foreground)]">Draft</p>
          <p className="whitespace-pre-wrap text-sm leading-7 text-[var(--foreground)]">{draft}</p>
        </div>
      ) : null}
      {error ? <p className="mt-3 text-sm text-[#a54634]">{error}</p> : null}
    </Panel>
  );
}
