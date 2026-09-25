# AURA — Brainstorm

_This file is deliberately messy. It's where we argue through open questions before anything gets locked into `project-spec.md`._

## Context already fixed by the project brief (not open questions)
- 3-layer intelligence engine: heuristic pre-filter → LLM classification → sentiment trend tracking.
- RAG grounded in 6 policy knowledge-base documents; top-3 chunk retrieval; citation required on every AI-generated reply.
- Autonomous agent, ReAct-style (Thought → Action → Observation), minimum 4 tools implemented (spec names 8 candidates), hard cap on tool calls per email, dry-run mode required, **never** auto-replies to Critical-urgency email.
- Web-intelligence enrichment for reputation-sensitive threads: minimum 2 scraping targets, async, cached, robots.txt-respecting, degrades gracefully.
- 3 dashboard views: Mission Control Inbox, Thread Workspace, Analytics.
- 5 synthetic demo scenarios double as acceptance tests: DSAR, security/extortion threat, own-product misinformation, reputation crisis, conflicting thread signals.
- Deliverables: git repo w/ atomic history, README, architecture diagram, KB source docs, ER diagram + SQL + migrations, recorded walkthrough, OpenAPI spec.

## Data model sketch
Grouped by subsystem — see chat for full rationale per entity.
- CRM: `contacts`, `accounts` (kept separate — one account can have multiple contacts)
- Email/threading: `threads`, `messages` (unique external `message_id` = idempotency key; `received_at` separate from `created_at` for out-of-order handling)
- Intelligence: `classifications` — deliberately denormalized with `contact_id` directly on the row (not just via message→thread→contact) so the 30-day sentiment-trend performance target can hit a single indexed query.
- RAG: `kb_documents`, `kb_chunks` (pgvector embedding column), `rag_retrievals` (chunk + similarity score per run — powers both citation and the debug search endpoint).
- Agent: `agent_runs` (one per processed email; the ReAct reasoning trace is stored as a single JSON blob field on this row — simpler than a per-step table, still satisfies the "human-readable reasoning log" requirement), `tickets`, `escalations`, `legal_flags` (three separate typed tables, one per agent action type, rather than a unified table — matches the distinct tool signatures cleanly).
- Web intel: `market_intel_cache` (target type/id, jsonb data, fetched_at/expires_at for TTL).

## Open questions
- [ ] Auth/roles needed even for the demo, or single-tenant is fine? — team unsure yet; leaning single-tenant for MVP/V1 unless a specific need surfaces (see roadmap V2 note).

## Not yet discussed (flag these for whoever writes project-spec.md — propose, don't assume already decided)
- Agent tool signatures — exact input/output schema for each of the 8 tools.
- Content/topics for the 6 KB policy documents — only the count is fixed so far.
- API endpoint list — implied by the data model, not yet enumerated.
- Heuristic pre-filter specifics — actual keyword lists/rules for Layer 1 (spam, urgency, security).
- Escalation matrix — the brief references one for security threats; the priority→routing mapping isn't defined yet.
- Frontend breakdown — no component/page-level detail for the 3 dashboard views, just names.
- Testing strategy — how the 5 synthetic scenarios become automated tests.
- Deployment target — which free/cheap host for the demo.

## Ideas / options considered
- LLM/embeddings hybrid: hosted API (Claude/OpenAI) for classification + agent reasoning (reliability on structured output & tool-calling matters most here), self-hosted embedding model for RAG (cheap, no agentic reasoning needed, saves cost on repeated re-chunking during dev).
- Fully self-hosted LLM considered and set aside for now — GPU cost + reliability risk on structured output/tool-calling is too high given a 2–3 month timeline and no prior agent experience on the team.
- Vector storage: pgvector (recommended, fits "production-grade" brief language + single DB) vs. Chroma (faster to set up, but reads as a shortcut) vs. dedicated vector DB (Pinecone/Weaviate — overkill for a 6-doc KB).
- Agent framework: custom ReAct loop (recommended — easiest to prove hard constraints like Critical never-auto-reply) vs. LangGraph (faster but adds an abstraction layer to learn) vs. CrewAI/AutoGen (built for multi-agent, not needed here).

## Risks we're aware of
- Scope is large relative to a team/semester timeline — risk of over-building before the core loop is proven.
- **2–3 month deadline is tight for the full V1 scope in the brief (8 tools, 6 KB docs, 3 dashboard views, web scraping, performance benchmarking). Likely need to cut ruthlessly or extend some V1 items into V2 once the team sees real velocity in Phase 0/1.**
- LLM provider not yet chosen — this blocks the Phase 0 spike (single classification call), so it's the most time-sensitive open question right now.
- Work split not yet decided — worth locking down before Phase 0 ends, since "by layer" vs. "by phase" changes how the repo/branching strategy should be set up.
- The "never auto-reply to Critical urgency" guarantee needs dedicated test coverage, not incidental coverage.
- Scraping reliability / ToS risk — must degrade gracefully rather than block the pipeline.
- OpenAI doesn't have a generous ongoing free tier (unlike some initial trial credits) — running free/cheap only may mean watching usage closely once heavier testing (5 scenarios × repeated agent runs × RAG calls) starts. Worth checking current OpenAI pricing/free-tier terms before Phase 0 spike, and setting a hard spend cap on the account early.

## Decisions made so far (promote these to `project-spec.md` once settled)
- Deadline: 2–3 months from project start.
- Vector storage: pgvector (single Postgres DB).
- Agent framework: custom ReAct loop (full control, easiest to prove hard constraints for grading).
- LLM/embeddings: hosted API for classification + agent reasoning (provider TBD); self-hosted embedding model for RAG, run locally on team's RTX 3050 mobile GPUs (4GB VRAM — fine for embeddings, not for the main LLM).
- Side experiment (non-blocking, not in critical path): bounded half-day spike benchmarking a quantized ~7B local model against 2–3 synthetic scenarios, purely to see how close local gets — result feeds a future decision, doesn't gate Phase 0/1.
- LLM provider: OpenAI (for classification + agent reasoning).
- Conflicting-signal precedence rule: the most severe/actionable component determines `category`/`urgency` (e.g. praise + refund demand → treated as the refund demand); `sentiment_score` stays a continuous value and is free to reflect the mixed tone without needing a tie-break.
- Team split: build the MVP together first, split by feature/module once Phase 1 is underway.
- Budget: no course-provided credits — team will use free tiers/alternatives where possible.
- Stack: fully open choice, no instructor-mandated tools or constraints.
- Classification storage: separate `classifications` table (supports re-classification history, one row per LLM run on a message).
- Agent reasoning log: single JSON blob field on `agent_runs` (simpler; satisfies the reasoning-log requirement without a per-step table).
- Agent actions: separate typed tables (`tickets`, `escalations`, `legal_flags`) rather than one unified table — matches the distinct tool signatures without nullable-field bloat.
- Schema: `accounts` and `contacts` stay separate tables (one account can have multiple contacts).
- Sentiment trend: computed on-the-fly via an indexed query over `classifications` (indexed on `contact_id`/`sender_email` + timestamp) rather than a separate rollup table — simplest option that still meets the performance target; revisit only if benchmarking shows it's not fast enough.
