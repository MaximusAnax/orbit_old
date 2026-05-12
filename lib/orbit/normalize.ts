import { DEFAULT_FOLLOW_UP_DAYS } from "@/lib/constants";
import type { ExtractionResult, CommitResolution } from "@/lib/validators";
import type { ProfileRecord } from "@/lib/types";

export interface MatchCandidate {
  profileId: string;
  fullName: string;
  currentOrg: string | null;
  currentRole: string | null;
  score: number;
  reason: string;
}

export interface MatchDecision {
  mode: "auto_link" | "create_new" | "needs_confirmation";
  selectedProfileId?: string;
  candidates: MatchCandidate[];
}

export function normalizeName(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function normalizeOrg(value: string | null | undefined) {
  if (!value) return null;
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildSearchText(extraction: ExtractionResult, rawText: string) {
  return [
    extraction.contact.name,
    extraction.contact.org,
    extraction.contact.role,
    extraction.interaction.summary,
    extraction.interaction.context,
    extraction.tags.join(" "),
    rawText,
  ]
    .filter(Boolean)
    .join("\n");
}

export function calculateFollowUpAt(
  interactionDate: Date,
  suggestedDays?: number | null,
  preferredDays?: number | null,
) {
  const days = preferredDays ?? suggestedDays ?? DEFAULT_FOLLOW_UP_DAYS;
  const result = new Date(interactionDate);
  result.setUTCDate(result.getUTCDate() + days);
  return result.toISOString();
}

export function scoreProfileMatch(profile: ProfileRecord, extraction: ExtractionResult): MatchCandidate {
  const normalizedName = normalizeName(extraction.contact.name);
  const normalizedOrg = normalizeOrg(extraction.contact.org);
  const profileOrg = normalizeOrg(profile.current_org);

  let score = 0;
  const reasons: string[] = [];

  if (profile.normalized_name === normalizedName) {
    score += 0.72;
    reasons.push("Exact name match");
  } else if (profile.normalized_name.includes(normalizedName) || normalizedName.includes(profile.normalized_name)) {
    score += 0.48;
    reasons.push("Partial name match");
  }

  if (normalizedOrg && profileOrg && normalizedOrg === profileOrg) {
    score += 0.23;
    reasons.push("Organization match");
  } else if (!normalizedOrg || !profileOrg) {
    score += 0.08;
    reasons.push("Missing org, keeping light confidence");
  }

  if (extraction.contact.role && profile.job_role) {
    const extractionRole = extraction.contact.role.toLowerCase();
    const profileRole = profile.job_role.toLowerCase();
    if (extractionRole === profileRole) {
      score += 0.08;
      reasons.push("Role match");
    }
  }

  score = Math.min(0.99, Number(score.toFixed(2)));

  return {
    profileId: profile.id,
    fullName: profile.full_name,
    currentOrg: profile.current_org,
    currentRole: profile.job_role,
    score,
    reason: reasons.join(" • ") || "Low confidence match",
  };
}

export function selectProfilesForMatching(profiles: ProfileRecord[], extraction: ExtractionResult) {
  const normalizedName = normalizeName(extraction.contact.name);
  const normalizedOrg = normalizeOrg(extraction.contact.org);
  const nameParts = new Set(normalizedName.split(" ").filter((part) => part.length > 1));

  return profiles
    .filter((profile) => {
      const profileName = normalizeName(profile.full_name);
      const profileOrg = normalizeOrg(profile.current_org);
      const hasNameOverlap =
        profile.normalized_name === normalizedName ||
        profile.normalized_name.includes(normalizedName) ||
        normalizedName.includes(profile.normalized_name) ||
        profileName.split(" ").some((part) => nameParts.has(part));
      const hasOrgOverlap = Boolean(normalizedOrg && profileOrg && normalizedOrg === profileOrg);

      return hasNameOverlap || hasOrgOverlap;
    })
    .slice(0, 10);
}

export function decideMatch(
  profiles: ProfileRecord[],
  extraction: ExtractionResult,
  resolution?: CommitResolution,
): MatchDecision {
  if (resolution?.type === "link_existing") {
    return {
      mode: "auto_link",
      selectedProfileId: resolution.profileId,
      candidates: [],
    };
  }

  if (resolution?.type === "create_new") {
    return {
      mode: "create_new",
      candidates: [],
    };
  }

  const candidates = profiles
    .map((profile) => scoreProfileMatch(profile, extraction))
    .filter((candidate) => candidate.score >= 0.45)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  const [top, second] = candidates;

  if (!top) {
    return {
      mode: "create_new",
      candidates: [],
    };
  }

  if (top.score >= 0.9 && (!second || top.score - second.score >= 0.12)) {
    return {
      mode: "auto_link",
      selectedProfileId: top.profileId,
      candidates,
    };
  }

  if (top.score >= 0.65) {
    return {
      mode: "needs_confirmation",
      candidates,
    };
  }

  return {
    mode: "create_new",
    candidates,
  };
}
