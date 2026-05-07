import Link from "next/link";

export default function NotFoundPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="glass max-w-lg rounded-[2rem] p-8 text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">Not found</p>
        <h1 className="section-title mt-4 text-4xl">That memory drifted out of orbit.</h1>
        <p className="mt-4 leading-7 text-[var(--muted)]">
          The profile or route you asked for doesn’t exist for this account.
        </p>
        <Link className="mt-8 inline-flex rounded-full bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-white" href="/app">
          Back to dashboard
        </Link>
      </div>
    </main>
  );
}
