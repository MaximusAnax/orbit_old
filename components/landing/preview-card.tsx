"use client";

import { motion } from "motion/react";
import type { ExtractionResult } from "@/lib/validators";

const revealOrder = [
  "Name",
  "Role",
  "Company",
  "Context",
  "Follow-up",
] as const;

export function PreviewCard({
  extraction,
  revealedCount,
}: {
  extraction: ExtractionResult | null;
  revealedCount: number;
}) {
  if (!extraction) {
    return (
      <div className="glass flex min-h-[420px] items-center justify-center rounded-[2rem] border-dashed p-8 text-center text-[var(--muted)]">
        Start with a messy note. Orbit will turn it into a structured memory card here.
      </div>
    );
  }

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
          <h2 className="section-title mt-3 text-3xl">{extraction.contact.name}</h2>
        </div>
        <div className="rounded-full border border-[var(--line)] px-3 py-1 text-xs text-[var(--muted)]">
          {extraction.interaction.sentiment}
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        {revealOrder.map((label, index) => {
          const isVisible = index < revealedCount;
          const value =
            label === "Name"
              ? extraction.contact.name
              : label === "Role"
                ? extraction.contact.role ?? "Not inferred yet"
                : label === "Company"
                  ? extraction.contact.org ?? "Not inferred yet"
                  : label === "Context"
                    ? extraction.interaction.context
                    : `${extraction.suggestedFollowUpDays} days`;

          return (
            <motion.div
              key={label}
              className="rounded-[1.25rem] border border-[var(--line)] bg-white/70 p-4"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: isVisible ? 1 : 0.25, y: 0 }}
              transition={{ duration: 0.25, delay: index * 0.05 }}
            >
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
              <p className="mt-2 text-base leading-7 text-[var(--foreground)]">{value}</p>
            </motion.div>
          );
        })}
      </div>

      {extraction.tags.length ? (
        <div className="mt-5 flex flex-wrap gap-2">
          {extraction.tags.map((tag) => (
            <span key={tag} className="rounded-full bg-[var(--accent-soft)] px-3 py-1 text-xs font-medium text-[var(--accent)]">
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </motion.div>
  );
}
