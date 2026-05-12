"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { LOCAL_STORAGE_KEYS } from "@/lib/constants";
import {
  createEmptyExtractionPreview,
  mergeExtractionPreview,
  previewFromExtraction,
  type ExtractionPreview,
} from "@/lib/orbit/preview";
import { parseSseBuffer } from "@/lib/orbit/sse";
import { PreviewCard } from "@/components/landing/preview-card";
import type { ExtractionResult } from "@/lib/validators";

interface PendingCommitPayload {
  captureId: string;
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
  const [preview, setPreview] = useState<ExtractionPreview | null>(null);
  const [captureId, setCaptureId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isProcessingUpload, setIsProcessingUpload] = useState(false);

  useEffect(() => {
    const savedText = window.localStorage.getItem(LOCAL_STORAGE_KEYS.draftRawText);
    const savedExtraction = window.localStorage.getItem(LOCAL_STORAGE_KEYS.draftExtraction);
    const savedCaptureId = window.localStorage.getItem(LOCAL_STORAGE_KEYS.draftCaptureId);

    if (savedText) setRawText(savedText);
    if (savedCaptureId) setCaptureId(savedCaptureId);
    if (savedExtraction) {
      try {
        const parsed = JSON.parse(savedExtraction) as ExtractionResult;
        setExtraction(parsed);
        setPreview(previewFromExtraction(parsed));
      } catch {
        window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftExtraction);
      }
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftRawText, rawText);

    if (!rawText.trim()) {
      setCaptureId(null);
      setExtraction(null);
      setPreview(null);
      setError(null);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftRawText);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftExtraction);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftCaptureId);
      window.localStorage.removeItem(LOCAL_STORAGE_KEYS.captureStartedAt);
      return;
    }

    if (!captureId) {
      const nextCaptureId = crypto.randomUUID();
      setCaptureId(nextCaptureId);
      window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftCaptureId, nextCaptureId);
      window.localStorage.setItem(LOCAL_STORAGE_KEYS.captureStartedAt, String(Date.now()));
      void trackEvent("capture_started", { captureId: nextCaptureId, length: rawText.length });
    }
  }, [captureId, rawText]);

  useEffect(() => {
    if (rawText.trim().length < 8) {
      setExtraction(null);
      setPreview(rawText.trim() ? createEmptyExtractionPreview() : null);
      setError(null);
      setIsExtracting(false);
      return;
    }

    if (!captureId) {
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setIsExtracting(true);
      setExtraction(null);
      setPreview(createEmptyExtractionPreview());
      try {
        const captureStartedAtMs = Number(window.localStorage.getItem(LOCAL_STORAGE_KEYS.captureStartedAt) ?? Date.now());
        const response = await fetch("/api/extract", {
          method: "POST",
          signal: controller.signal,
          headers: {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "x-orbit-anonymous-id": getAnonymousId(),
          },
          body: JSON.stringify({
            rawText,
            captureId,
            stream: true,
            captureStartedAtMs,
          }),
        });

        if (!response.ok) {
          const payload = await response.json();
          throw new Error(payload.error ?? "Orbit couldn’t extract that note.");
        }

        const contentType = response.headers.get("content-type") ?? "";
        if (!contentType.includes("text/event-stream")) {
          const payload = await response.json();
          setCaptureId(payload.captureId);
          setExtraction(payload.extraction);
          setPreview(previewFromExtraction(payload.extraction));
          setError(null);
          window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftCaptureId, payload.captureId);
          window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftExtraction, JSON.stringify(payload.extraction));
          return;
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("Orbit couldn’t stream that extraction.");
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSseBuffer(buffer);
          buffer = parsed.remainder;

          for (const event of parsed.events) {
            if (event.event === "meta") {
              const payload = event.data as { captureId: string };
              setCaptureId(payload.captureId);
              window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftCaptureId, payload.captureId);
              continue;
            }

            if (event.event === "preview") {
              const payload = event.data as { patch: Parameters<typeof mergeExtractionPreview>[1] };
              setPreview((current) => mergeExtractionPreview(current, payload.patch));
              continue;
            }

            if (event.event === "final") {
              const payload = event.data as { captureId: string; extraction: ExtractionResult };
              setCaptureId(payload.captureId);
              setExtraction(payload.extraction);
              setPreview(previewFromExtraction(payload.extraction));
              setError(null);
              window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftCaptureId, payload.captureId);
              window.localStorage.setItem(LOCAL_STORAGE_KEYS.draftExtraction, JSON.stringify(payload.extraction));
              continue;
            }

            if (event.event === "error") {
              const payload = event.data as { error?: string };
              throw new Error(payload.error ?? "Orbit couldn’t extract that note.");
            }
          }
        }
      } catch (caught) {
        if ((caught as Error).name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "Orbit couldn’t extract that note.");
        void trackEvent("extract_failed", { captureId });
      } finally {
        setIsExtracting(false);
      }
    }, 650);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [captureId, rawText]);

  const canSave = useMemo(() => Boolean(rawText.trim() && extraction && captureId), [captureId, rawText, extraction]);

  async function saveDirectly(payload: PendingCommitPayload) {
    const captureStartedAtMs = Number(window.localStorage.getItem(LOCAL_STORAGE_KEYS.captureStartedAt) ?? Date.now());
    const response = await fetch("/api/memories/commit", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-orbit-anonymous-id": getAnonymousId(),
      },
      body: JSON.stringify({
        captureId: payload.captureId,
        rawText: payload.rawText,
        extraction: payload.extraction,
        resolution: { type: "auto" },
        captureStartedAtMs,
      }),
    });

    const data = await response.json();

    if (response.status === 409 && data.requiresResolution) {
      router.push(`/app?postAuth=1&captureId=${payload.captureId}`);
      return;
    }

    if (!response.ok) {
      throw new Error(data.error ?? "Orbit couldn’t save that memory.");
    }

    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.pendingCommit);
    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftRawText);
    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftExtraction);
    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.draftCaptureId);
    window.localStorage.removeItem(LOCAL_STORAGE_KEYS.captureStartedAt);
    router.push(`/profiles/${data.profileId}?saved=1`);
  }

  async function handleSave() {
    if (!extraction || !captureId) return;

    try {
      const payload = { captureId, rawText, extraction };

      window.localStorage.setItem(LOCAL_STORAGE_KEYS.pendingCommit, JSON.stringify(payload));
      await trackEvent("oauth_started", { authenticated: isAuthenticated, captureId });

      if (isAuthenticated) {
        await saveDirectly(payload);
        return;
      }

      const next = encodeURIComponent(`/app?postAuth=1&captureId=${captureId}`);
      window.location.href = `/auth/login?next=${next}`;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Orbit couldn’t save that memory.");
    }
  }

  async function processUpload(file: File | null, kind: "audio" | "card") {
    if (!file) return;

    setIsProcessingUpload(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append(kind, file);
      const response = await fetch(`/api/capture/${kind === "audio" ? "audio" : "card"}`, {
        method: "POST",
        headers: {
          "x-orbit-anonymous-id": getAnonymousId(),
        },
        body: formData,
      });
      const payload = await response.json();

      if (!response.ok) {
        throw new Error(payload.error ?? "Orbit couldn’t process that upload.");
      }

      setRawText(kind === "audio" ? payload.transcript : payload.text);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Orbit couldn’t process that upload.");
    } finally {
      setIsProcessingUpload(false);
    }
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
            {isProcessingUpload ? "Processing upload..." : isExtracting ? "Streaming extract..." : "Private preview"}
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

        <div className="mt-4 flex flex-wrap gap-3">
          <label className="inline-flex cursor-pointer items-center justify-center rounded-full border border-[var(--line)] bg-white/65 px-4 py-2 text-sm font-semibold transition hover:bg-white">
            Voice note
            <input
              accept="audio/mpeg,audio/mp4,audio/wav,audio/webm,audio/x-m4a"
              className="sr-only"
              disabled={isProcessingUpload}
              onChange={(event) => {
                void processUpload(event.target.files?.[0] ?? null, "audio");
                event.currentTarget.value = "";
              }}
              type="file"
            />
          </label>
          <label className="inline-flex cursor-pointer items-center justify-center rounded-full border border-[var(--line)] bg-white/65 px-4 py-2 text-sm font-semibold transition hover:bg-white">
            Business card
            <input
              accept="image/jpeg,image/png,image/webp"
              className="sr-only"
              disabled={isProcessingUpload}
              onChange={(event) => {
                void processUpload(event.target.files?.[0] ?? null, "card");
                event.currentTarget.value = "";
              }}
              type="file"
            />
          </label>
        </div>

        {error ? <p className="mt-4 text-sm text-[#a54634]">{error}</p> : null}
      </div>

      <PreviewCard extraction={extraction} preview={preview} isExtracting={isExtracting} />
    </motion.section>
  );
}
