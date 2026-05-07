import { DashboardShell } from "@/components/app/dashboard-shell";
import { getDashboardData } from "@/lib/data";

export default async function AppDashboardPage() {
  const data = await getDashboardData();
  return <DashboardShell {...data} />;
}
