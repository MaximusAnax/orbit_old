"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { Bell, PauseCircle, Save } from "lucide-react";
import type { NotificationPreferenceRecord } from "@/lib/types";
import { Badge, Button, Panel, TextInput } from "@/components/ui/primitives";

export function NotificationSettings() {
  const [preferences, setPreferences] = useState<NotificationPreferenceRecord | null>(null);
  const [dailyDigestEnabled, setDailyDigestEnabled] = useState(true);
  const [timezone, setTimezone] = useState("UTC");
  const [pausedUntil, setPausedUntil] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let isMounted = true;
    void fetch("/api/notification-preferences")
      .then((response) => response.json())
      .then((payload) => {
        if (!isMounted) return;
        const next = payload.preferences as NotificationPreferenceRecord;
        setPreferences(next);
        setDailyDigestEnabled(next.daily_digest_enabled);
        setTimezone(next.timezone);
        setPausedUntil(next.paused_until);
      })
      .catch(() => {
        if (isMounted) setError("Notification settings could not be loaded.");
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const pauseDateValue = useMemo(() => (pausedUntil ? pausedUntil.slice(0, 10) : ""), [pausedUntil]);

  function save(nextPausedUntil = pausedUntil) {
    setError(null);
    setMessage(null);
    startTransition(() => {
      void (async () => {
        const response = await fetch("/api/notification-preferences", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dailyDigestEnabled,
            timezone,
            pausedUntil: nextPausedUntil,
          }),
        });
        const payload = await response.json();

        if (!response.ok) {
          setError(payload.error ?? "Notification settings could not be saved.");
          return;
        }

        setPreferences(payload.preferences);
        setMessage("Notification settings saved.");
      })();
    });
  }

  function updatePauseDate(value: string) {
    if (!value) {
      setPausedUntil(null);
      return;
    }
    setPausedUntil(new Date(`${value}T12:00:00.000Z`).toISOString());
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
      <Panel className="p-5">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-8 items-center justify-center rounded-[var(--radius)] bg-[var(--accent-soft)] text-[var(--accent)]">
            <Bell aria-hidden="true" className="size-4" />
          </span>
          <p className="eyebrow">Notifications</p>
        </div>
        <h1 className="section-title mt-2 text-3xl font-black">Digest settings</h1>
        <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
          Control the reminders Orbit is allowed to send. The product should nudge thoughtfully, never nag.
        </p>
        <div className="mt-5 grid gap-3">
          <div className="rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-4">
            <p className="text-sm font-bold">Current state</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge tone={dailyDigestEnabled ? "success" : "neutral"}>{dailyDigestEnabled ? "Digest on" : "Digest off"}</Badge>
              {pausedUntil ? <Badge tone="warning">Paused until {new Date(pausedUntil).toLocaleDateString()}</Badge> : <Badge>No pause</Badge>}
            </div>
          </div>
        </div>
      </Panel>

      <Panel className="p-5">
        {!preferences && !error ? <p className="text-sm text-[var(--muted)]">Loading settings...</p> : null}

        <div className="grid gap-5">
          <label className="flex items-center justify-between gap-4 rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-4">
            <span>
              <span className="block text-sm font-bold text-[var(--foreground)]">Daily digest</span>
              <span className="mt-1 block text-sm leading-6 text-[var(--muted)]">One grouped reminder email when follow-ups are due.</span>
            </span>
            <input
              checked={dailyDigestEnabled}
              className="size-5 accent-[var(--accent)]"
              onChange={(event) => setDailyDigestEnabled(event.target.checked)}
              type="checkbox"
            />
          </label>

          <label className="grid gap-2 text-sm font-bold text-[var(--foreground)]">
            Timezone
            <TextInput value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="America/New_York" />
          </label>

          <label className="grid gap-2 text-sm font-bold text-[var(--foreground)]">
            Pause until
            <TextInput value={pauseDateValue} onChange={(event) => updatePauseDate(event.target.value)} type="date" />
          </label>

          {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}
          {message ? <p className="text-sm text-[var(--success)]">{message}</p> : null}

          <div className="flex flex-wrap gap-3">
            <Button disabled={isPending} onClick={() => save()} tone="primary" type="button">
              <Save aria-hidden="true" className="size-4" />
              Save settings
            </Button>
            <Button
              disabled={isPending}
              onClick={() => {
                setPausedUntil(null);
                save(null);
              }}
              type="button"
            >
              <PauseCircle aria-hidden="true" className="size-4" />
              Clear pause
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  );
}
