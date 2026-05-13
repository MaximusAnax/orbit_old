import { LinkButton, Panel } from "@/components/ui/primitives";

export default function NotFoundPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Panel className="max-w-lg p-8 text-center">
        <p className="eyebrow">Not found</p>
        <h1 className="section-title mt-4 text-4xl font-black">That memory drifted out of orbit.</h1>
        <p className="mt-4 leading-7 text-[var(--muted)]">
          The profile or route you asked for doesn’t exist for this account.
        </p>
        <LinkButton className="mt-8" href="/app" tone="primary">
          Back to dashboard
        </LinkButton>
      </Panel>
    </main>
  );
}
