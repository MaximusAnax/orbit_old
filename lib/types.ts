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

export interface SearchInteractionRow {
  interaction_id: string;
  profile_id: string;
  full_name: string;
  current_org: string | null;
  job_role: string | null;
  structured_summary: string;
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
