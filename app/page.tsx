import { Orbit } from "lucide-react";
import { CaptureExperience } from "@/components/landing/capture-experience";
import { Badge, LinkButton, Panel } from "@/components/ui/primitives";
import { APP_NAME } from "@/lib/constants";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export default async function HomePage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <main className="ambient-grid min-h-screen pb-10 pt-5">
      <div className="shell">
        <header className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] pb-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-[var(--radius)] bg-[var(--foreground)] text-white">
              <Orbit aria-hidden="true" className="size-5" />
            </div>
            <div>
              <div className="text-lg font-black tracking-normal">{APP_NAME}</div>
              <p className="text-sm text-[var(--muted)]">Private relationship memory, ready before sign-in.</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm">
            {user ? (
              <LinkButton href="/app" tone="primary">
                Open dashboard
              </LinkButton>
            ) : (
              <LinkButton href="/auth/login">
                Sign in with Google
              </LinkButton>
            )}
          </div>
        </header>

        <section className="mb-5 grid gap-5 lg:grid-cols-[0.88fr_1.12fr]">
          <Panel className="p-6 lg:p-7">
            <Badge tone="accent">30-second first memory</Badge>
            <h1 className="section-title mt-5 max-w-2xl text-4xl font-black leading-tight md:text-5xl">
              Turn the messy note in your head into someone you can actually remember.
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-[var(--muted-strong)]">
              Paste the rough version. Orbit extracts the person, the moment, the emotional signal, and the next thoughtful step before the login wall.
            </p>

            <div className="mt-6 rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-4">
              <p className="text-sm font-bold text-[var(--foreground)]">Try a brain dump</p>
              <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                &quot;Met Priya from Figma after the CMU alumni dinner. She leads product ops, wants intros to ML infra founders, and we clicked on practical AI tools.&quot;
              </p>
            </div>

            <div className="mt-6 grid gap-3 text-sm sm:grid-cols-3">
              {[
                ["Capture", "No contact form. Start with the note you already have."],
                ["Trust", "Drafts stay local until you choose to save."],
                ["Recall", "Search by context, event, topic, or half-remembered detail."],
              ].map(([title, body]) => (
                <div key={title} className="rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] p-3">
                  <div className="font-bold text-[var(--foreground)]">{title}</div>
                  <p className="mt-1 leading-5 text-[var(--muted)]">{body}</p>
                </div>
              ))}
            </div>
          </Panel>

          <CaptureExperience isAuthenticated={Boolean(user)} />
        </section>
      </div>
    </main>
  );
}
