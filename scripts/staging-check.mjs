import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

const requiredEnv = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "OPENAI_API_KEY",
  "CRON_SECRET",
  "RESEND_API_KEY",
  "REMINDER_FROM_EMAIL",
  "NEXT_PUBLIC_APP_URL",
];

const missingEnv = requiredEnv.filter((name) => !process.env[name]);
const migrationsDir = join(process.cwd(), "supabase", "migrations");
const migrations = existsSync(migrationsDir)
  ? readdirSync(migrationsDir).filter((file) => file.endsWith(".sql")).sort()
  : [];

console.log("Orbit staging readiness check");
console.log(`Migrations found: ${migrations.length}`);
for (const migration of migrations) {
  console.log(`- ${migration}`);
}

if (missingEnv.length) {
  console.error(`Missing env vars: ${missingEnv.join(", ")}`);
  process.exitCode = 1;
} else {
  console.log("Required env vars are present.");
}

if (!migrations.some((migration) => migration.includes("notification_preferences"))) {
  console.error("Missing notification preferences migration.");
  process.exitCode = 1;
}
