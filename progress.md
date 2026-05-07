# Orbit Progress

## Status

Stage one of the product is complete.

The MVP exists as a functioning vertical slice:
- capture starts on the landing page
- extraction happens before auth
- OAuth completes the handshake
- the memory is committed into Supabase
- the user can view saved profiles and interactions
- the user can search semantically and review follow-up lanes

This means the core product thesis has been proven in software, not just in docs.

## What has been implemented

### 1. Product flow
- Inverted onboarding is implemented.
- The homepage acts as both acquisition surface and primary product surface.
- Users can type a relationship note immediately.
- The app shows a structured preview before authentication.
- Users can authenticate only when they choose to save.
- After auth, the app restores pending state and completes the save flow.

### 2. AI extraction and search plumbing
- A canonical extraction schema was defined and enforced with Zod.
- Structured extraction is available through `/api/extract`.
- Embeddings are generated for searchable memory text.
- Semantic search is available through `/api/search` and a Postgres RPC.
- Query results are grouped by profile rather than shown as flat rows.

### 3. Data model and persistence
- Supabase schema exists for `profiles`, `interactions`, and `events`.
- RLS is enabled across the main tables.
- Profile records track identity, org, `job_role`, and follow-up timing.
- Interaction records track the original note, derived summary, tags, sentiment, follow-up suggestion, and vector.
- The app commits a profile and interaction together as part of the save path.

### 4. Matching and ambiguity handling
- Identity normalization exists for name and org.
- The app scores candidate profile matches.
- High-confidence matches auto-link.
- Mid-confidence matches trigger a user confirmation step.
- Low-confidence matches create a new profile.

### 5. Authenticated product surfaces
- Dashboard route exists at `/app`.
- Profile detail route exists at `/profiles/[id]`.
- Dashboard includes:
  - search
  - recent captures
  - overdue follow-ups
  - upcoming follow-ups
- Profiles include:
  - top-level identity summary
  - follow-up cadence visibility
  - reverse-chronological timeline

### 6. Design and experience
- The UI is not a placeholder scaffold; it has a defined soft-tech visual direction.
- Capture, preview, dashboard, and profile surfaces all have product-level styling.
- The extraction preview uses staged reveal behavior to make the result legible and emotionally satisfying.

### 7. Tooling and quality bar
- The repo has app/tooling scaffolding in place.
- Environment template and setup docs exist.
- Unit tests cover validation and core memory logic.
- A Playwright smoke test exists.
- The app currently builds and validates cleanly.

## Important nuances and implementation details

### OpenAI fallback behavior
- The app can run without `OPENAI_API_KEY`.
- In that case it uses heuristic extraction and pseudo-embeddings.
- This is useful for local development and UI iteration.
- It is not a substitute for production-grade extraction quality or search quality.

### Pre-auth persistence is browser-only
- Anonymous capture state is stored in `localStorage`.
- This keeps the MVP simple and fast.
- It also means pending capture is tied to the same browser context and is not durable across device changes or storage clearing.

### Current matching is intentionally lightweight
- Match scoring is rule-based, not model-based.
- This is appropriate for the first stage, but it will eventually need stronger identity resolution if the dataset grows or names become ambiguous.

### Search quality is foundational, not final
- The vector path exists and works.
- Ranking, hybrid retrieval, caching, and search UX refinement are still open improvement areas.

### Schema evolution discipline matters now
- The init migration has already been edited during early-stage development, which is fine while the project is young.
- Going forward, changes should be added as new forward migrations instead of rewriting the init migration once shared environments exist.

### Observability is useful but still light
- Basic event tracking exists.
- There is not yet a full analytics layer, dashboard instrumentation pipeline, or alerting/monitoring setup.

## What is left to do or improve

### Product depth
- Add better reminder workflows beyond passive dashboard lanes.
- Add manual profile correction/editing for extracted mistakes.
- Add richer profile metadata and optional enrichment.
- Add better empty states and first-run onboarding guidance once multiple-user testing begins.

### Capture inputs
- Add voice capture.
- Add OCR/business card ingestion.
- Add mobile-native or share-sheet capture paths.

### Search and memory quality
- Improve extraction prompts and schema behavior based on real usage.
- Improve match scoring and disambiguation heuristics.
- Improve semantic search ranking and result explanations.
- Consider hybrid search using both vectors and structured filters.

### Reliability and robustness
- Add authenticated E2E tests against a real Supabase/OpenAI environment.
- Add more failure-path handling around OAuth, extraction outages, and partial commit problems.
- Add retry strategies or job-based handling if embedding or extraction latency becomes an issue.

### Operations and analytics
- Add proper production monitoring and error reporting.
- Expand funnel instrumentation and connect it to actual dashboards.
- Measure the 30-second first-memory success metric in a way that can be tracked longitudinally.

### Security and data governance
- Review auth and RLS behavior in a production deployment.
- Tighten secrets handling and deployment docs as environments multiply.
- Add data lifecycle policies if deletion/export/privacy requirements become important.

## Recommended next phase

The best next phase is not another broad surface-area expansion. It is a quality-and-learning phase around the existing loop.

Priority order:
- improve extraction accuracy and matching quality
- strengthen authenticated end-to-end tests
- improve search quality and explanation
- refine follow-up usefulness
- only then broaden inputs or add enrichment

That sequence gives the product a better chance of becoming trustworthy before it becomes larger.
