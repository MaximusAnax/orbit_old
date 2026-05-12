"use client";

import { motion } from "motion/react";
import { previewFromExtraction, type ExtractionPreview } from "@/lib/orbit/preview";
import type { ExtractionResult } from "@/lib/validators";

export function PreviewCard({
  preview,
  extraction,
  isExtracting,
}: {
  preview: ExtractionPreview | null;
  extraction: ExtractionResult | null;
  isExtracting: boolean;
}) {
  const activePreview = extraction ? previewFromExtraction(extraction) : preview;

  if (!activePreview) {
    return (
      <div className="glass flex min-h-[420px] items-center justify-center rounded-[2rem] border-dashed p-8 text-center text-[var(--muted)]">
        Start with a messy note. Orbit will turn it into a structured memory card here.
      </div>
    );
  }

  const sections = [
    {
      label: "Name",
      value: activePreview.contact.name,
      placeholder: "Listening for who this memory is about...",
    },
    {
      label: "Role",
      value: activePreview.contact.role,
      placeholder: "Role will appear once Orbit catches the signal.",
    },
    {
      label: "Company",
      value: activePreview.contact.org,
      placeholder: "Company will appear once Orbit has enough context.",
    },
    {
      label: "Context",
      value: activePreview.interaction.context,
      placeholder: "Context is building from the rough note...",
    },
    {
      label: "Follow-up",
      value: activePreview.suggestedFollowUpDays ? `${activePreview.suggestedFollowUpDays} days` : null,
      placeholder: "Follow-up timing lands when the note is parsed.",
    },
  ] as const;

  return (
    <motion.div
      className="glass min-h-[420px] rounded-[2rem] p-6"
      initial={{ opacity: 0.6, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Memory card</p>
          <h2 className="section-title mt-3 text-3xl">{activePreview.contact.name ?? "Orbit is pulling the person forward..."}</h2>
        </div>
        <div className="rounded-full border border-[var(--line)] px-3 py-1 text-xs text-[var(--muted)]">
          {activePreview.interaction.sentiment ?? (isExtracting ? "extracting" : "preview")}
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        {sections.map((section, index) => {
          const isVisible = Boolean(section.value);
          return (
            <motion.div
              key={section.label}
              className="rounded-[1.25rem] border border-[var(--line)] bg-white/70 p-4"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: isVisible ? 1 : 0.25, y: 0 }}
              transition={{ duration: 0.25, delay: index * 0.05 }}
            >
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{section.label}</p>
              <p className="mt-2 text-base leading-7 text-[var(--foreground)]">{section.value ?? section.placeholder}</p>
            </motion.div>
          );
        })}
      </div>

      {activePreview.tags.length ? (
        <div className="mt-5 flex flex-wrap gap-2">
          {activePreview.tags.map((tag) => (
            <span key={tag} className="rounded-full bg-[var(--accent-soft)] px-3 py-1 text-xs font-medium text-[var(--accent)]">
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </motion.div>
  );
}
