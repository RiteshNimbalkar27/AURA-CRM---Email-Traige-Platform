# AURA Implementation Specification Draft

## Summary

Build AURA as a single-tenant, locally deployed B2B SaaS email-triage system. It uses seeded `Operator` and `Supervisor` accounts, Docker Compose, PostgreSQL with pgvector, FastAPI, a React dashboard, local embeddings, and Gemini free-tier inference for synthetic data only. The revised Gemini decision supersedes OpenAI because the project has no API budget; free-tier content handling means real customer or PII data is out of scope. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)

The agent runs in supervised mode: it may create drafts, tickets, escalations, and legal flags, but only an Operator can approve a simulated outbound reply. Critical items never produce or send a customer reply.

## Data, API, and Ingestion

* Create `users`, `accounts`, `contacts`, `threads`, `messages`, `classifications`, `kb\_documents`, `kb\_chunks`, `rag\_retrievals`, `agent\_runs`, `tickets`, `escalations`, `legal\_flags`, `market\_intel\_cache`, and `audit\_log`.
* Keep `accounts` and `contacts` separate; keep classification history as append-only rows; store one redacted JSONB action/rationale trace per `agent\_run`.
* Enforce unique `messages.external\_message\_id`; index thread retrieval and `(contact\_id, received\_at)` sentiment queries; use pgvector cosine search on a 384-dimension embedding.
* Seed two roles: Operator can triage, edit drafts, and approve simulated sends; Supervisor can also resolve High/Critical escalations and legal/security records.
* Use a consistent API error envelope: `{ "error\_code", "message", "details" }`.

|Area|Endpoints|
|-|-|
|Auth|`POST /auth/login`, `POST /auth/logout`, `GET /auth/me`|
|Ingestion|`POST /api/ingest`, `POST /api/replay`, `GET /api/jobs/{job\_id}`|
|Inbox and threads|`GET /api/dashboard/stats`, `GET /api/threads`, `GET /api/threads/{thread\_id}`, `GET /api/messages/{message\_id}`|
|Agent and actions|`POST /api/messages/{id}/agent-runs`, `GET /api/agent-runs/{id}`, `PATCH /api/drafts/{id}`, `POST /api/drafts/{id}/approve`, `GET /api/tickets`, `GET /api/escalations`, `GET /api/legal-flags`|
|CRM and analytics|`GET /api/contacts/{email}`, `PATCH /api/contacts/{email}/status`, `GET /api/analytics/sentiment-trend`, `GET /api/analytics/category-breakdown`, `GET /api/analytics/at-risk-accounts`|
|RAG, web, audit|`GET /api/rag/search`, `GET /api/market-intelligence`, `GET /api/audit/{entity\_type}/{entity\_id}`, `GET /health`|

* Require inbound payloads to include `external\_message\_id`, sender email, subject, body, and `received\_at`; accept optional external thread and reply-reference IDs.
* Strip HTML, reject blank bodies, retain the full sanitized body, and limit LLM context to the first 8,000 plus final 2,000 characters of oversized messages.
* Link by supplied external thread ID, then reply reference, then normalized sender-plus-subject fallback. Duplicate delivery returns the original message/job rather than creating another record.
* `POST /api/replay` replays only the versioned synthetic scenarios at configurable speed.

## Intelligence, RAG, and Agent

* Layer 1 runs synchronously and deterministically. Blocklist spam terms include crypto giveaway, guaranteed profit, wire transfer, work from home, and click-here scams; configured sender-domain denylist supplements this. Internal `@demo-company.example` messages go to the internal queue.
* Raise urgency from explicit rules: ransomware, data breach, leaked credentials, unauthorized access, and extortion are Critical security; DSAR, GDPR, cease-and-desist, lawsuit, public-review threat, press, and investor inquiry are High; refund, billing, misinformation, outage, and cancellation requests are Medium unless a stronger signal appears.
* Layer 2 uses Gemini function calling for the agent and schema-validated structured output for classification. Categories are `security`, `legal\_compliance`, `reputation`, `billing\_refund`, `product\_support`, `sales\_pricing`, and `general\_inquiry`; urgency is `low`, `medium`, `high`, or `critical`.
* Apply the fixed most-severe/actionable precedence: security, legal/compliance, reputation, billing/refund, product support, sales/pricing, general inquiry. Keep `sentiment\_score` continuous from `-1.0` to `1.0`; classifications below `0.70` confidence require human review.
* Layer 3 queries classifications on demand. Three chronological scores below `-0.35` create an at-risk alert; no rollup table is created.
* Author and version six Markdown policies: pricing tiers and discounts; SLA and credits; refunds and retention offers; API limits and deprecations; GDPR/HIPAA/SOC 2/data residency; and an escalation ownership matrix.
* Chunk policies at 400 tokens with 50-token overlap, embed locally with `all-MiniLM-L6-v2`, retrieve the top three chunks, record every retrieval, and require every generated draft to cite its policy document and chunk IDs.

|Tool|Exact input|Exact output|MVP|
|-|-|-|-|
|`search\_knowledge\_base`|`{query, max\_results: 1..3}`|`{chunks:\[{chunk\_id, document\_id, title, excerpt, score}]}`|Yes|
|`get\_thread\_history`|`{sender\_email, limit: 1..50}`|`{threads:\[{thread\_id, messages:\[{message\_id, received\_at, subject, body\_excerpt, classification}]}]}`|Yes|
|`get\_contact\_profile`|`{email}`|`{contact\_id, account\_id, status, account\_value, churn\_risk\_score, open\_thread\_count}`|Contract only|
|`check\_account\_status`|`{email}`|`{account\_id, plan, billing\_status, overdue\_invoices, renewal\_date}`|Contract only|
|`draft\_reply`|`{message\_id, tone, policy\_refs:\[chunk\_id]}`|`{draft\_id, body, citations:\[{document\_id, chunk\_id}], requires\_approval:true}`|Yes|
|`escalate\_to\_human`|`{message\_id, reason, priority, queue}`|`{escalation\_id, queue, priority, status:"open", brief}`|Yes|
|`create\_internal\_ticket`|`{source\_message\_id, title, body, assignee\_queue}`|`{ticket\_id, assignee\_queue, status:"open"}`|Yes|
|`flag\_for\_legal`|`{message\_id, issue\_type, summary}`|`{legal\_flag\_id, issue\_type, status:"open", queue:"legal\_compliance"}`|Yes|

* Wrap every tool result in `{ok, tool\_name, data, error?}`. Disabled contract-only tools return `tool\_not\_enabled`; they are not exposed to Gemini in MVP.
* Use a custom ReAct loop with at most four tool calls. Persist concise, auditable rationale/action/observation entries rather than private model reasoning.
* In dry-run mode, persist only the run and proposed plan; create no ticket, escalation, legal flag, draft, or simulated outbound message.
* Route Critical security incidents directly to `security`, DSAR/legal threats to `legal\_compliance`, reputation crises to `reputation\_retention`, and routine billing/product issues to `support\_operations`. Critical always escalates and never invokes `draft\_reply`.

## Web, Frontend, Testing, and Delivery

* Run web enrichment asynchronously when a review/public-post term appears, sentiment is at most `-0.60`, a High complaint is detected, or press/investor language appears.
* Configure two allowlisted targets: one review-source URL and one competitor-pricing URL. Fetch only after robots.txt approval, cache results for six hours, and return `{rating, review\_count, complaint\_themes, pricing\_snapshot, fetched\_at}` when available. A denial, timeout, or parser failure is recorded and never blocks triage.
* Build three pages: Mission Control Inbox with filters, tabs, queue badges, and polling; Thread Workspace with timeline, profile, classification, RAG, agent-trace, draft approval, and web-intel panels; Analytics with sentiment, category, response-time, at-risk, and agent-performance charts.
* Version five synthetic fixtures and assert their outcomes end-to-end: DSAR creates legal flag plus compliance ticket and a supervised acknowledgement; ransomware is Critical and security-escalated with no draft/send; misinformation retrieves policy and creates an empathetic supervised draft plus escalation; reputation crisis queues web enrichment and retention escalation; conflicting signals use full thread history and the agreed pricing tier.
* Add unit tests for validation, deduplication, thread linking, pre-filter precedence, sentiment deterioration, RAG citations, tool contracts, and the Critical no-reply invariant. Add integration tests for migrations, pgvector search, role enforcement, dry-run non-mutation, caching degradation, and all five API-driven scenarios.
* Phase 0: Compose startup, migrations, seeded roles, fixtures, Gemini adapter smoke test, and cost/data-handling guard. Phase 1: ingestion, heuristics, classification, RAG, and performance targets. Phase 2: six enabled tools, supervised agent loop, traces, and five scenario tests. Phase 3: web enrichment, dashboard, benchmark evidence, architecture/ER/OpenAPI/README, and recorded walkthrough.
* Make local Docker Compose the required deployment and demo target. Keep cloud hosting as a post-MVP option; local embeddings and all persistent state remain inside the Compose stack. Retain the half-day local quantized-model benchmark as a non-blocking experiment.

