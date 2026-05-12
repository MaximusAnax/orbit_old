# Orbit TDD: Post-MVP Relationship Intelligence Platform

## 1. Architecture Overview

The completed MVP uses a serverless, capture-first architecture: Next.js, Supabase Postgres with `pgvector`, Supabase Auth, and OpenAI-backed extraction and embeddings.

The post-MVP architecture extends that foundation into an event-driven relationship intelligence platform. The key technical shift is from single-memory extraction to continuous intelligence loops:

1. Capture or import raw relationship context.
2. Normalize, extract, and link entities.
3. Store memories with provenance and embeddings.
4. Update profile summaries, relationship signals, and clusters.
5. Generate reminders, opportunity matches, and draftable next actions.
6. Let the user approve, correct, dismiss, or act.

The system must preserve a private-first trust model. AI can suggest and draft, but the user remains in control.

## 2. Existing Foundation

Assumed complete from MVP:

- Next.js App Router application deployed on Vercel.
- Supabase Auth with OAuth.
- `profiles` and `interactions` tables.
- `pgvector` semantic search over interaction embeddings.
- `/api/extract` for structured memory extraction.
- `/api/search` for semantic retrieval.
- Capture-before-auth onboarding and post-auth commit flow.
- Basic recency reminders.

New work should extend these surfaces instead of introducing a parallel data model.

## 3. Technical Stack

- **Frontend:** Next.js App Router, React, Tailwind CSS, Framer Motion.
- **Backend:** Next.js route handlers for synchronous user actions.
- **Database:** Supabase Postgres with `pgvector`, JSONB metadata, Row Level Security.
- **Auth:** Supabase Auth.
- **Background Jobs:** Supabase Edge Functions, Vercel Cron, or a queue worker depending on deployment constraints.
- **AI:** OpenAI structured outputs for extraction, classification, summarization, goal parsing, and outreach drafts.
- **Embeddings:** OpenAI embedding model currently used by MVP unless upgraded deliberately.
- **Storage:** Supabase Storage for uploaded business cards, audio snippets, and import files.
- **Optional Cache:** Upstash Redis for short-lived search and goal-result caching.

## 4. Core Domain Model

The existing `profiles` and `interactions` tables remain the center of the system. Additive schema changes should support richer intelligence without breaking MVP flows.

### 4.1 `profiles`

Extend existing profile records with:

- `display_name`
- `current_org`
- `job_role`
- `location`
- `relationship_strength`
- `importance_level`
- `last_interaction_at`
- `summary`
- `metadata`
- `updated_at`

### 4.2 `interactions`

Extend existing interaction records with:

- `source_type`: text, voice, card, import, calendar, share, manual.
- `source_id`
- `event_id`
- `structured_json`
- `sentiment`
- `open_loops`
- `follow_up_date`
- `embedding`
- `created_at`

### 4.3 New Tables

#### `sources`

Tracks where a fact or memory came from.

- `id`
- `user_id`
- `source_type`
- `source_uri`
- `raw_content_ref`
- `captured_at`
- `confidence`
- `metadata`

#### `profile_facts`

Stores editable, provenance-backed facts about a person.

- `id`
- `user_id`
- `profile_id`
- `field_name`
- `field_value`
- `source_id`
- `confidence`
- `is_user_verified`
- `is_sensitive`
- `created_at`
- `updated_at`

#### `profile_aliases`

Supports deduplication and entity linking.

- `id`
- `user_id`
- `profile_id`
- `alias`
- `alias_type`: name, email, phone, handle, url.
- `source_id`

#### `events`

Groups high-volume capture sessions.

- `id`
- `user_id`
- `name`
- `event_type`
- `location`
- `started_at`
- `ended_at`
- `metadata`

#### `goals`

Stores Opportunity Mode goals.

- `id`
- `user_id`
- `raw_goal`
- `structured_goal`
- `status`
- `created_at`
- `updated_at`

#### `goal_matches`

Stores ranked people or paths for a goal.

- `id`
- `user_id`
- `goal_id`
- `profile_id`
- `score`
- `reason`
- `supporting_interaction_ids`
- `status`: new, saved, dismissed, acted.
- `created_at`

#### `follow_up_suggestions`

Stores generated relationship actions.

- `id`
- `user_id`
- `profile_id`
- `goal_id`
- `reason`
- `suggested_action`
- `suggested_channel`
- `priority`
- `due_at`
- `status`: pending, accepted, snoozed, dismissed, completed.
- `created_at`

#### `outreach_drafts`

Stores user-requested drafts.

- `id`
- `user_id`
- `profile_id`
- `goal_id`
- `suggestion_id`
- `draft_body`
- `tone`
- `source_context`
- `created_at`
- `updated_at`

#### `network_clusters`

Stores computed clusters for insight views.

- `id`
- `user_id`
- `cluster_type`: event, company, school, domain, location, inferred.
- `label`
- `profile_ids`
- `summary`
- `embedding`
- `updated_at`

## 5. AI Pipelines

### 5.1 Capture Processing Pipeline

Input sources:

- Text capture.
- Voice transcription.
- Business card OCR.
- Contact import.
- Calendar context.
- Shared profile or URL.

Pipeline:

1. Persist raw source.
2. Extract structured entities and relationship memory.
3. Generate or update embeddings.
4. Link to existing profile or create a new profile.
5. Write provenance-backed facts.
6. Update profile summary and relationship signals.
7. Create follow-up candidates when warranted.

Entity linking should use a hybrid approach:

- Exact identifiers: email, phone, URL, handle.
- Name similarity within user's private graph.
- Organization and event overlap.
- Embedding similarity across prior interactions.
- LLM adjudication only after deterministic candidates are gathered.

### 5.2 Opportunity Mode Pipeline

Input:

```json
{
  "goal": "Looking for ML internships in SF"
}
```

Pipeline:

1. Parse the goal into structured dimensions: intent, domain, organizations, geography, time horizon, desired help.
2. Create an embedding for the raw and structured goal.
3. Retrieve candidate profiles via vector search, full-text search, metadata filters, events, and clusters.
4. Rank candidates by semantic relevance, relationship strength, recency, explicit importance, and path clarity.
5. Generate concise explanations with citations to stored memories.
6. Store `goal_matches`.
7. Offer next actions and optional outreach drafts.

Ranking formula should be inspectable and tunable:

```text
match_score =
  semantic_relevance * 0.40 +
  metadata_match * 0.20 +
  relationship_strength * 0.15 +
  recency * 0.10 +
  explicit_importance * 0.10 +
  source_confidence * 0.05
```

Weights can be adjusted after product telemetry.

### 5.3 Follow-Up Suggestion Pipeline

Triggered by:

- Daily scheduled job.
- New captured interaction.
- New or updated goal.
- Event recap generation.
- Explicit user reminder.

Scoring inputs:

- Last interaction date.
- Relationship strength and importance.
- Open loops.
- Active goals.
- Event recency.
- Known recruiting or deadline context.
- User dismissals and feedback.

Output:

- A small set of high-confidence suggestions.
- Each suggestion includes rationale and supporting memory references.
- Suggestions must be suppressible and learn from dismissals.

### 5.4 Outreach Draft Pipeline

Draft generation must be user-initiated.

Input context:

- Profile facts.
- Recent interactions.
- Shared event or context.
- Goal or follow-up reason.
- User-selected tone.

Safety constraints:

- Do not invent facts.
- Do not imply closeness not supported by memory.
- Do not send automatically.
- Include only context visible to the user.
- Prefer concise drafts.

## 6. API Surface

### Capture and Imports

- `POST /api/capture/text`
- `POST /api/capture/voice`
- `POST /api/capture/card`
- `POST /api/imports/contacts`
- `POST /api/imports/calendar`
- `POST /api/sources`

### Profiles

- `GET /api/profiles`
- `GET /api/profiles/:id`
- `PATCH /api/profiles/:id`
- `POST /api/profiles/:id/merge`
- `POST /api/profiles/:id/facts`
- `PATCH /api/profile-facts/:id`

### Search and Recall

- `POST /api/search`
- `POST /api/recall`
- `GET /api/clusters`
- `GET /api/events/:id/recap`

### Opportunity Mode

- `POST /api/goals`
- `GET /api/goals`
- `GET /api/goals/:id`
- `POST /api/goals/:id/matches`
- `PATCH /api/goal-matches/:id`

### Follow-Up and Outreach

- `GET /api/follow-ups`
- `POST /api/follow-ups/generate`
- `PATCH /api/follow-ups/:id`
- `POST /api/outreach/drafts`
- `PATCH /api/outreach/drafts/:id`

## 7. Search and Retrieval Design

Use hybrid retrieval for all important intelligence features:

- Vector similarity over interactions, profile summaries, and clusters.
- Postgres full-text search for names, orgs, titles, and event labels.
- Metadata filters for location, organization, event, source type, and tags.
- Recency and relationship-strength reranking.
- Result explanations that cite source interactions or facts.

Search results should return profiles plus the specific memories that explain the match. This prevents the system from feeling magical in an untrustworthy way.

## 8. Background Jobs

### Required Jobs

- `process_capture_source`: extraction, linking, embedding, persistence.
- `refresh_profile_summary`: updates AI profile summaries after new interactions.
- `generate_follow_ups`: creates daily suggestion set.
- `evaluate_goal_matches`: refreshes matches when goals or memories change.
- `compute_network_clusters`: periodically refreshes clusters.
- `generate_event_recap`: runs after event-mode sessions.
- `cleanup_expired_pending_data`: removes stale pre-auth or abandoned imports.

Jobs should be idempotent. Each job needs status, retry count, error logging, and user ownership.

## 9. Privacy, Security, and Trust

Requirements:

- Row Level Security on every user-owned table.
- Encrypted storage for OAuth tokens and sensitive import credentials.
- Signed URLs for uploaded audio, cards, and import files.
- Explicit permission prompts before imports or enrichment.
- User-visible source provenance for important AI claims.
- Export and deletion flows for user data.
- No autonomous message sending.
- No public profile or social graph exposure.

AI prompts must avoid sending unnecessary private data. Prefer narrow context windows over full-profile dumps.

## 10. Observability

Track:

- Capture processing latency and failure rate.
- Entity-linking confidence and user correction rate.
- Search success and zero-result rate.
- Goal match acceptance and dismissal reasons.
- Follow-up suggestion acceptance, snooze, and dismissal rates.
- Draft copy/edit rate.
- AI cost per active user.
- Background job retries and dead-letter counts.

Log AI inputs and outputs only when privacy settings and retention policy allow it. Redact sensitive values where possible.

## 11. Performance Targets

- Text capture preview: first visible structured result within 2 seconds when possible.
- Voice transcription plus extraction: under 10 seconds for a short note.
- Search results: under 1 second for warm queries, under 3 seconds cold.
- Opportunity Mode initial result set: under 8 seconds.
- Follow-up dashboard load: under 1.5 seconds.
- Event recap generation: asynchronous, visible progress state required.

## 12. Testing Strategy

### Unit Tests

- Extraction schema validation.
- Entity-linking candidate scoring.
- Goal parser schema validation.
- Ranking formula behavior.
- Follow-up scoring.
- Draft prompt guardrails.

### Integration Tests

- Capture source -> interaction -> profile update.
- Goal creation -> candidate retrieval -> match storage.
- Follow-up generation -> dismissal/snooze feedback.
- Profile merge preserves interactions and facts.
- RLS prevents cross-user reads and writes.

### AI Evaluation Tests

Maintain fixture-based evals for:

- Name, role, company, event, and follow-up extraction.
- Duplicate detection.
- Opportunity Mode relevance.
- Draft factuality.
- Tone compliance.

### Product QA

- Event capture with 10+ rapid entries.
- Goal flow with sparse and rich networks.
- Search with vague natural language.
- Correction flows for wrong AI facts.
- Data deletion and export.

## 13. Release Plan

### Phase 1: Trustworthy Data Expansion

- Voice capture.
- Business card OCR.
- Contact import.
- Sources and profile facts.
- Profile correction and merge tools.

### Phase 2: Action Intelligence

- Goals.
- Opportunity Mode retrieval and ranking.
- Context-aware follow-ups.
- User-initiated outreach drafts.

### Phase 3: Insight Layer

- Network clusters.
- Event recaps.
- Rediscovery surfaces.
- Relationship health views.
- Optional graph exploration.

### Phase 4: Integrations

- Calendar context.
- Share sheet and mobile-first capture.
- Email metadata only if permission and trust posture are strong.
- Campus/event templates for distribution.
