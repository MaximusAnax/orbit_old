"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, Clock, Pause } from "lucide-react";
import { Button } from "@/components/ui/primitives";

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
        <Button
          className="min-h-8 px-3 py-1.5 text-xs"
          tone="primary"
          disabled={isPending}
          onClick={() => void act({ action: "mark_contacted" })}
          type="button"
        >
          <Check aria-hidden="true" className="size-3.5" />
          Mark contacted
        </Button>
        <Button
          className="min-h-8 px-3 py-1.5 text-xs"
          disabled={isPending}
          onClick={() => void act({ action: "snooze", days: 7 })}
          type="button"
        >
          <Clock aria-hidden="true" className="size-3.5" />
          Snooze 7d
        </Button>
        {!compact ? (
          <Button
            className="min-h-8 px-3 py-1.5 text-xs"
            disabled={isPending}
            onClick={() => void act({ action: "pause" })}
            type="button"
          >
            <Pause aria-hidden="true" className="size-3.5" />
            Pause
          </Button>
        ) : null}
      </div>
      {error ? <p className="mt-2 text-xs text-[#a54634]">{error}</p> : null}
    </div>
  );
}
