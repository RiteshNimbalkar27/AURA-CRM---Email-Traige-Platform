# AURA Specification Sheet

## 1. Document Control

| Field | Value |
|---|---|
| Product | AURA - Agentic CRM Intelligence Platform |
| Specification type | MVP product and technical requirements document |
| Intended readers | Four-person build team, course evaluators, and project stakeholders |
| Delivery model | Single-tenant local Docker Compose deployment |
| Information classification | Synthetic demo data only |
| Status | Implementation-ready except for the decision gates in Section 17 |
| Source authority | `PLAN.md` is the current decision record; `AURA_Project_Overview.md` provides product framing; `CRM_reviewed1.docx` and `brainstorm.md` are historical context where they conflict with the plan. |

## 2. Product Definition

AURA is a supervised, RAG-grounded email operations and triage system for B2B support and sales inboxes. It ingests synthetic email events, groups them into threads, classifies risk and intent, retrieves relevant internal policies, and proposes auditable actions. The system can create drafts, internal tickets, escalations, and legal flags. An Operator must approve every simulated outbound reply; Critical items never produce or send a customer reply.

The MVP exists to demonstrate production-oriented AI engineering patterns, not to process live customer communications. Persistent data, embeddings, and the application stack run locally. Gemini free-tier inference is restricted to synthetic data because the plan explicitly excludes real customer or personally identifiable information.

## 3. Goals and Non-Goals

### Goals

- Ingest, validate, deduplicate, and thread synthetic inbound email events.
- Apply deterministic safety rules before LLM processing.
- Produce structured classifications with policy-grounded proposed actions.
- Use a bounded, auditable tool-using agent with dry-run support.
- Surface triage, investigation, and analytics workflows in a three-page React dashboard.
- Prove the system with five automated synthetic scenarios and documented performance evidence.

### Non-Goals

- Live mailbox integration, actual outbound email delivery, multi-tenancy, cloud hosting, or production handling of customer/PII data.
- Autonomous customer communication; “send” means a simulated, Operator-approved state transition only.
- Contract-only CRM/billing lookups in the MVP.
- A self-hosted primary LLM; the local quantized-model test is a non-blocking experiment.

## 4. Roles and Permissions

| Capability | Operator | Supervisor |
|---|---:|---:|
| View inboxes, threads, classifications, RAG evidence, and audit history | Yes | Yes |
| Run triage and dry runs | Yes | Yes |
| Edit a draft and approve a simulated send | Yes | Yes |
| View tickets, escalations, and legal flags | Yes | Yes |
| Resolve High/Critical escalations and legal/security records | No | Yes |

Seed one account for each role. Authentication is session-based at the API boundary; credential bootstrap, password rules, session expiry, and CSRF posture remain decision gates because the sources do not specify them.

## 5. Functional Requirements

### 5.1 Ingestion and Threading

`POST /api/ingest` accepts a payload containing `external_message_id`, sender email, subject, body, and `received_at`; `external_thread_id` and reply-reference IDs are optional. The service must:

1. validate the schema, normalize the sender address, strip HTML, and reject blank/whitespace-only bodies;
2. retain the sanitized body, but pass only the first 8,000 plus final 2,000 characters of an oversized body to the LLM;
3. enforce uniqueness of `external_message_id` and return the original message/job for a duplicate delivery;
4. link a message by external thread ID, then reply reference, then normalized sender-plus-subject fallback;
5. tolerate out-of-order `received_at` timestamps and render thread history chronologically;
6. create a job record that can be read at `GET /api/jobs/{job_id}`.

`POST /api/replay` replays only versioned synthetic scenarios at configurable speed. It must never replay arbitrary production-like mailbox data.

### 5.2 Intelligence Pipeline

**Layer 1: deterministic pre-filter.** Runs synchronously on ingest. Blocklisted phrases include `crypto giveaway`, `guaranteed profit`, `wire transfer`, `work from home`, and click-through scams; a configured sender-domain denylist supplements them. Internal `@demo-company.example` traffic routes to the internal queue. The pre-filter assigns an initial queue and risk flags.

**Urgency rules.** Ransomware, data breach, leaked credentials, unauthorized access, and extortion are Critical security. DSAR, GDPR, cease-and-desist, lawsuit, public-review threat, press, and investor inquiry are High. Refund, billing, misinformation, outage, and cancellation are Medium unless a higher-severity signal applies.

**Layer 2: LLM classification.** Non-spam, non-internal traffic uses Gemini function calling and schema-validated output. The classification must include category, urgency, continuous `sentiment_score` in `[-1.0, 1.0]`, confidence, human-review status, relevant entities, and the proposed rationale/action. Supported categories are `security`, `legal_compliance`, `reputation`, `billing_refund`, `product_support`, `sales_pricing`, and `general_inquiry`.

For mixed signals, use this fixed most-severe/actionable precedence: security, legal/compliance, reputation, billing/refund, product support, sales/pricing, general inquiry. Confidence below `0.70` requires human review.

**Layer 3: sentiment trend.** On demand, query chronological classifications. Three consecutive scores below `-0.35` create an at-risk alert. Do not add a rollup table unless performance benchmarking later demonstrates a need.

### 5.3 Knowledge Base and RAG

Author, version, seed, and index these six Markdown policies:

| Document | Required content |
|---|---|
| Pricing tiers and discounts | Plans, discounts, and exceptions |
| SLA and credits | SLA commitments, credits, incident communication |
| Refunds and retention offers | Eligibility, exceptions, credits/refunds, retention playbook |
| API limits and deprecations | Rate limits, breaking changes, deprecation policy |
| GDPR HIPAA SOC 2 data residency | Compliance posture and request process |
| Escalation ownership matrix | Security, legal, PR/reputation, and operations ownership |

Chunk each document at 400 tokens with 50-token overlap. Generate 384-dimensional embeddings locally with `all-MiniLM-L6-v2`; use pgvector cosine similarity and retrieve the top three chunks. Record every retrieval. Every generated draft must cite its policy document and chunk IDs; drafts without citations cannot be approved.

### 5.4 Agent and Actions

Use a custom ReAct-style loop, capped at four tool calls. Store concise rationale, action, and observation entries, not private model chain-of-thought. All tool responses use `{ok, tool_name, data, error?}`.

| Tool | MVP status | Required behavior |
|---|---|---|
| `search_knowledge_base` | Enabled | Returns 1-3 cited chunks for a query. |
| `get_thread_history` | Enabled | Returns up to 50 chronologically ordered thread messages for a sender. |
| `get_contact_profile` | Contract only | Returns `tool_not_enabled`; not exposed to Gemini. |
| `check_account_status` | Contract only | Returns `tool_not_enabled`; not exposed to Gemini. |
| `draft_reply` | Enabled | Creates an approval-required draft with policy citations. |
| `escalate_to_human` | Enabled | Creates an open escalation with queue, priority, and brief. |
| `create_internal_ticket` | Enabled | Creates an open internal ticket. |
| `flag_for_legal` | Enabled | Creates an open legal/compliance flag. |

In dry-run mode, persist only the agent run and proposed plan. It must not create any draft, ticket, escalation, legal flag, or simulated outbound message.

Critical security must route directly to `security`, always escalate, and never invoke `draft_reply`. DSAR and legal threats route to `legal_compliance`; reputation crises route to `reputation_retention`; routine billing/product issues route to `support_operations`.

### 5.5 Web Intelligence

Run enrichment asynchronously when an email references reviews/public posting, has sentiment at or below `-0.60`, is a High complaint, or contains press/investor language. Configure exactly two allowlisted targets for the MVP: one review-source URL and one competitor-pricing URL. Check `robots.txt` before each fetch; cache a successful or failed outcome for six hours; never block triage on denial, timeout, or parsing failure. Return available `rating`, `review_count`, `complaint_themes`, `pricing_snapshot`, and `fetched_at` fields.

### 5.6 User Interface

| Page | Required capabilities |
|---|---|
| Mission Control Inbox | Filterable queues; tabs; category/sentiment/urgency badges; queue counts; polling; thread grouping. Use `Approved simulated sends`, not `Auto-Replied`, as a tab/metric label. |
| Thread Workspace | Chronological timeline; profile; classification; retrieved RAG evidence; agent trace; editable draft; approval control; escalation/legal/ticket state; web-intelligence panel. |
| Analytics | Sentiment, category, response-time, at-risk, and agent-performance charts; date and relevant entity filters. |

## 6. Data Model

Use PostgreSQL with pgvector. Store timestamps in UTC. IDs, audit actor fields, and foreign keys are implementation-defined, but these entities are required.

| Entity | Core requirements |
|---|---|
| `users` | Seeded Operator/Supervisor identities and role. |
| `accounts` | CRM account record; separate from contacts. |
| `contacts` | Normalized email, account relationship, operational status. |
| `threads` | External thread/reply identifiers, subject normalization, queue/status timestamps. |
| `messages` | Unique `external_message_id`, sanitized body, received time, thread/contact references. |
| `classifications` | Append-only per-model-run history, category, urgency, sentiment, confidence, entities, review status; index `(contact_id, received_at)`. |
| `kb_documents` | Versioned source policy metadata and content. |
| `kb_chunks` | Document reference, token range/content, 384-dimension embedding, cosine-search index. |
| `rag_retrievals` | Agent/classification run, chunk, rank, score, and timestamp. |
| `agent_runs` | Trigger, mode, classification reference, redacted JSONB rationale/action/observation trace, outcome. |
| `tickets` | Source message, queue/assignee, title/body, status. |
| `escalations` | Source message, queue, priority, brief, status/resolution metadata. |
| `legal_flags` | Source message, issue type, summary, legal status/resolution metadata. |
| `market_intel_cache` | Target, normalized response/failure state, fetched and expiry time. |
| `audit_log` | Immutable actor/action/entity/time/redacted change metadata. |

Required constraints/indexes: unique `messages.external_message_id`; thread retrieval index; classification sentiment query index; pgvector cosine-search index; foreign keys for referential integrity; append-only classification and audit semantics.

## 7. API Contract

All failures use `{ "error_code": string, "message": string, "details": object | array | null }`. JSON success payload shapes must be documented in the generated OpenAPI specification. List endpoints require explicit pagination, sort, and filter parameters in OpenAPI; exact defaults are a decision gate.

| Area | Endpoints |
|---|---|
| Authentication | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Ingestion | `POST /api/ingest`, `POST /api/replay`, `GET /api/jobs/{job_id}` |
| Inbox/thread | `GET /api/dashboard/stats`, `GET /api/threads`, `GET /api/threads/{thread_id}`, `GET /api/messages/{message_id}` |
| Agent/actions | `POST /api/messages/{id}/agent-runs`, `GET /api/agent-runs/{id}`, `PATCH /api/drafts/{id}`, `POST /api/drafts/{id}/approve`, `GET /api/tickets`, `GET /api/escalations`, `GET /api/legal-flags` |
| CRM/analytics | `GET /api/contacts/{email}`, `PATCH /api/contacts/{email}/status`, `GET /api/analytics/sentiment-trend`, `GET /api/analytics/category-breakdown`, `GET /api/analytics/at-risk-accounts` |
| RAG/web/audit | `GET /api/rag/search`, `GET /api/market-intelligence`, `GET /api/audit/{entity_type}/{entity_id}`, `GET /health` |

`POST /api/drafts/{id}/approve` performs a simulated send only and must write an audit event. It must reject a Critical-linked draft as an invariant violation.

## 8. Architecture and Deployment

The required demo deployment is Docker Compose with FastAPI, React, PostgreSQL plus pgvector, an asynchronous worker/scheduler, and local embedding runtime. Gemini is an external inference dependency used only with synthetic inputs. The repository must contain an architecture diagram covering ingestion, heuristics, LLM/RAG, agent/tools, database, async enrichment, and UI.

Cloud deployment is post-MVP. The local quantized-model benchmark is timeboxed to half a day and cannot block Phase 0 or Phase 1.

## 9. Security and Data Handling Requirements

- Reject live customer, secret, and PII-bearing input from the demo workflow; fixtures must be synthetic.
- Redact sensitive values from stored agent rationale/action/observation traces and audit metadata.
- Enforce role checks server-side, not only in the UI.
- Allowlist enrichment targets; honour robots controls; record enrichment failure without surfacing untrusted raw data as a decision.
- Keep secrets outside source control and document required environment variables in the README.
- Treat all LLM output, web content, and inbound email as untrusted: validate schemas, encode rendered content, and prohibit tool execution outside the defined contracts.

## 10. Quality Attributes and Performance

| Requirement | Acceptance target |
|---|---|
| Pre-filter | Synchronous and single-digit milliseconds under the project benchmark setup. |
| Thread read | Up to 50 messages in under 100 ms. |
| Sentiment trend | Indexed 30-day query with recorded query plan/benchmark evidence. |
| Vector search | Top three chunks in under 200 ms. |
| Resilience | Duplicate delivery is idempotent; web failures do not block triage. |
| Auditability | Every agent run, retrieval, approval, and action has an auditable record. |

## 11. Acceptance Scenarios

| Scenario | Required outcome |
|---|---|
| DSAR | Legal flag plus compliance ticket and an approval-required holding acknowledgement that cites compliance policy. |
| Ransomware/extortion | Critical security escalation; no draft and no simulated send. |
| Own-product misinformation | Policy retrieval, empathetic cited draft, and escalation with discrepancy summary. |
| Reputation crisis | Async web-enrichment request, retention escalation, and policy-grounded retention suggestion. |
| Conflicting thread signals | Full history informs the correct previously agreed pricing tier for a later billing question. |

## 12. Required Test Coverage

Unit tests: payload validation, HTML/blank-body handling, deduplication, thread linking, pre-filter precedence, confidence review threshold, sentiment deterioration, RAG citations, tool contracts, and the Critical no-reply invariant.

Integration tests: migrations, pgvector search, role enforcement, dry-run non-mutation, web-cache degradation, approval audit record, and the five API-driven acceptance scenarios. Include benchmark evidence for the Section 10 targets.

## 13. Deliverables

- Git repository with atomic, reviewable history.
- README: setup, configuration, synthetic-data guard, KB seeding, architecture trade-offs, and demo steps.
- Docker Compose configuration, migrations, seeded roles, versioned fixtures, six KB documents, and OpenAPI specification.
- Architecture diagram and ER diagram/schema.
- Automated test suite and benchmark evidence.
- Recorded walkthrough showing ingestion, agent trace, RAG debug view, reputation crisis, and analytics dashboard.

## 14. Delivery Plan and Completion Criteria

| Phase | Scope | Exit criterion |
|---|---|---|
| 0 | Compose, migrations, roles, fixtures, Gemini adapter smoke test, synthetic-data guard | Stack starts locally and safely processes a smoke fixture. |
| 1 | Ingestion, heuristics, classification, RAG, performance baseline | A fixture is safely ingested, classified, cited, and retrievable. |
| 2 | Six enabled tools, agent loop, traces, scenario tests | All five scenarios pass and dry run mutates no action records. |
| 3 | Web enrichment, dashboard, benchmarks, diagrams/OpenAPI/README, walkthrough | Deliverables are complete and demo evidence is reproducible. |

The specification is complete when every required endpoint and entity is represented in OpenAPI/schema/migrations, all acceptance scenarios and invariants pass, the performance evidence is recorded, and the documentation/demo deliverables are present.

## 15. Product Evolution Roadmap

This roadmap is a proposed sequence, not a commitment to build every item. Work moves to the next version only after the previous version has met its exit criteria. Product direction, user feedback, budget, and privacy/legal requirements may change the ordering.

### MVP - Demonstrable Core System

The current specification defines the MVP: local Compose deployment, synthetic email fixtures, deterministic triage, Gemini-based structured classification, local RAG over six policies, six enabled agent tools, supervised simulated drafts, the three dashboard views, web enrichment, and five automated acceptance scenarios.

**Exit criterion:** Every Section 11 scenario passes; Critical items cannot produce a draft or simulated send; the required documentation, diagrams, OpenAPI, benchmark evidence, and walkthrough are complete.

### V1 - MVP Hardening and Usability

V1 improves the working MVP without changing its core product boundary.

| Area | Proposed improvement |
|---|---|
| Reliability | Retry/backoff and dead-letter handling for asynchronous jobs; clearer job progress and recoverable error states. |
| Quality | Regression test corpus, prompt/version evaluation, retrieval-quality review, and a feedback mechanism for corrected classifications/drafts. |
| Operations | Structured logs, health/readiness checks, basic metrics, backup/restore runbook, and configurable retention for synthetic data. |
| UX | Low-fidelity-to-polished workflows for filtering, bulk triage, draft review, escalation resolution, loading/empty/error states, and responsive accessibility. |
| Policy governance | In-app policy version visibility and a safe re-index workflow with retrieval provenance. |
| Security | Finalized session lifecycle, password/seed-account handling, rate limiting, audit-log access controls, and secret-management guidance. |

**Exit criterion:** The MVP is stable for repeated demonstrations, an Operator can complete core workflows without developer assistance, and test/observability evidence makes failures diagnosable.

### V2 - Integrated Team Workflow

V2 adds controlled integrations and collaboration features after synthetic-only safeguards, security posture, and operational ownership have been approved.

| Area | Proposed feature |
|---|---|
| Inbound channels | One approved mailbox/help-desk connector with OAuth, sandbox mode, consent/data classification, and a replayable event adapter. |
| CRM and billing | Enable `get_contact_profile` and `check_account_status` behind an approved CRM/billing integration; retain the existing tool contracts. |
| Collaboration | Assignment, ownership, internal notes, escalation SLAs, notifications, and Supervisor resolution workflows. |
| Communication | Template-based outbound replies with approval queues, delivery status, and durable audit records; keep Critical no-send safeguards. |
| Analytics | Queue/team performance, policy coverage, correction trends, SLA reporting, and exportable reports. |
| Deployment | Staging environment, configuration separation, CI/CD, database migration discipline, and a production-readiness review. |

**Exit criterion:** An approved team can operate the system through a real integration in a controlled pilot, with clear ownership, auditability, rollback, and no unapproved autonomous sending.

### V3 - Production-Ready Platform

V3 addresses scale, governance, and enterprise readiness. It should begin only after a privacy, security, legal, and product review authorizes processing of non-synthetic data.

| Area | Proposed feature |
|---|---|
| Data protection | PII discovery/minimization, tenant isolation, encryption/key management, retention/deletion workflows, DSAR operations, and vendor/data-processing review. |
| Identity and access | SSO, MFA, granular roles/permissions, account lifecycle management, and audit export. |
| Scale and resilience | Queue-based worker scaling, rate limiting, load testing, disaster recovery, backups, alerting, and service-level objectives. |
| Intelligence governance | Model/provider abstraction, evaluation gates before prompt/model changes, human-feedback loops, safety monitoring, and explainable decision evidence. |
| Multi-tenancy | Tenant boundaries, per-tenant policies/knowledge bases, quotas, billing boundaries, and cross-tenant isolation tests. |
| Enterprise integrations | Additional email/help-desk/CRM connectors, webhook/event APIs, and SIEM/alerting integrations. |

**Exit criterion:** The platform passes a formal production readiness review against the organization’s security, privacy, reliability, and support requirements.

### Future Nice-to-Haves

- WebSocket or server-sent real-time updates after polling has proven insufficient.
- Multilingual classification, retrieval, and draft review.
- Attachment parsing and malware-scanning integration, subject to a dedicated security design.
- Configurable workflow builder for routing and escalation policies.
- Quality dashboard for retrieval precision, citation coverage, and human override rate.
- Additional public-intelligence sources such as social listening or company news, with compliance review.
- A bounded, benchmarked local-LLM fallback for synthetic/offline demos.
- Mobile-optimized supervisor review experience.

### Explicitly Not in Scope Now

Do not build the following during MVP delivery unless scope, resourcing, and approvals are formally changed:

- Live customer mailbox ingestion, live PII/customer data processing, or unapproved third-party data sharing.
- Fully autonomous outbound email, especially for High/Critical cases.
- Multi-tenant SaaS billing, self-service tenant onboarding, or enterprise-grade SSO.
- Native mobile applications.
- Broad web scraping, social monitoring, or scraping targets beyond the two approved allowlisted URLs.
- Complex attachment/OCR/malware pipeline, voice/chat channels, or omnichannel contact-center replacement.
- Self-hosted primary LLM infrastructure, fine-tuning, or training custom foundation models.
- Global high-availability, multi-region deployment, or formal compliance certification.

## 16. Review Findings and Decisions

1. **LLM provider resolved:** `PLAN.md` supersedes earlier OpenAI/Claude references. Gemini is the MVP inference provider and synthetic data is mandatory.
2. **Data model resolved:** the normalized entities in Section 6 supersede the Word draft’s legacy `emails` and `actions` tables; classification history remains append-only.
3. **Send terminology resolved:** no auto-reply is allowed. Dashboard labels, API descriptions, fixtures, and tests must use `approval-required draft` and `approved simulated send`.
4. **Tool scope resolved:** six tools are enabled; contact-profile and account-status tools are defined only as disabled contracts.
5. **Critical safety resolved:** Critical security has a direct escalation path and cannot produce a draft or simulated send.

## 17. Decision Gates and Open Items

The following information is not in the provided sources and must be explicitly chosen before implementation. No implementation should silently invent it.

| Decision needed | Why it matters | Owner / deadline |
|---|---|---|
| Exact final submission format beyond this Markdown specification | Determines whether a separate PRD, design doc, or OpenAPI artifact needs packaging. | Project lead, before Phase 0 close |
| Auth bootstrap, password policy, session duration, and CSRF approach | Required to make the seeded-role claim testable. | Backend owner, Phase 0 |
| Gemini model/version, API rate limits, retry/backoff, and spend/quota guard | Controls deterministic tests, reliability, and no-budget operation. | AI owner, Phase 0 |
| Synthetic company identity and concrete policy values | Required to author the six KB documents and assert citations. | Product/KB owner, Phase 0 |
| Exact allowlisted review and competitor URLs | Required for compliant web enrichment and fixture assertions. | Web owner, before Phase 3 |
| API pagination/filter defaults and retention/deletion policy | Needed to finalize OpenAPI, indexes, and audit behavior. | Backend owner, Phase 1 |
| Queue ownership/assignee identities and escalation SLAs | Needed to make the escalation matrix operational rather than descriptive. | Product lead, Phase 1 |
| Benchmark dataset size, host profile, and measurement method | Needed for credible performance evidence. | QA owner, Phase 1 |

## 18. Immediate Next Steps

1. Resolve all Phase 0 decision gates and record the values in the README/environment example and the escalation policy.
2. Create the repository structure, Compose stack, migrations, seeded roles, synthetic fixtures, and a failing test for the Critical no-draft/no-send invariant.
3. Author/version the six KB policies before implementing retrieval or agent drafting.
4. Generate OpenAPI from FastAPI and validate every endpoint in Section 7 against scenario-driven tests.
5. Do not enable live email ingestion or non-synthetic inference until the project scope is formally changed.
