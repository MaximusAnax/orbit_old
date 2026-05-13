import { LinkButton, Panel } from "@/components/ui/primitives";

export default function AuthErrorPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Panel className="max-w-lg p-8 text-center">
        <p className="eyebrow">Auth hiccup</p>
        <h1 className="section-title mt-4 text-4xl font-black">Orbit couldn’t finish sign-in.</h1>
        <p className="mt-4 leading-7 text-[var(--muted)]">
          Double-check your Google OAuth redirect URLs and Supabase auth settings, then try again.
        </p>
        <LinkButton className="mt-8" href="/" tone="primary">
          Return home
        </LinkButton>
      </Panel>
    </main>
  );
}
