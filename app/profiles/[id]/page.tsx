import Link from "next/link";
import { notFound } from "next/navigation";
import { UserRound } from "lucide-react";
import { FollowUpActions } from "@/components/app/follow-up-actions";
import { ProfileEditor } from "@/components/app/profile-editor";
import { RelationshipActions } from "@/components/app/relationship-actions";
import { Badge, IconBox, Panel } from "@/components/ui/primitives";
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
    <main className="min-h-screen bg-transparent py-6">
      <div className="shell">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] pb-4">
          <Link className="text-sm font-semibold text-[var(--muted-strong)] transition hover:text-[var(--foreground)]" href="/app">
            Back to dashboard
          </Link>
          {saved ? (
            <Badge tone="success">Memory saved</Badge>
          ) : null}
        </div>

        <Panel className="p-5 lg:p-6">
          <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <IconBox>
                  <UserRound aria-hidden="true" />
                </IconBox>
                <p className="eyebrow">Relationship profile</p>
              </div>
              <h1 className="section-title mt-3 text-4xl font-black">{profile.full_name}</h1>
              <p className="mt-3 text-lg text-[var(--muted)]">
                {[profile.job_role, profile.current_org].filter(Boolean).join(" · ") || "Role and company inferred from your notes"}
              </p>
              <div className="mt-5">
                <ProfileEditor profile={profile} />
              </div>
            </div>

            <div className="grid gap-4 rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-5 text-sm text-[var(--muted)] md:min-w-[300px]">
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
              <FollowUpActions profileId={profile.id} />
            </div>
          </div>
        </Panel>

        <RelationshipActions profileId={profile.id} />

        <section className="mt-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title text-2xl font-black">Timeline</h2>
            <span className="text-sm text-[var(--muted)]">{interactions.length} captured moments</span>
          </div>

          <div className="grid gap-4">
            {interactions.map((interaction) => (
              <Panel key={interaction.id} className="p-5">
                <div className="flex flex-wrap items-center gap-3">
                  <Badge tone={interaction.sentiment === "positive" ? "success" : "neutral"}>{interaction.sentiment}</Badge>
                  <span className="text-sm text-[var(--muted)]">{formatLongDate(interaction.interaction_date)}</span>
                </div>
                <p className="mt-4 text-base leading-7 text-[var(--foreground)]">{interaction.structured_summary}</p>
                <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-[var(--muted)]">{interaction.raw_content}</p>
                {interaction.tags.length ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {interaction.tags.map((tag) => (
                      <span key={tag} className="rounded-[var(--radius)] border border-[var(--line)] px-2.5 py-1 text-xs text-[var(--muted)]">
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
              </Panel>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
