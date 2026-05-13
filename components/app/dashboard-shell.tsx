"use client";

import Link from "next/link";
import { Bell, Orbit, Plus } from "lucide-react";
import type { InteractionRecord, ProfileRecord } from "@/lib/types";
import { formatLongDate, formatRelativeDate } from "@/lib/utils";
import { FollowUpActions } from "@/components/app/follow-up-actions";
import { PostAuthCommitter } from "@/components/app/post-auth-committer";
import { SearchPanel } from "@/components/app/search-panel";
import { Badge, EmptyState, IconBox, LinkButton, Panel } from "@/components/ui/primitives";

function FollowUpColumn({
  title,
  subtitle,
  tone,
  profiles,
}: {
  title: string;
  subtitle: string;
  tone: "danger" | "accent";
  profiles: ProfileRecord[];
}) {
  return (
    <Panel className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">{subtitle}</p>
          <h2 className="section-title mt-1 text-2xl font-black">{title}</h2>
        </div>
        <Badge tone={tone === "danger" ? "danger" : "accent"}>{profiles.length}</Badge>
      </div>

      <div className="mt-5 grid gap-3">
        {profiles.length ? (
          profiles.map((profile) => (
            <article key={profile.id} className="rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-4 transition hover:border-[var(--accent)]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <Link className="font-semibold text-[var(--foreground)] transition hover:text-[var(--accent)]" href={`/profiles/${profile.id}`}>
                    {profile.full_name}
                  </Link>
                  <p className="mt-1 text-sm text-[var(--muted)]">
                    {[profile.job_role, profile.current_org].filter(Boolean).join(" · ") || "Profile inferred from your notes"}
                  </p>
                </div>
                <Badge tone={tone === "danger" ? "danger" : "accent"}>{formatRelativeDate(profile.next_follow_up_at)}</Badge>
              </div>
              <FollowUpActions profileId={profile.id} compact />
            </article>
          ))
        ) : (
          <EmptyState title="Clear for now" description="No profiles in this follow-up lane yet." />
        )}
      </div>
    </Panel>
  );
}

function RecentCaptures({
  interactions,
}: {
  interactions: Array<
    InteractionRecord & {
      profiles: ProfileRecord;
    }
  >;
}) {
  return (
    <Panel className="p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Recent captures</p>
          <h2 className="section-title mt-1 text-2xl font-black">Fresh memory stream</h2>
        </div>
        <Link className="text-sm font-semibold text-[var(--muted-strong)] transition hover:text-[var(--foreground)]" href="/">
          Capture another
        </Link>
      </div>

      <div className="mt-5 grid gap-4">
        {interactions.length ? (
          interactions.map((interaction) => (
            <article key={interaction.id} className="rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <Link className="font-semibold text-[var(--foreground)] transition hover:text-[var(--accent)]" href={`/profiles/${interaction.profile_id}`}>
                    {interaction.profiles.full_name}
                  </Link>
                  <p className="mt-1 text-sm text-[var(--muted)]">
                    {[interaction.profiles.job_role, interaction.profiles.current_org].filter(Boolean).join(" · ") || "Profile inferred from your notes"}
                  </p>
                </div>
                <span className="text-sm text-[var(--muted)]">{formatLongDate(interaction.interaction_date)}</span>
              </div>
              <p className="mt-3 text-sm leading-6 text-[var(--foreground)]">{interaction.structured_summary}</p>
            </article>
          ))
        ) : (
          <EmptyState title="No saved memories yet" description="Use the capture surface to create your first relationship memory." action={<LinkButton href="/" tone="primary">Capture a note</LinkButton>} />
        )}
      </div>
    </Panel>
  );
}

export function DashboardShell({
  overdue,
  upcoming,
  recent,
}: {
  overdue: ProfileRecord[];
  upcoming: ProfileRecord[];
  recent: Array<
    InteractionRecord & {
      profiles: ProfileRecord;
    }
  >;
}) {
  const totalFollowUps = overdue.length + upcoming.length;
  const totalMemories = recent.length;

  return (
    <main className="min-h-screen bg-transparent py-6">
      <div className="shell">
        <header className="mb-5 flex flex-wrap items-center justify-between gap-4 border-b border-[var(--line)] pb-4">
          <div className="flex items-center gap-3">
            <IconBox>
              <Orbit aria-hidden="true" />
            </IconBox>
            <div>
              <p className="eyebrow">Orbit dashboard</p>
              <h1 className="section-title text-3xl font-black">Search your memory</h1>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <LinkButton href="/settings/notifications">
              <Bell aria-hidden="true" className="size-4" />
              Notification settings
            </LinkButton>
            <LinkButton href="/" tone="primary">
              <Plus aria-hidden="true" className="size-4" />
              Capture a new note
            </LinkButton>
          </div>
        </header>

        <PostAuthCommitter />

        <section className="mb-5 grid gap-3 sm:grid-cols-3">
          <Panel className="p-4">
            <p className="text-sm font-semibold text-[var(--muted)]">Follow-ups</p>
            <p className="mt-2 text-3xl font-black">{totalFollowUps}</p>
          </Panel>
          <Panel className="p-4">
            <p className="text-sm font-semibold text-[var(--muted)]">Recent memories</p>
            <p className="mt-2 text-3xl font-black">{totalMemories}</p>
          </Panel>
          <Panel className="p-4">
            <p className="text-sm font-semibold text-[var(--muted)]">Recall mode</p>
            <p className="mt-2 text-lg font-black">Semantic</p>
          </Panel>
        </section>

        <div className="grid gap-5 xl:grid-cols-[1.08fr_0.92fr]">
          <SearchPanel />
          <RecentCaptures interactions={recent} />
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <FollowUpColumn title="Needs attention now" subtitle="Going cold" tone="danger" profiles={overdue} />
          <FollowUpColumn title="Upcoming soon" subtitle="Stay warm" tone="accent" profiles={upcoming} />
        </div>
      </div>
    </main>
  );
}
