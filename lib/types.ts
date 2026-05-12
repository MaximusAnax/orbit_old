export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

export type Sentiment = "positive" | "neutral" | "mixed" | "negative";

export interface ProfileRecord {
  id: string;
  user_id: string;
  full_name: string;
  normalized_name: string;
  current_org: string | null;
  job_role: string | null;
  metadata: Record<string, Json>;
  last_interaction_at: string | null;
  next_follow_up_at: string | null;
  follow_up_interval_days: number | null;
  created_at: string;
  updated_at: string;
}

export interface InteractionRecord {
  id: string;
  profile_id: string;
  user_id: string;
  raw_content: string;
  structured_summary: string;
  search_text: string;
  tags: string[];
  sentiment: Sentiment;
  suggested_follow_up_days: number;
  interaction_date: string;
  created_at: string;
}

export interface PendingCaptureRecord {
  id: string;
  user_id: string | null;
  anonymous_id: string;
  raw_content: string;
  extraction: Json;
  status: "pending" | "committed";
  profile_id: string | null;
  interaction_id: string | null;
  committed_at: string | null;
  created_at: string;
  updated_at: string;
}

export type ReminderStatus = "due" | "snoozed" | "contacted" | "paused" | "sent" | "failed" | "skipped";

export interface ReminderRecord {
  id: string;
  user_id: string;
  profile_id: string;
  status: ReminderStatus;
  due_at: string;
  sent_at: string | null;
  payload: Record<string, Json>;
  created_at: string;
}

export interface NotificationPreferenceRecord {
  user_id: string;
  daily_digest_enabled: boolean;
  paused_until: string | null;
  unsubscribed_at: string | null;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface SearchInteractionRow {
  interaction_id: string;
  profile_id: string;
  full_name: string;
  current_org: string | null;
  job_role: string | null;
  structured_summary: string;
  search_text?: string;
  raw_content: string;
  tags: string[];
  sentiment: Sentiment;
  interaction_date: string;
  similarity: number;
}

export interface SearchResultGroup {
  profileId: string;
  fullName: string;
  currentOrg: string | null;
  currentRole: string | null;
  topSimilarity: number;
  whyMatched: string[];
  matches: Array<{
    interactionId: string;
    summary: string;
    rawContent: string;
    tags: string[];
    sentiment: Sentiment;
    interactionDate: string;
    similarity: number;
  }>;
}
