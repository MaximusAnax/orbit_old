import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

const requiredEnv = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "OPENAI_API_KEY",
  "NEXT_PUBLIC_APP_URL",
];

const expectedAppUrl = "https://orbit.abdoulndiongue.com";
const missingEnv = requiredEnv.filter((name) => !process.env[name]);
const migrationsDir = join(process.cwd(), "supabase", "migrations");
const migrations = existsSync(migrationsDir)
  ? readdirSync(migrationsDir).filter((file) => file.endsWith(".sql")).sort()
  : [];

console.log("Orbit production readiness check");
console.log(`Target URL: ${expectedAppUrl}`);
console.log(`Migrations found: ${migrations.length}`);
for (const migration of migrations) {
  console.log(`- ${migration}`);
}

if (missingEnv.length) {
  console.error(`Missing env vars: ${missingEnv.join(", ")}`);
  process.exitCode = 1;
} else {
  console.log("Required launch env vars are present.");
}

if (process.env.NEXT_PUBLIC_APP_URL && process.env.NEXT_PUBLIC_APP_URL !== expectedAppUrl) {
  console.error(`NEXT_PUBLIC_APP_URL must be ${expectedAppUrl}.`);
  process.exitCode = 1;
}

if (!migrations.length) {
  console.error("No Supabase migrations found.");
  process.exitCode = 1;
}

if (!migrations.some((migration) => migration.includes("notification_preferences"))) {
  console.error("Missing notification preferences migration.");
  process.exitCode = 1;
}

if (process.env.RESEND_API_KEY || process.env.REMINDER_FROM_EMAIL) {
  console.warn("Reminder email env vars are present. Launch plan says reminders stay disabled.");
}
