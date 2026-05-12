# Orbit Progress

## Status

The MVP is complete, and the first post-MVP buildout pass has now landed.

Orbit is no longer just a functioning vertical slice. It now has the broader product loop described in the PRD/TDD:
- capture can start from text, audio upload, or business card image upload
- extraction can stream partial preview state before returning the final structured payload
- pending captures are durable enough to survive auth redirects and commit retries
- memories are committed idempotently with a stable `captureId`
- profiles can be corrected manually after extraction
- search uses vector similarity plus structured ranking signals and explanations
- follow-ups can be acted on from the dashboard and profile surfaces
- daily reminder logging/digest infrastructure exists
- profile enrichment and outreach drafting exist as explicit action-layer endpoints
- advanced recall surfaces are feature-flagged instead of exposed prematurely

The product is still early, but the major post-MVP architecture is now represented in code.

## What has been implemented

### 1. Capture and onboarding
- Inverted onboarding remains implemented.
- The homepage is still both the acquisition surface and the primary capture surface.
- Users can type a relationship note immediately before authentication.
- Users can upload an audio note through `/api/capture/audio`.
- Users can upload a business card image through `/api/capture/card`.
- Audio and card routes use OpenAI when `OPENAI_API_KEY` is configured and fall back to local development text when it is not.
- Capture state now includes a stable `captureId`.
- Auth redirects preserve the intended post-auth commit route with `captureId`.

### 2. Streaming extraction
- `/api/extract` keeps the original JSON behavior and now supports an opt-in streaming mode.
- The landing preview can render partial extraction patches before the final structured result arrives.
- Streaming events include metadata, preview patches, final extraction, and error events.
- The preview UI was updated from a timer-only staged reveal to real progressive extraction state.
- Extraction success events now include timing metadata for first-memory funnel measurement.

### 3. Durable pending captures and idempotent commits
- A new `pending_captures` table stores pre-auth captures by `captureId` and anonymous id.
- A `claim_pending_capture` Postgres function lets an authenticated user claim a pending capture after OAuth.
- `/api/memories/commit` now requires `captureId`.
- Commit can recover raw text and extraction from the server-side pending capture record.
- Duplicate commit attempts return the existing profile/interaction when the capture has already been committed.
- Commit events now include `timeToMemoryMs` when capture start timing is available.

### 4. Data model and migrations
- New forward migrations were added instead of editing the init migration.
- Added `pending_captures` for durable pre-auth capture recovery.
- Replaced `search_interactions` with a new return shape that includes `search_text`.
- Added `reminders` for follow-up action and digest tracking.
- Added `enrichment_jobs` for profile enrichment provenance.
- The `search_interactions` migration now drops the previous function signature before recreating it, which avoids PostgreSQL return-type errors.

### 5. Matching and ambiguity handling
- Identity normalization still exists for name and org.
- Candidate matching is no longer limited to exact `normalized_name` lookup.
- The commit path now considers recent profiles and filters candidates by partial name or org hints before scoring.
- Existing high-confidence, ambiguous, and create-new match decisions remain intact.
- Unit tests cover partial-name and org-hint candidate selection.

### 6. Profile correction and profile surfaces
- Profiles can now be edited from `/profiles/[id]`.
- The profile edit API supports name, company, role, cadence, and metadata updates.
- Name updates also refresh `normalized_name`.
- Profile update events are tracked.
- Profile pages now include profile editing, follow-up actions, enrichment, and outreach drafting controls.

### 7. Search and recall
- `/api/search` still embeds natural-language queries and calls the Supabase vector RPC.
- Search results are still grouped by profile.
- Results now include `whyMatched` explanations.
- Ranking now combines vector similarity with structured boosts from tags, org, role, and memory text overlap.
- Search has a five-minute cache path using Upstash REST when configured.
- If Upstash is not configured, search falls back to a process-local memory cache.
- Search telemetry now records cache hits.

### 8. Follow-up engine
- Follow-up actions are implemented through `/api/profiles/[id]/follow-up`.
- Users can mark contacted, snooze, set cadence through the API, and pause follow-ups.
- Dashboard follow-up lanes now include quick actions.
- Profile pages include richer follow-up controls.
- A protected `/api/reminders/daily-digest` route can generate daily reminder records.
- Reminder records prevent duplicate daily sends for the same profile.
- The daily digest currently logs reminder delivery state and can be connected to a real email provider.

### 9. Action layer
- `/api/profiles/[id]/enrich` writes conservative enrichment metadata onto the profile.
- Enrichment provenance is stored in `enrichment_jobs`.
- `/api/profiles/[id]/outreach-draft` creates a follow-up draft from saved profile and interaction context.
- Outreach drafting uses OpenAI when configured and a local fallback when not.
- Advanced recall capabilities are exposed through `/api/recall/features`.
- Graph recall, voice search, and external sync are feature-flagged by environment variables.

### 10. Tooling and quality bar
- `npm run lint` was migrated from deprecated `next lint` to `eslint .`.
- `eslint.config.mjs` was added for the ESLint CLI.
- Unit coverage now includes validation, memory logic, streaming preview helpers, search ranking, upload validation, reminders, and action-layer helpers.
- Current verification passes:
  - `npm test`: 24 tests passing
  - `npm run lint`: passing
  - `npm run build`: passing

## Important nuances and implementation details

### OpenAI fallback behavior
- The app can still run without `OPENAI_API_KEY`.
- Extraction uses heuristic fallback behavior.
- Embeddings use pseudo-embeddings.
- Audio upload returns a development transcript placeholder.
- Business card upload returns a development OCR placeholder.
- Outreach drafts use a deterministic local fallback.
- These fallbacks keep development unblocked, but production quality depends on real OpenAI-backed extraction, transcription, OCR, embeddings, and drafting.

### Pending captures are now server-backed
- Pre-auth capture is no longer browser-only.
- `localStorage` is still used for fast client recovery and draft UX.
- The server-side `pending_captures` table is now the durable recovery path for auth redirects and commit retries.
- Pending capture recovery depends on the anonymous id and `captureId` staying available through the handoff.

### Search quality is improved, not final
- Search now has hybrid ranking and result explanations.
- The hybrid layer is intentionally simple and testable.
- Upstash caching is optional.
- Future ranking work should be based on real search logs and user feedback rather than more speculative heuristics.

### Follow-up delivery now has a real email path
- Follow-up action state exists.
- Daily digest records can be generated.
- `/api/reminders/daily-digest` now uses a service-role Supabase client for cron-safe cross-user processing.
- Resend delivery is wired through direct REST calls, with one grouped digest email per user.
- Reminder rows now track sent, failed, and skipped delivery outcomes with provider payload details.
- Notification preferences and signed unsubscribe links are implemented.

### Audio and card capture are ingestion paths, not full asset management
- File type and size validation exist.
- Uploaded files are processed directly by the API route.
- AI calls now use explicit timeout/retry behavior.
- Audio and card responses include review status for fallback or low-confidence output.
- Supabase Storage persistence for original audio/card assets is not yet implemented.
- Low-confidence OCR review is not yet a dedicated UI state.

### Enrichment is conservative
- Enrichment does not scrape external websites.
- The current implementation stores provenance, confidence, suggested search text, and public search links.
- This avoids silently adding unverified personal data while still creating the metadata path the future enrichment system needs.

### Schema evolution discipline remains important
- All post-MVP schema changes are forward migrations.
- The search RPC migration intentionally drops and recreates the function because PostgreSQL cannot change a table-returning function signature with `create or replace`.
- Shared or production environments should apply migrations in order.

### Observability is broader but still not complete
- Funnel, search, profile update, follow-up, reminder, enrichment, upload, and outreach events are now tracked.
- A staging SQL ops report now exists for event counts, reminder delivery state, and time-to-memory percentiles.
- There is still no dedicated analytics dashboard, alerting pipeline, or error-reporting service.

## Latest hardening pass

- Added `notification_preferences` with RLS and reminder status support for skipped deliveries.
- Added a service-role Supabase client for trusted cron/server jobs.
- Reworked daily digest generation to require `CRON_SECRET`, use Resend, group reminders by user, suppress duplicate daily sends, and respect pause/unsubscribe preferences.
- Added authenticated notification preference and signed unsubscribe endpoints.
- Added Resend email utilities, unsubscribe token utilities, reminder email builders, and tests.
- Added AI retry/timeout helpers used by extraction, embeddings, transcription, card OCR, and outreach drafts.
- Added low-confidence review metadata to audio and card capture responses.
- Added staging runbook, staging readiness script, ops SQL report, and a skipped authenticated Playwright staging smoke.
- Verification now passes:
  - `npm test`: 32 tests passing
  - `npm run lint`: passing
  - `npm run build`: passing
  - `npm run test:e2e`: 1 passing, 1 skipped unless `STAGING_AUTH_STATE` is configured

## What is left to do or improve

### Production reliability
- Add authenticated E2E tests against a real Supabase/OpenAI environment.
- Add route-level integration tests for commit recovery, profile edit, reminder actions, upload processing, and action-layer endpoints.
- Add explicit retry/backoff behavior around Supabase and deeper route-level provider failures.
- Add a background job model if extraction, transcription, OCR, or enrichment latency becomes noticeable.

### Notifications and reminders
- Configure Resend credentials and verify real delivery in staging.
- Add a scheduled job configuration for production cron.
- Add delivery observability for sent, failed, retried, and skipped reminder batches.

### Capture inputs
- Add browser recording instead of upload-only voice capture.
- Store source audio/card assets in Supabase Storage if users need auditability or later reprocessing.
- Add confidence/review UI for OCR and transcription results.
- Add mobile share-sheet or PWA capture support.

### Search and memory quality
- Tune extraction prompts against real examples.
- Add regression fixtures for ambiguous names, duplicate contacts, and noisy notes.
- Improve ranking with real feedback signals.
- Add structured filters for tags, org, role, recency, and sentiment.

### Action layer
- Keep enrichment behind explicit user action until quality is proven.
- Add user approval and copy controls around outreach drafts.
- Add provenance display for enriched metadata.
- Keep graph recall, voice search, and external sync behind feature flags until each has a complete implementation and tests.

### Security and governance
- Review all new RLS policies in a production Supabase project.
- Add data export and deletion flows.
- Add rate limits for extraction, upload, search, outreach, and reminder endpoints.
- Add stronger upload scanning if original files are persisted.

## Recommended next phase

The next phase should be a hardening and validation phase, not another broad expansion.

Priority order:
- apply and verify all Supabase migrations in a real environment
- test anonymous capture to auth to idempotent save end-to-end
- connect real OpenAI transcription/OCR behavior and review upload latency
- connect real daily email delivery behind `CRON_SECRET`
- add authenticated Playwright coverage for save, edit, search, follow-up actions, and outreach draft generation
- instrument a simple dashboard or SQL report for time-to-first-memory and search success

The product now has the planned post-MVP surface area. The next bit of leverage is making that surface trustworthy under real usage.
