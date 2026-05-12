"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export function FollowUpActions({ profileId, compact = false }: { profileId: string; compact?: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  async function act(body: Record<string, unknown>) {
    setError(null);
    const response = await fetch(`/api/profiles/${profileId}/follow-up`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();

    if (!response.ok) {
      setError(data.error ?? "Follow-up update failed.");
      return;
    }

    startTransition(() => router.refresh());
  }

  return (
    <div className={compact ? "mt-3" : "mt-5"}>
      <div className="flex flex-wrap gap-2">
        <button
          className="rounded-full bg-[var(--accent)] px-3 py-2 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
          disabled={isPending}
          onClick={() => void act({ action: "mark_contacted" })}
          type="button"
        >
          Mark contacted
        </button>
        <button
          className="rounded-full border border-[var(--line)] bg-white/70 px-3 py-2 text-xs font-semibold transition hover:bg-white disabled:opacity-50"
          disabled={isPending}
          onClick={() => void act({ action: "snooze", days: 7 })}
          type="button"
        >
          Snooze 7d
        </button>
        {!compact ? (
          <button
            className="rounded-full border border-[var(--line)] bg-white/70 px-3 py-2 text-xs font-semibold transition hover:bg-white disabled:opacity-50"
            disabled={isPending}
            onClick={() => void act({ action: "pause" })}
            type="button"
          >
            Pause
          </button>
        ) : null}
      </div>
      {error ? <p className="mt-2 text-xs text-[#a54634]">{error}</p> : null}
    </div>
  );
}
