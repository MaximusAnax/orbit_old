"use client";

import { motion } from "motion/react";
import { previewFromExtraction, type ExtractionPreview } from "@/lib/orbit/preview";
import { Badge, Panel } from "@/components/ui/primitives";
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
      <Panel className="flex min-h-[360px] items-center justify-center border-dashed p-8 text-center">
        <div>
          <p className="font-bold text-[var(--foreground)]">Memory preview</p>
          <p className="mt-2 max-w-sm text-sm leading-6 text-[var(--muted)]">
            Start with a messy note. Orbit will turn it into a structured relationship card here.
          </p>
        </div>
      </Panel>
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
      className="surface min-h-[360px] p-5 lg:p-6"
      initial={{ opacity: 0.6, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Memory card</p>
          <h2 className="section-title mt-2 text-2xl font-black">{activePreview.contact.name ?? "Orbit is pulling the person forward..."}</h2>
        </div>
        <Badge tone={activePreview.interaction.sentiment === "positive" ? "success" : "neutral"}>
          {activePreview.interaction.sentiment ?? (isExtracting ? "extracting" : "preview")}
        </Badge>
      </div>

      <div className="mt-5 grid gap-3">
        {sections.map((section, index) => {
          const isVisible = Boolean(section.value);
          return (
            <motion.div
              key={section.label}
              className="rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-4"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: isVisible ? 1 : 0.25, y: 0 }}
              transition={{ duration: 0.25, delay: index * 0.05 }}
            >
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--muted)]">{section.label}</p>
              <p className="mt-2 text-base leading-7 text-[var(--foreground)]">{section.value ?? section.placeholder}</p>
            </motion.div>
          );
        })}
      </div>

      {activePreview.tags.length ? (
        <div className="mt-5 flex flex-wrap gap-2">
          {activePreview.tags.map((tag) => (
            <span key={tag} className="rounded-[var(--radius)] bg-[var(--accent-soft)] px-2.5 py-1 text-xs font-semibold text-[var(--accent)]">
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </motion.div>
  );
}
