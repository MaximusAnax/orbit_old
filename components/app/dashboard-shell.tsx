"use client";

import Link from "next/link";
import type { InteractionRecord, ProfileRecord } from "@/lib/types";
import { formatLongDate, formatRelativeDate } from "@/lib/utils";
import { PostAuthCommitter } from "@/components/app/post-auth-committer";
import { SearchPanel } from "@/components/app/search-panel";

function FollowUpColumn({
  title,
  subtitle,
  profiles,
}: {
  title: string;
  subtitle: string;
  profiles: ProfileRecord[];
}) {
  return (
    <section className="glass rounded-[2rem] p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">{subtitle}</p>
      <h2 className="section-title mt-2 text-3xl">{title}</h2>

      <div className="mt-5 grid gap-3">
        {profiles.length ? (
          profiles.map((profile) => (
            <Link key={profile.id} className="rounded-[1.25rem] border border-[var(--line)] bg-white/75 p-4 transition hover:border-[var(--accent)]" href={`/profiles/${profile.id}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-semibold text-[var(--foreground)]">{profile.full_name}</div>
                  <p className="mt-1 text-sm text-[var(--muted)]">
                    {[profile.job_role, profile.current_org].filter(Boolean).join(" · ") || "Profile inferred from your notes"}
                  </p>
                </div>
                <span className="rounded-full bg-[var(--accent-soft)] px-2.5 py-1 text-xs font-medium text-[var(--accent)]">
                  {formatRelativeDate(profile.next_follow_up_at)}
                </span>
              </div>
            </Link>
          ))
        ) : (
          <p className="rounded-[1.25rem] border border-dashed border-[var(--line)] px-4 py-6 text-center text-sm text-[var(--muted)]">
            No profiles in this lane yet.
          </p>
        )}
      </div>
    </section>
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
    <section className="glass rounded-[2rem] p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Recent captures</p>
          <h2 className="section-title mt-2 text-3xl">The freshest moments in orbit.</h2>
        </div>
        <Link className="text-sm text-[var(--muted)] transition hover:text-[var(--foreground)]" href="/">
          Capture another
        </Link>
      </div>

      <div className="mt-5 grid gap-4">
        {interactions.length ? (
          interactions.map((interaction) => (
            <article key={interaction.id} className="rounded-[1.35rem] border border-[var(--line)] bg-white/75 p-5">
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
              <p className="mt-4 leading-7 text-[var(--foreground)]">{interaction.structured_summary}</p>
            </article>
          ))
        ) : (
          <p className="rounded-[1.25rem] border border-dashed border-[var(--line)] px-4 py-6 text-center text-sm text-[var(--muted)]">
            No saved memories yet. Use the capture surface to create your first one.
          </p>
        )}
      </div>
    </section>
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
  return (
    <main className="min-h-screen bg-transparent py-8">
      <div className="shell">
        <header className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Orbit dashboard</p>
            <h1 className="section-title mt-2 text-5xl">People you should remember before they go cold.</h1>
          </div>
          <Link className="rounded-full bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90" href="/">
            Capture a new note
          </Link>
        </header>

        <PostAuthCommitter />

        <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          <SearchPanel />
          <RecentCaptures interactions={recent} />
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <FollowUpColumn title="Needs attention now" subtitle="Going cold" profiles={overdue} />
          <FollowUpColumn title="Upcoming soon" subtitle="Stay warm" profiles={upcoming} />
        </div>
      </div>
    </main>
  );
}
