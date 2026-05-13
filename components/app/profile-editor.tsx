"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ProfileRecord } from "@/lib/types";
import { Button, Panel, TextInput } from "@/components/ui/primitives";

export function ProfileEditor({ profile }: { profile: ProfileRecord }) {
  const router = useRouter();
  const [isEditing, setIsEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  async function submit(formData: FormData) {
    setError(null);
    const followUpValue = String(formData.get("followUpIntervalDays") ?? "").trim();
    const payload = {
      fullName: String(formData.get("fullName") ?? "").trim(),
      currentOrg: optionalString(formData.get("currentOrg")),
      jobRole: optionalString(formData.get("jobRole")),
      followUpIntervalDays: followUpValue ? Number(followUpValue) : null,
    };

    const response = await fetch(`/api/profiles/${profile.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();

    if (!response.ok) {
      setError(data.error ?? "Profile update failed.");
      return;
    }

    setIsEditing(false);
    startTransition(() => router.refresh());
  }

  if (!isEditing) {
    return (
      <Button onClick={() => setIsEditing(true)} type="button">
        Edit profile
      </Button>
    );
  }

  return (
    <form
      action={(formData) => {
        void submit(formData);
      }}
      className="mt-5 grid gap-4"
    >
      <Panel className="grid gap-4 p-4">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Name" name="fullName" defaultValue={profile.full_name} required />
          <Field label="Company" name="currentOrg" defaultValue={profile.current_org ?? ""} />
          <Field label="Role" name="jobRole" defaultValue={profile.job_role ?? ""} />
          <Field
            label="Cadence days"
            name="followUpIntervalDays"
            defaultValue={String(profile.follow_up_interval_days ?? 21)}
            type="number"
          />
        </div>

        {error ? <p className="text-sm text-[#a54634]">{error}</p> : null}

        <div className="flex flex-wrap gap-3">
          <Button disabled={isPending} tone="primary" type="submit">
            Save changes
          </Button>
          <Button onClick={() => setIsEditing(false)} type="button">
            Cancel
          </Button>
        </div>
      </Panel>
    </form>
  );
}

function Field({
  label,
  name,
  defaultValue,
  required,
  type = "text",
}: {
  label: string;
  name: string;
  defaultValue: string;
  required?: boolean;
  type?: string;
}) {
  return (
    <label className="grid gap-2 text-sm font-medium text-[var(--foreground)]">
      {label}
      <TextInput
        className="font-normal"
        defaultValue={defaultValue}
        min={type === "number" ? 1 : undefined}
        max={type === "number" ? 180 : undefined}
        name={name}
        required={required}
        type={type}
      />
    </label>
  );
}

function optionalString(value: FormDataEntryValue | null) {
  const trimmed = String(value ?? "").trim();
  return trimmed || null;
}
