# Orbit PRD: Relationship Intelligence After MVP

## 1. Executive Summary

Orbit's completed MVP proves the "relief layer": a user can capture a relationship memory in natural language, have it structured by AI, save it to a private profile, retrieve it semantically, and receive simple follow-up prompts.

This PRD defines the next product stage: the "action layer." Orbit should evolve from a private relationship memory system into relationship intelligence software that helps ambitious students and early-career professionals sustain, understand, and activate their networks without making relationships feel transactional.

The product must remain private, calm, and human. It is not a social network, a public profile product, or a sales CRM. It is a personal AI memory and guidance system for relational continuity.

## 2. Product Thesis

Orbit remembers the user's relationships better than they can and helps them sustain and activate those relationships meaningfully over time.

The next stage moves the core user promise from:

> "I no longer have to carry all of this in my head."

to:

> "I can see who matters for what I am trying to do, understand why, and take the next thoughtful step."

## 3. Baseline Assumptions

This PRD assumes the previous MVP scope is complete:

- Inverted onboarding with first capture before authentication.
- Natural language extraction into structured memory cards.
- Private relationship profiles with timelines and metadata.
- Semantic search across people and interactions.
- Basic "going cold" reminders based on recency.
- Supabase-backed authentication, storage, and vector search.

The next stage should build on these behaviors rather than replace them.

## 4. Target Users

### Primary ICP

Ambitious students and early-career professionals managing high-opportunity weak ties:

- University students at dense opportunity networks such as Carnegie Mellon, Stanford, and UC Berkeley.
- Founders, builders, club leaders, hackathon attendees, and conference-heavy students.
- Early-career operators recruiting, fundraising, hiring, collaborating, or exploring new domains.

### Initial Distribution Wedge

Events remain the strongest acquisition moment:

> "Went to a networking event? Never lose track of those conversations again."

Orbit should support career fairs, hackathons, mixers, conferences, startup events, and club ecosystems where many shallow but valuable connections are formed quickly.

## 5. Strategic Product Goals

1. Turn captured memory into useful action.
2. Make hidden network value visible without making the interface graph-first.
3. Help users follow up warmly and specifically, without guilt or hustle-culture language.
4. Support richer capture channels while preserving the zero-form product feel.
5. Build trust through privacy, provenance, user control, and permissioned enrichment.

## 6. Core Jobs To Be Done

- When I meet several people at an event, I want to capture them quickly so I do not forget who they are or why they mattered.
- When I have a goal, I want Orbit to surface relevant people and explain the connection so I can act intelligently.
- When a relationship is fading, I want a gentle, specific reason to reconnect so follow-up feels natural.
- When I search my network, I want results based on meaning, context, and relationship history rather than exact keywords.
- When Orbit suggests an action, I want to trust where the suggestion came from and stay in control before anything is sent.

## 7. Functional Requirements

### 7.1 Opportunity Mode

Opportunity Mode is the flagship post-MVP feature.

Users can enter a goal in natural language, such as:

- "Looking for ML internships in SF."
- "I want to meet climate tech founders."
- "Who could help me prepare for Databricks recruiting?"
- "I need sponsors for a hackathon."

Orbit must:

- Parse the goal into structured intent, domain, geography, timing, and desired outcome.
- Retrieve relevant people from profiles, interactions, tags, organizations, and semantic memory.
- Rank people by relevance, relationship strength, recency, and explainability.
- Show why each person appears.
- Identify warm paths, shared contexts, dormant relationships, and useful clusters.
- Suggest the next best action for each candidate.
- Allow the user to save the goal and revisit it as new memories are added.

Success condition: a user can enter a goal and identify at least three relevant people or paths in under 60 seconds.

### 7.2 Context-Aware Follow-Up Engine

The MVP reminder system evolves from simple recency alerts into thoughtful relationship maintenance.

Orbit must generate follow-up suggestions using:

- Time since last interaction.
- Relationship strength and user-defined importance.
- Open loops from prior conversations.
- User goals.
- Events, recruiting cycles, school calendars, and known deadlines.
- Explicit reminders set by the user.

Each suggestion must include:

- The person.
- The reason Orbit is suggesting the follow-up.
- Relevant memory snippets.
- A suggested channel when known.
- A dismissal, snooze, or "not relevant" action.

The tone must be warm and non-judgmental. Avoid guilt, urgency theater, and "networking grind" language.

### 7.3 AI Outreach Drafts

Orbit may draft outreach but must not send messages autonomously.

Users can request drafts from:

- A profile.
- A follow-up suggestion.
- An Opportunity Mode result.
- A recent event recap.

Drafts must:

- Reference specific shared context.
- Match the relationship's warmth and formality.
- Offer 2-3 tone variants when useful.
- Be editable before copying or sending.
- Avoid exaggerating closeness or inventing facts.

Sending through external channels is future scope. For this stage, copy-to-clipboard and mailto/deeplink handoff are sufficient.

### 7.4 Multi-Modal Capture Expansion

The original fast capture loop remains the product's foundation. The next stage should support more real-world capture moments:

- Voice notes for post-event or walking capture.
- Business card OCR.
- Contact import from phone or CSV.
- Calendar event context.
- Share sheet/link capture for profiles or social pages.

All capture paths must resolve into the same memory model:

- Raw source.
- Extracted entities.
- Suggested profile link or new profile.
- User validation.
- Embedded searchable memory.
- Possible follow-up or goal relevance.

### 7.5 Relationship Profiles 2.0

Profiles should become living relationship records, not static contact pages.

Each profile should include:

- AI-generated relationship summary.
- Timeline of interactions and captured memories.
- Current role, organization, location, interests, and links.
- Relationship strength signal.
- Open loops and promised follow-ups.
- Shared contexts, events, and mutual clusters.
- Related goals and opportunity matches.
- Source provenance for important facts.

Users must be able to correct fields, merge duplicates, add private notes, and mark sensitive information.

### 7.6 Network Insight Layer

Orbit should create the "my network is richer than I thought" moment without making a graph UI the default product surface.

Required insight views:

- Clusters by event, community, company, school, domain, and geography.
- Rediscovered people who are relevant but dormant.
- Event recap showing who was met, themes, and follow-up opportunities.
- Relationship health view for important contacts.
- Search-driven mini-maps for a specific goal or domain.

Graph visualization may appear as an optional exploratory view, but it must not become the primary navigation model.

### 7.7 Permissioned Enrichment

Orbit should enrich user-entered relationship memory carefully and transparently.

Allowed enrichment:

- User-provided profile links.
- Contact import fields.
- Calendar metadata approved by the user.
- Public profile fields when the user supplies the URL.
- Lightweight organization and location normalization.

Out of scope for this stage:

- Massive scraping infrastructure.
- LinkedIn replication.
- Autonomous background surveillance of contacts.
- Public social network features.

Every enriched fact should show its source or confidence when surfaced in decision-making contexts.

### 7.8 Event Mode

Event Mode packages the event wedge into a repeatable workflow.

Users can create or select an event and rapidly capture multiple people against that context. After the event, Orbit produces:

- A recap of people met.
- Themes and clusters.
- Suggested high-priority follow-ups.
- Opportunity matches against active goals.
- Draftable outreach prompts.

This mode should be optimized for hackathons, career fairs, club events, conferences, and mixers.

## 8. User Experience Principles

- Natural language remains the primary interface.
- No heavy forms unless editing structured details is explicitly requested.
- Suggestions should feel like relief and clarity, not obligation.
- Use language of memory, continuity, thoughtfulness, and opportunity.
- Avoid "leverage your network," "grind," "maximize relationships," or CRM-coded language.
- Keep the interface private by default and emotionally warm.
- Reveal AI reasoning enough to build trust, but do not overwhelm the user.

## 9. Non-Goals

- Public profiles or social feeds.
- Follower/friend mechanics.
- Sales pipeline management.
- Company CRM administration.
- Graph-first navigation as the default interface.
- Fully automated sending of messages.
- Large-scale scraping or contact surveillance.

## 10. Success Metrics

### Activation

- Percentage of users who create a second memory within 7 days.
- Percentage of event-mode users who capture 5+ people in one session.
- Percentage of users who connect at least one optional import source.

### Retention

- Weekly captured memories per active user.
- Weekly meaningful relationship actions completed.
- Follow-up suggestion acceptance rate.
- Percentage of users returning to an active goal.

### Intelligence Quality

- Opportunity Mode precision: user marks a suggested person/path as useful.
- Search success: user finds the intended person in the first result set.
- Draft usefulness: user copies or edits an AI-generated draft.
- Duplicate merge accuracy and user correction rate.

### Trust

- Percentage of AI suggestions with visible provenance.
- Low rate of "wrong person" or "invented fact" feedback.
- Deletion/export completion reliability.

## 11. Release Phasing

### V2.1: Capture Expansion and Profile Trust

- Voice capture.
- Business card OCR.
- Contact import.
- Profile merge and correction flows.
- Source provenance for extracted and enriched fields.

### V2.2: Action Layer

- Opportunity Mode.
- Context-aware follow-up suggestions.
- AI outreach drafts.
- Saved goals.

### V2.3: Network Insight Layer

- Clusters.
- Event recaps.
- Rediscovery surfaces.
- Relationship health views.
- Optional exploratory graph.

### V2.4: Integrations and Distribution Loops

- Calendar and email context with explicit permission.
- Share sheet and mobile-first capture.
- Event templates for campus and conference use.
- Lightweight team or club pilots only if they preserve private user memory.
