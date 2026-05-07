import Link from "next/link";
import { notFound } from "next/navigation";
import { getProfileById } from "@/lib/data";
import { formatLongDate, formatRelativeDate } from "@/lib/utils";

export default async function ProfilePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ saved?: string }>;
}) {
  const { id } = await params;
  const { saved } = await searchParams;
  const { profile, interactions } = await getProfileById(id);

  if (!profile) {
    notFound();
  }

  return (
    <main className="min-h-screen bg-transparent py-8">
      <div className="shell">
        <div className="mb-5 flex items-center justify-between">
          <Link className="text-sm text-[var(--muted)] transition hover:text-[var(--foreground)]" href="/app">
            Back to dashboard
          </Link>
          {saved ? (
            <span className="rounded-full bg-[var(--accent-soft)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--accent)]">
              Memory saved
            </span>
          ) : null}
        </div>

        <section className="glass rounded-[2rem] p-8">
          <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--accent)]">Relationship profile</p>
              <h1 className="section-title mt-3 text-5xl">{profile.full_name}</h1>
              <p className="mt-3 text-lg text-[var(--muted)]">
                {[profile.job_role, profile.current_org].filter(Boolean).join(" · ") || "Role and company inferred from your notes"}
              </p>
            </div>

            <div className="grid gap-4 rounded-[1.5rem] border border-[var(--line)] bg-white/65 p-5 text-sm text-[var(--muted)] md:min-w-[280px]">
              <div>
                <div className="font-semibold text-[var(--foreground)]">Next follow-up</div>
                <p className="mt-1">{formatRelativeDate(profile.next_follow_up_at)}</p>
              </div>
              <div>
                <div className="font-semibold text-[var(--foreground)]">Last interaction</div>
                <p className="mt-1">
                  {profile.last_interaction_at ? formatLongDate(profile.last_interaction_at) : "First capture pending"}
                </p>
              </div>
              <div>
                <div className="font-semibold text-[var(--foreground)]">Cadence</div>
                <p className="mt-1">{profile.follow_up_interval_days ?? 21} day rhythm</p>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title text-3xl">Timeline</h2>
            <span className="text-sm text-[var(--muted)]">{interactions.length} captured moments</span>
          </div>

          <div className="grid gap-4">
            {interactions.map((interaction) => (
              <article key={interaction.id} className="glass rounded-[1.75rem] p-6">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="rounded-full bg-[var(--accent-soft)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
                    {interaction.sentiment}
                  </span>
                  <span className="text-sm text-[var(--muted)]">{formatLongDate(interaction.interaction_date)}</span>
                </div>
                <p className="mt-4 text-lg leading-8 text-[var(--foreground)]">{interaction.structured_summary}</p>
                <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-[var(--muted)]">{interaction.raw_content}</p>
                {interaction.tags.length ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {interaction.tags.map((tag) => (
                      <span key={tag} className="rounded-full border border-[var(--line)] px-3 py-1 text-xs text-[var(--muted)]">
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
