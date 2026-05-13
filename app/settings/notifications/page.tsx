import Link from "next/link";
import { NotificationSettings } from "@/components/app/notification-settings";
import { requireUser } from "@/lib/data";

export default async function NotificationSettingsPage() {
  await requireUser();

  return (
    <main className="min-h-screen py-6">
      <div className="shell">
        <div className="mb-5 flex items-center justify-between border-b border-[var(--line)] pb-4">
          <Link className="text-sm font-semibold text-[var(--muted-strong)] transition hover:text-[var(--foreground)]" href="/app">
            Back to dashboard
          </Link>
        </div>
        <NotificationSettings />
      </div>
    </main>
  );
}
