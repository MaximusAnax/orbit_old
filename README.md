# Orbit

Orbit is a capture-first relational memory app for turning messy interpersonal notes into structured, searchable relationship memory.

The current product proves the first stage of the concept:
- a user can land on the homepage
- paste an unstructured note before authenticating
- see a structured memory preview
- sign in with Google
- save the note into a private memory graph
- revisit that person later through timelines, semantic search, and follow-up lanes

## Product overview

Orbit is designed around one core promise: reduce the cognitive overhead of maintaining a network.

Instead of asking the user to fill out a CRM-style contact form, Orbit begins with a natural-language capture flow. The user writes the rough note they would have otherwise kept in their head, notes app, or chat draft. The system extracts:
- who the person is
- where or how they were met
- the user’s read on the interaction
- relevant tags and context
- an estimated follow-up interval

The app then saves that memory into a private, user-scoped data model backed by Supabase and makes it retrievable by meaning, not just exact keywords.

## What exists today

### Capture-first landing flow
- The homepage is the primary product surface, not a marketing-only landing page.
- Users can type a freeform relationship note immediately, before auth.
- Draft text and extracted preview state are stored in `localStorage`.
- The interface animates a staged “memory reveal” so the structured result feels responsive and legible.

### AI extraction
- `POST /api/extract` accepts raw text and returns validated structured memory data.
- The extraction contract includes contact info, interaction summary/context, sentiment, tags, follow-up timing, and match hints.
- If `OPENAI_API_KEY` is configured, the app uses OpenAI for extraction and embeddings.
- If no OpenAI key is present, the app falls back to deterministic local extraction and pseudo-embeddings so the app remains runnable in development.

### Auth and post-auth handshake
- Google sign-in is implemented through Supabase Auth.
- The “save” path supports inverted onboarding: capture first, auth second.
- After auth callback, the app restores the pending capture from browser storage and attempts to commit it without requiring the user to re-enter the note.

### Memory persistence
- Profile and interaction data are stored in Supabase Postgres.
- The initial schema includes:
  - `profiles`
  - `interactions`
  - `events`
- Row-level security is enabled so users can only access their own records.
- The role field on profiles is stored as `job_role`.

### Matching and dedupe behavior
- Orbit attempts to determine whether a new capture belongs to an existing profile.
- Exact or high-confidence matches auto-link.
- Ambiguous matches return a confirmation state so the user can choose:
  - link to an existing person
  - create a new profile

### Authenticated product surfaces
- `/app` provides:
  - semantic search
  - recent captures
  - overdue follow-ups
  - upcoming follow-ups
- `/profiles/[id]` provides:
  - profile summary
  - job role and company
  - follow-up timing
  - reverse-chronological interaction timeline

### Search
- `POST /api/search` embeds the query and calls a Supabase RPC over vector data.
- Search is semantic rather than exact-match only.
- Results are grouped by person and include the most relevant interactions/snippets.

### Event tracking and product telemetry
- The app records lightweight product events in the `events` table.
- Current tracked events include:
  - `capture_started`
  - `extract_succeeded`
  - `extract_failed`
  - `oauth_started`
  - `memory_saved`
  - `search_run`
  - `search_result_opened`

### Testing and validation
- Unit tests cover core validation and memory logic.
- A Playwright smoke test covers the landing/capture surface.
- The app currently passes:
  - `npm run test`
  - `npm run lint`
  - `npm run build`

## Architecture

### Frontend
- Next.js App Router
- React
- Tailwind CSS
- Motion for reveal/transition behavior

### Backend and data
- Next.js route handlers for app APIs
- Supabase Auth for Google OAuth
- Supabase Postgres for relational storage
- `pgvector` for semantic search support

### AI layer
- OpenAI extraction for structured memory parsing
- OpenAI embeddings for semantic search vectors
- Local fallback behavior for development when OpenAI keys are absent

## Key routes and APIs

### App routes
- `/`
- `/app`
- `/profiles/[id]`
- `/auth/login`
- `/auth/callback`
- `/auth/error`

### API routes
- `POST /api/extract`
- `POST /api/memories/commit`
- `POST /api/search`
- `POST /api/events`

## Data model summary

### `profiles`
Stores the canonical person record for a given user.

Important fields:
- `full_name`
- `normalized_name`
- `current_org`
- `job_role`
- `metadata`
- `last_interaction_at`
- `next_follow_up_at`
- `follow_up_interval_days`

### `interactions`
Stores each captured note tied to a profile.

Important fields:
- `raw_content`
- `structured_summary`
- `search_text`
- `tags`
- `sentiment`
- `suggested_follow_up_days`
- `embedding`
- `interaction_date`

### `events`
Stores lightweight telemetry and funnel data.

## Environment and required setup

Copy `.env.example` to `.env.local`.

Required values:
- `OPENAI_API_KEY`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- `NEXT_PUBLIC_APP_URL`

Optional values:
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ACCESS_TOKEN`
- `SUPABASE_DB_PASSWORD`

Platform-side requirements:
- a Supabase project
- Google OAuth client credentials configured inside Supabase Auth
- redirect URLs configured in both Google and Supabase
- Postgres with `vector` enabled

Recommended local runtime:
- Node `20.17+`

## Local development

Install dependencies:

```bash
npm install
```

Start local Supabase if using the local DB workflow:

```bash
npx supabase start
```

Apply migrations:

```bash
npx supabase db push
```

Run the app:

```bash
npm run dev
```

## Testing

Unit tests:

```bash
npm run test
```

E2E smoke test:

```bash
npm run test:e2e
```

Production build validation:

```bash
npm run build
```

## Current limitations

- Voice capture is not implemented.
- Apple auth is not implemented.
- Outbound reminders are not implemented.
- Contact enrichment is not implemented.
- Manual profile editing is not implemented.
- Search uses vector lookup, but ranking and retrieval strategy are still basic.
- The Playwright suite is still minimal and does not yet cover full authenticated end-to-end flows against a real Supabase/OpenAI environment.

## Notes for future development

- The normal runtime path uses authenticated Supabase sessions with RLS, not the service-role key.
- The OpenAI fallback path is useful for local development, but production quality depends on real model-backed extraction and embeddings.
- If the schema has already been applied in another environment, schema changes should be added as forward migrations rather than by editing the original init migration.
