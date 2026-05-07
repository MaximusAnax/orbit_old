import Link from "next/link";
import { CaptureExperience } from "@/components/landing/capture-experience";
import { APP_NAME } from "@/lib/constants";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export default async function HomePage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <main className="ambient-grid min-h-screen pb-12 pt-6">
      <div className="shell">
        <header className="mb-8 flex items-center justify-between rounded-full border border-[var(--line)] bg-white/55 px-5 py-3 backdrop-blur">
          <div>
            <div className="section-title text-2xl">{APP_NAME}</div>
            <p className="mt-1 text-sm text-[var(--muted)]">Relational memory that starts before the login wall.</p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {user ? (
              <Link className="rounded-full bg-[var(--accent)] px-4 py-2 text-white transition hover:opacity-90" href="/app">
                Open dashboard
              </Link>
            ) : (
              <Link className="rounded-full border border-[var(--line)] px-4 py-2 transition hover:bg-white/70" href="/auth/login">
                Sign in with Google
              </Link>
            )}
          </div>
        </header>

        <section className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="glass rounded-[2rem] p-8 lg:p-10">
            <span className="inline-flex rounded-full bg-[var(--accent-soft)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">
              30-second first memory
            </span>
            <h1 className="section-title mt-6 max-w-3xl text-5xl leading-none md:text-6xl">
              Turn the messy note in your head into someone you can actually remember.
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-[var(--muted)]">
              Paste the rough version. Orbit extracts the person, the moment, the emotional signal, and the follow-up window before you even authenticate.
            </p>

            <div className="mt-8 rounded-[1.5rem] border border-[var(--line)] bg-white/70 p-5">
              <p className="text-sm font-medium text-[var(--foreground)]">Try a brain dump</p>
              <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                “Met Priya from Figma after the CMU alumni dinner. She leads product ops, wants intros to ML infra founders, and we really clicked on practical AI tools.”
              </p>
            </div>

            <div className="mt-8 grid gap-4 text-sm text-[var(--muted)] md:grid-cols-3">
              <div className="rounded-[1.5rem] border border-[var(--line)] bg-white/60 p-4">
                <div className="font-semibold text-[var(--foreground)]">Capture first</div>
                <p className="mt-2 leading-6">No contact forms. Just the note you already have.</p>
              </div>
              <div className="rounded-[1.5rem] border border-[var(--line)] bg-white/60 p-4">
                <div className="font-semibold text-[var(--foreground)]">Private by default</div>
                <p className="mt-2 leading-6">Your data stays tied to your account and RLS-backed rows.</p>
              </div>
              <div className="rounded-[1.5rem] border border-[var(--line)] bg-white/60 p-4">
                <div className="font-semibold text-[var(--foreground)]">Search by meaning</div>
                <p className="mt-2 leading-6">Find “that person from TartanHacks” even if you forgot the name.</p>
              </div>
            </div>
          </div>

          <CaptureExperience isAuthenticated={Boolean(user)} />
        </section>
      </div>
    </main>
  );
}
