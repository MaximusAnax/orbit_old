"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { LOCAL_STORAGE_KEYS } from "@/lib/constants";
import { PreviewCard } from "@/components/landing/preview-card";
import type { ExtractionResult } from "@/lib/validators";

interface PendingCommitPayload {
  rawText: string;
  extraction: ExtractionResult;
}

function getAnonymousId() {
  if (typeof window === "undefined") return "";

  const existing = window.localStorage.getItem(LOCAL_STORAGE_KEYS.anonymousId);
  if (existing) return existing;

  const generated = `anon_${crypto.randomUUID()}`;
  window.localStorage.setItem(LOCAL_STORAGE_KEYS.anonymousId, generated);
  return generated;
}

async function trackEvent(eventName: string, payload?: Record<string, unknown>) {
  const anonymousId = getAnonymousId();
  await fetch("/api/events", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ eventName, payload, anonymousId }),
  }).catch(() => undefined);
}

export function CaptureExperience({ isAuthenticated }: { isAuthenticated: boolean }) {
  const router = useRouter();
  const [rawText, setRawText] = useState("");
  const [extraction, setExtraction] = useState<ExtractionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revealedCount, setRevealedCount] = useState(0);
  const [isPending, startTransition] = useTransition();
  const startedRef = useRef(false);

  useEffect(() => {
    const savedText = window.localStorage.getItem(LOCAL_STORAGE_KEYS.draftRawText);
    const savedExtraction = window.localStorage.getItem(LOCAL_STORAGE_KEYS.draftExtraction);

    if (savedText) setRawText(savedText);
    if (savedExtraction) {
      try {
        setExtraction(JSON.parse(savedExtraction));
      } catch {
        window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftExtraction);
      }
    }
  }, []);

  useEffect(() => {
    if (!extraction) {
      setRevealedCount(0);
      return;
    }

    setRevealedCount(1);
    const timers = [1, 2, 3, 4].map((offset, index) =>
      window.setTimeout(() => setRevealedCount(offset + 1), 180 + index * 120),
    );

    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [extraction]);

  useEffect(() => {
    window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftRawText, rawText);
    if (rawText && !startedRef.current) {
      startedRef.current = true;
      void trackEvent("capture_started", { length: rawText.length });
    }
  }, [rawText]);

  useEffect(() => {
    if (rawText.trim().length < 8) {
      setExtraction(null);
      setError(null);
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      startTransition(async () => {
        try {
          const response = await fetch("/api/extract", {
            method: "POST",
            signal: controller.signal,
            headers: {
              "Content-Type": "application/json",
              "x-orbit-anonymous-id": getAnonymousId(),
            },
            body: JSON.stringify({ rawText }),
          });

          const payload = await response.json();
          if (!response.ok) {
            throw new Error(payload.error ?? "Orbit couldn’t extract that note.");
          }

          setExtraction(payload.extraction);
          setError(null);
          window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftExtraction, JSON.stringify(payload.extraction));
        } catch (caught) {
          if ((caught as Error).name === "AbortError") return;
          setError(caught instanceof Error ? caught.message : "Orbit couldn’t extract that note.");
          void trackEvent("extract_failed");
        }
      });
    }, 650);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [rawText]);

  const canSave = useMemo(() => Boolean(rawText.trim() && extraction), [rawText, extraction]);

  async function saveDirectly(payload: PendingCommitPayload) {
    const response = await fetch("/api/memories/commit", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-orbit-anonymous-id": getAnonymousId(),
      },
      body: JSON.stringify({
        rawText: payload.rawText,
        extraction: payload.extraction,
        resolution: { type: "auto" },
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error ?? "Orbit couldn’t save that memory.");
    }

    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.pendingCommit);
    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftRawText);
    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftExtraction);
    router.push(`/profiles/${data.profileId}?saved=1`);
  }

  async function handleSave() {
    if (!extraction) return;

    const payload = { rawText, extraction };

    window.localStorage.setItem(LOCAL_STORAGE_KEYS.pendingCommit, JSON.stringify(payload));
    await trackEvent("oauth_started", { authenticated: isAuthenticated });

    if (isAuthenticated) {
      await saveDirectly(payload);
      return;
    }

    window.location.href = "/auth/login";
  }

  return (
    <motion.section
      className="grid gap-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
    >
      <div className="glass rounded-[2rem] p-6 lg:p-8">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Capture before auth</p>
            <h2 className="section-title mt-2 text-3xl">Paste the rough note.</h2>
          </div>
          <div className="rounded-full border border-[var(--line)] px-3 py-1 text-xs text-[var(--muted)]">
            {isPending ? "Extracting..." : "Private preview"}
          </div>
        </div>

        <textarea
          className="min-h-[220px] w-full rounded-[1.75rem] border border-[var(--line)] bg-white/78 px-5 py-4 text-base leading-7 text-[var(--foreground)] outline-none transition focus:border-[var(--accent)]"
          placeholder="Met Alex from Figma after the hackathon dinner..."
          value={rawText}
          onChange={(event) => setRawText(event.target.value)}
        />

        <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className="max-w-xl text-sm leading-6 text-[var(--muted)]">
            Orbit stores the draft in your browser until you decide to save it. Sign-in only happens when you want the memory committed to your account.
          </p>
          <button
            className="inline-flex items-center justify-center rounded-full bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canSave}
            onClick={() => {
              void handleSave();
            }}
          >
            Save to my memory
          </button>
        </div>

        {error ? <p className="mt-4 text-sm text-[#a54634]">{error}</p> : null}
      </div>

      <PreviewCard extraction={extraction} revealedCount={revealedCount} />
    </motion.section>
  );
}
