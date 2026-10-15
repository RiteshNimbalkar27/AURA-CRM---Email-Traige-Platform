# AURA — Progress Log

Updated after each work session. Most recent entry at the top.

---

## Session 5 — 2026-10-15

**Agent:** Antigravity (Claude Sonnet 4.6 Thinking)

### Completed

- [x] **Phase 3: Web Enrichment Service (`backend/app/services/web_enrichment.py`)**:
  - `get_or_fetch_market_intel(db, url)` async entry point
  - 6-hour TTL cache backed by `market_intel_cache` DB table
  - Robots.txt checked via `urllib.robotparser` before every fresh fetch
  - Only fetches URLs from settings (`ENRICHMENT_REVIEW_URL`, `ENRICHMENT_COMPETITOR_URL`)
  - Stale fallback: returns last cached row with `stale=True` on fresh-fetch failure
  - Status tracking: `success | failed | robots_denied | timeout`
  - Returns `{url, fetched_at, summary, raw_text, status, stale, error}` envelope

- [x] **Phase 3: CRM & Analytics API (`backend/app/api/crm_api.py`)**:
  - `GET /api/contacts/{email}` — contact profile + account + last 5 classifications
  - `PATCH /api/contacts/{email}/status` — supervisor-only status update
  - `GET /api/analytics/sentiment-trend` — daily avg sentiment (last N days, optional contact filter)
  - `GET /api/analytics/category-breakdown` — count per category last N days
  - `GET /api/analytics/at-risk-accounts` — accounts with at_risk contacts + last sentiment
  - `GET /api/market-intelligence` — web enrichment trigger (`?url=review|competitor`)
  - `GET /api/audit/{entity_type}/{entity_id}` — audit lookup for agent_run/draft/ticket/escalation/legal_flag

- [x] **Phase 3: `backend/app/main.py` Updated**:
  - CRM router registered under `/api` with `["CRM & Analytics"]` tag
  - CORS expanded to include Vite dev server ports (`localhost:5173`, `127.0.0.1:5173`)

- [x] **Phase 3: React Dashboard Frontend (`frontend/src/`)**:
  - `src/api/client.ts` — Typed Axios client with JWT Bearer interceptor + all API functions
  - `src/hooks/useAuth.ts` — JWT auth hook (localStorage `aura_token`, login/logout, expiry check)
  - `src/components/Layout.tsx` — Dark slate sidebar (240px, AURA logo, nav links, user/logout)
  - `src/components/ProtectedRoute.tsx` — Auth guard with redirect to /login
  - `src/pages/Login.tsx` — Login page with AURA branding, error state, loading spinner
  - `src/pages/MissionControl.tsx` — Inbox: stat cards, filter bar, paginated threads with urgency badges
  - `src/pages/ThreadWorkspace.tsx` — 60/40 split: message timeline + agent action panel (run/approve/edit)
  - `src/pages/Analytics.tsx` — Recharts: sentiment LineChart, category BarChart, at-risk accounts table
  - `src/App.tsx` — Updated: /login public + protected routes wrapped in Layout

- [x] **Production UI Redesign (In-House Professional Theme)**:
  - Eliminated AI aesthetic tropes: removed gradients, hero cards, rainbow badges, emojis, and soft shadows.
  - Tighter border-based layout with compact header metric bars, flat tables, and monospace draft/trace inspector.
  - Hardened all charts and tables against sparse data with unified slate palette.

- [x] **Bug Fixes & End-to-End ReAct Agent Loop Verification**:
  - Fixed React fatal white-screen crash in `AgentRunPanel`: `step.observation` dictionary is now stringified safely.
  - Fixed Analytics white screen: array wrappers safely extract data envelopes (`trend`, `breakdown`, `at_risk_accounts`).
  - Fixed `run_agent` argument mapping in `backend/app/api/agent_api.py`.
  - Fixed tool registry binding in `backend/app/agent/react_loop.py` to correctly map LLM arguments to tool factories.
  - Increased ReAct loop `max_tokens` to 2048 to prevent truncated reasoning finish reasons.
  - Verified live test: `run_agent` ran in dry-run mode against database message, executed `escalate_to_human`, and succeeded with status `dry_run`.

### Next Phases: Dual-Agent Critic & Active Learning Flywheel (Phases 3A – 3D)

Brainstormed and aligned via `/grill-me` interview. Ready for direct execution:

- [ ] **Phase 3A: Database & Backend Critic / Auditor**:
  - Create `golden_examples` table schema + Alembic migration (`id`, `source_message_id`, `category`, `original_draft`, `edited_draft`, `semantic_diff`, `correction_tag`, `embedding` vector(384), `verified_by`, `is_active`, `created_at`)
  - Create `app/agent/critic.py` — Adversarial Critic / Judge agent (Grounding Score 0–100%, Hallucination Risk rating, citation verification, PII/tone check)
  - Create `app/api/golden_memory_api.py` — `GET /api/golden-examples`, `POST /api/golden-examples`, and diff capture endpoint
  - Register router in `app/main.py`

- [ ] **Phase 3B: ReAct Generator Memory Integration**:
  - Integrate pgvector similarity search over `golden_examples` inside `react_loop.py` to inject dynamic operator-verified few-shot references
  - Wire Critic agent to run automatically after draft generation, storing structured audit report in `drafts.audit_report` (JSONB)
  - Update `AgentRunResponse` to include the Critic audit card summary

- [ ] **Phase 3C: Frontend Workspace Audit Card & Diff Modal**:
  - Build interactive "Compliance & Grounding Audit" card in `ThreadWorkspace.tsx` showing score, hallucination rating, and citation checklist
  - Enforce soft-lock on approval if Grounding Score < 70% or Hallucination Risk is High (requires operator edit or explicit override checkbox)
  - Build visual text diff modal with 1-click failure taxonomy tagging (`Policy Fix`, `Hallucination`, `Tone Adjustment`, `Missing Context`) when saving draft edits

- [ ] **Phase 3D: Golden Memory Dashboard View (`/golden-memory`)**:
  - Create `/golden-memory` route and add sidebar navigation item
  - Build management dashboard: searchable diff table, category filters, and active/retire toggle switches for Golden Examples

---

### Subsequent Phase: Architecture Docs + Benchmarks (Phase 4)

Will commence immediately following completion of Phases 3A – 3D:
1. OpenAPI spec export and documentation
2. Benchmark evidence: RAG performance targets, classification latency measurements
3. README walkthrough with architecture diagrams and demo guide
4. Docker Compose full-stack deployment validation

---

## Session 4 — 2026-09-25

**Agent:** Antigravity (Claude Sonnet 4.6 Thinking)

### Completed

- [x] **Phase 2: ReAct Agent Loop (`backend/app/agent/react_loop.py`)**:
  - Custom LLM-driven ReAct loop (max 4 tool calls per run)
  - Auditable JSONB trace: `{step, rationale, action, observation}` (no private CoT)
  - Hard safety invariants: `critical` urgency blocks `draft_reply`, never produces outbound
  - Dry-run mode: persists AgentRun + plan, creates ZERO tickets/escalations/drafts/legal_flags
  - `get_tool_registry(db, agent_run_id, message_id, dry_run, urgency)` factory pattern
  - `app/agent/__init__.py` updated to export `run_agent`

- [x] **Phase 2: Agent Tools (`backend/app/agent/tools/`)**:
  - `search_kb.py` — `search_knowledge_base(query, max_results)` with pgvector + retrieval audit
  - `thread_history.py` — `get_thread_history(sender_email, limit)` with JOIN + classification
  - `draft_reply.py` — `draft_reply(message_id, tone, policy_refs)` grounded + citations
  - `escalate.py` — `escalate_to_human(message_id, reason, priority, queue)` Escalation row
  - `ticket.py` — `create_internal_ticket(source_message_id, title, body, assignee_queue)` Ticket row
  - `legal_flag.py` — `flag_for_legal(message_id, issue_type, summary)` LegalFlag row
  - `contract_stubs.py` — `get_contact_profile`, `check_account_status` → `tool_not_enabled`
  - All tools: `{ok, tool_name, data|error}` envelope, dry_run respected, try/except safety

- [x] **Phase 2: Agent Action API Endpoints (`backend/app/api/agent_api.py`)**:
  - `POST /api/messages/{id}/agent-runs` — trigger live or dry-run agent execution (201)
  - `GET /api/agent-runs/{id}` — retrieve run status, trace, outcome
  - `PATCH /api/drafts/{id}` — edit draft body (only if pending_approval)
  - `POST /api/drafts/{id}/approve` — Operator approves; hard block on critical urgency (403)
  - `GET /api/tickets` — paginated, filterable
  - `GET /api/escalations` — paginated, filterable
  - `GET /api/legal-flags` — paginated, filterable
  - `backend/app/main.py` updated to register agent router

- [x] **Phase 2: Scenario Acceptance Tests (`backend/tests/`)**:
  - `conftest.py` — session-scoped app/client/auth fixtures, `ingest_and_wait()`, `run_agent()` helpers
  - `test_scenarios.py` — 6 tests (5 scenarios + 1 dry-run) collected successfully
  - `pytest.ini` — `asyncio_mode = auto`, session-scoped loop
  - Scenario 01 (DSAR): legal_flag + ticket + supervised draft with citations
  - Scenario 02 (Ransomware): critical escalation, ZERO drafts enforced
  - Scenario 03 (Misinformation): RAG-grounded draft + escalation
  - Scenario 04 (Reputation): reputation_retention escalation
  - Scenario 05 (Conflicting Signals): thread history + trace depth assertions
  - Dry-run test: outcome='dry_run', zero DB side effects

- [x] **All 13 Phase 2 files pass AST syntax check and module import verification**

### Ready For Phase 3: Web Enrichment + Dashboard + Benchmarks

Next tasks:
1. Web enrichment async service (review-source + competitor-pricing, robots.txt, 6h cache)
2. React dashboard: Mission Control Inbox, Thread Workspace, Analytics pages
3. Benchmark evidence: RAG performance targets, classification latency
4. Architecture docs: ER diagram, OpenAPI spec, README walkthrough recording

---

## Session 3 — 2026-09-25

**Agent:** Antigravity (Claude Sonnet 4.6 Thinking)

### Completed

- [x] **Fixed Windows ProactorEventLoop blocker:**
  - Switched from `psycopg3` async driver to `asyncpg` (`postgresql+asyncpg://...`)
  - `asyncpg` natively supports Windows ProactorEventLoop without flags or custom loop policies
  - Added `asyncpg==0.31.0` to `requirements.txt`
  - Updated `.env` and `app/config.py` default connection strings
- [x] **Fixed OpenRouter model ID:**
  - `LLM_MODEL=deepseek/deepseek-v4-flash-0731:free` was returning 404 because OpenRouter's model slug is `deepseek/deepseek-v4-flash-0731` (no `:free` suffix)
  - Updated `.env` and `app/config.py` to `deepseek/deepseek-v4-flash-0731`
  - Verified OpenRouter connectivity: `smoke_test()` returned `{'ok': True, 'model': 'deepseek/deepseek-v4-flash-0731'}`
  - Verified end-to-end LLM email classification: successfully classified support email with 0.95 confidence
- [x] **Verified Phase 1 End-to-End Smoke Tests:**
  - `GET /health` → 200 OK
  - `POST /auth/login` → 200 OK (JWT issued)
  - `GET /auth/me` → 200 OK
  - `GET /api/rag/search` → 200 OK (cosine similarity search over 12 pgvector chunks)
  - `POST /api/ingest` (normal) → 202 Accepted, queued with ARQ job ID
  - `POST /api/ingest` (duplicate) → 202 Accepted, duplicate flag returned, no extra record
  - `POST /api/ingest` (critical ransomware) → 202 Accepted, critical pre-filter urgency detected
- [x] **Built Phase 1 Background Worker:**
  - Created `backend/app/worker/tasks.py`: `classify_message_task` running the 2-layer intelligence pipeline (prefilter + LLM), saving `Classification`, updating thread queue, and managing `job_status`
  - Created `backend/app/worker/main.py`: ARQ `WorkerSettings` entrypoint with retry configuration and Redis connection setup
- [x] **Built Phase 1 Mission Control Inbox / Dashboard APIs:**
  - Created `backend/app/api/inbox.py`:
    - `GET /api/dashboard/stats`: summary counts by queue, urgency, review status, unclassified, escalations, legal flags
    - `GET /api/threads`: paginated thread list with filters (queue, status, urgency, human_review) and latest classification metadata
    - `GET /api/threads/{thread_id}`: full thread timeline with messages and classifications
    - `GET /api/messages/{message_id}`: comprehensive message view with classifications, agent runs, drafts, tickets, escalations, legal flags
  - Registered inbox router in `backend/app/main.py`
- [x] **Updated Documentation:**
  - Rewrote `dev.md` with complete step-by-step instructions, worker startup commands, and explanation of Windows quirks / fixes
  - Created `PROJECT_FLOW_AND_ARCHITECTURE.md` documenting end-to-end data pipeline, agent loop, RAG flow, and safety invariants

### Ready For Phase 2: Agent + Tools + Scenario Replay

Next tasks to build:
1. **ReAct Agent Loop (`backend/app/agent/react_loop.py`)**:
   - Max 4 tool calls per run
   - Redacted JSONB audit trail (`step`, `rationale`, `action`, `observation`) without raw CoT
   - Dry-run mode (`mode="dry_run"`) that generates plans without mutating database records
   - Hard safety invariant: Critical urgency never invokes `draft_reply` or produces simulated outbound communications
2. **Agent Tools (`backend/app/agent/tools/`)**:
   - `search_knowledge_base`: cosine search with retrieval audit logging
   - `get_thread_history`: fetches chronological message history for sender
   - `draft_reply`: grounded draft generation citing document and chunk IDs
   - `escalate_to_human`: queues escalation by priority and routing matrix
   - `create_internal_ticket`: internal ticket creation with assignee queue
   - `flag_for_legal`: compliance/legal issue flagging
   - Contract-only stubs: `get_contact_profile`, `check_account_status` (returns `tool_not_enabled`)
3. **Agent Action API Endpoints**:
   - `POST /api/messages/{id}/agent-runs`: trigger live or dry-run agent execution
   - `GET /api/agent-runs/{id}`: retrieve run status and tool call trace
   - `PATCH /api/drafts/{id}`: edit drafted reply
   - `POST /api/drafts/{id}/approve`: Operator approves simulated send (blocks Critical items)
   - `GET /api/tickets`, `GET /api/escalations`, `GET /api/legal-flags`: queues review endpoints
4. **Scenario Acceptance Tests (`backend/tests/test_scenarios.py`)**:
   - Scenario 01: DSAR Compliance (legal flag + ticket + supervised acknowledgement)
   - Scenario 02: Ransomware Incident (Critical security escalation, ZERO draft/send)
   - Scenario 03: Misinformation / Outage (policy RAG + empathetic draft + escalation)
   - Scenario 04: Reputation Crisis (retention escalation + web intel trigger)
   - Scenario 05: Conflicting Signals (thread history analysis + pricing tier adherence)

---

## Session 2 — 2026-09-19

**Agent:** Antigravity (Claude Sonnet 4.6 Thinking)

### Completed

- [x] **Switched LLM from Gemini → DeepSeek V4 Flash 0731 (free) via OpenRouter**
  - Created `backend/app/services/llm_adapter.py` — OpenAI-compatible httpx adapter
  - `gemini_adapter.py` → backward-compat shim (re-exports from llm_adapter)
  - Updated `config.py`: `OPENROUTER_API_KEY`, `LLM_MODEL`, `OPENROUTER_BASE_URL`
  - Updated `requirements.txt`: removed `google-generativeai`, added `openai==1.54.0`
  - Verified: smoke test `ok=True`, model responding correctly
- [x] **Docker dev environment started** — `aura-db` (pgvector/pg16) + `aura-redis` running
- [x] **Fixed Alembic `env.py`** — `get_main_section_name()` → `config_ini_section`
- [x] **Fixed Windows asyncio** — Added `WindowsSelectorEventLoopPolicy` to `alembic/env.py`, `seed.py`, `seed_kb.py`
- [x] **Ran migrations** — `alembic upgrade head` → 001 Initial schema applied
- [x] **Ran seed.py** — Users, accounts, contacts seeded
- [x] **`/health` smoke test** — `{"status":"ok","synthetic_data_only":true}` ✅
- [x] **DeepSeek smoke test** — `{"ok":True, "provider":"openrouter"}` ✅
- [x] **seed_kb.py** — 6 docs × 2 chunks = 12 chunks embedded (384-dim) in pgvector ✅
- [x] **Phase 1 — Intelligence pipeline built:**
  - `app/intelligence/prefilter.py` — Layer 1 deterministic rules (all 5 rule branches verified)
  - `app/intelligence/classifier.py` — Layer 2 LLM wrapper (prefilter → LLM, critical safety invariant enforced)
- [x] **Phase 1 — RAG system built:**
  - `app/rag/embedder.py` — lazy singleton sentence-transformers loader
  - `app/rag/retriever.py` — pgvector cosine search + audit trail recording
  - `app/api/rag_api.py` — `GET /api/rag/search` endpoint
- [x] **Phase 1 — Ingestion API built:**
  - `app/schemas/ingest.py` — `IngestRequest`, `IngestResponse`, `JobStatusResponse`
  - `app/api/ingest.py` — `POST /api/ingest` (dedup, thread linking, ARQ enqueue), `GET /api/jobs/{id}`, `POST /api/replay` stub
- [x] **`main.py` updated** — all 3 routers registered (auth, ingest, rag)

### Open Issue — MUST FIX NEXT SESSION

- [ ] **Windows ProactorEventLoop blocks DB queries in uvicorn**
  - Root cause: uvicorn on Windows creates a `ProactorEventLoop` which psycopg3 async refuses to use
  - Fix: launch uvicorn with `--loop asyncio` flag (forces `SelectorEventLoop`)
  - Command to use: `uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop asyncio`
  - The `WindowsSelectorEventLoopPolicy` in `main.py` doesn't help because uvicorn replaces the loop after import
  - Also update `dev.md` to document this

### Next Session Should Start With

1. **Fix uvicorn startup** — add `--loop asyncio` to the run command
2. **Re-run smoke tests** — login, RAG search, POST /api/ingest (normal + duplicate + critical)
3. **Build Phase 1 background worker** — `app/worker/tasks.py` (ARQ task that calls `classify_message`)
4. **Build remaining Phase 1 API endpoints** — dashboard stats, threads list, thread detail, message detail
5. Then move to **Phase 2: Agent + Tools**

### Windows-Specific Fixes (Applied — Keep In Mind)

- All `asyncio.run()` calls for scripts need `WindowsSelectorEventLoopPolicy` on Windows
- FastAPI/uvicorn itself handles this correctly already
- The `alembic/env.py` fix is permanent

---

## Session 1 — 2026-09-18


**Agent:** Antigravity (Claude Sonnet 4.6 Thinking)

### Completed

- [x] Read all source documents: `SPECIFICATION_SHEET.md`, `PLAN.md`, `AURA_Project_Overview.md`, `brainstorm.md`
- [x] Created `implementation_plan.md` covering all 4 phases
- [x] Resolved all Phase 0 decision gates (see `decisions.md`)
- [x] Created `decisions.md` — all 12 architectural decisions recorded
- [x] Created `progress.md` (this file)
- [x] Created `agent_context.md` — context for future sessions
- [x] **PHASE 0 IN PROGRESS — subagents building:**
  - Infrastructure (docker-compose, requirements.txt, config, main.py)
  - DB models + Alembic migrations (all 15 entities)
  - KB documents (6 policy files) + synthetic fixtures (5 scenarios)
  - Auth system + Gemini adapter + seed scripts

### In Progress

- [/] Phase 0: Full project scaffold being built by parallel subagents

### Next Session Should Start With

1. Verify all Phase 0 files were created correctly
2. Run `docker compose -f docker-compose.dev.yml up -d` to confirm DB + Redis start
3. Create venv: `cd backend && python -m venv .venv`
4. Install deps: `pip install -r requirements.txt`
5. Run migrations: `alembic upgrade head`
6. Run seed: `python scripts/seed.py`
7. Run smoke test: `GET /health` and Gemini adapter smoke test
8. Then proceed to Phase 1: Ingestion + Intelligence + RAG

---

## Phase Completion Summary

| Phase | Status | Exit Criterion Met? |
|---|---|---|
| 0 — Foundation | ✅ Complete | Yes — DB, migrations, seeds, Docker, LLM adapter verified |
| 1 — Ingestion + Intelligence + RAG | ✅ Complete | Yes — Pipeline, RAG, Ingestion, Inbox APIs, and ARQ worker built & verified |
| 2 — Agent + Tools + Scenarios | ✅ Complete | Yes — ReAct loop, 6 tools, 7 API endpoints, 6 scenario tests all verified |
| 3 — Core Web Enrichment & In-House Dashboard | ✅ Complete | Yes — Web enrichment service (6h cache, robots.txt), 7 CRM/analytics API endpoints, production-styled React dashboard (Login, Mission Control, Thread Workspace, Analytics) — verified |
| 3A — Database & Backend Critic / Auditor | ⬜ Not Started | Spec ready — golden_examples schema, app/agent/critic.py, API endpoints |
| 3B — ReAct Generator Memory Integration | ⬜ Not Started | Spec ready — pgvector few-shot retrieval in react_loop.py, audit report persistence |
| 3C — Frontend Workspace Audit Card & Diff Modal | ⬜ Not Started | Spec ready — Compliance & Grounding Audit card, soft-block, visual text diff modal |
| 3D — Golden Memory Dashboard View | ⬜ Not Started | Spec ready — /golden-memory route, searchable diff table, active/retire toggles |
| 4 — Architecture Docs + Benchmarks | ⬜ Not Started | Scheduled after Phase 3A-3D completion |

---

## Known Issues / Blockers

- None currently. All decision gates resolved.

## Files Created This Session

- `d:\Code\EDAI Email\decisions.md`
- `d:\Code\EDAI Email\progress.md`
- `d:\Code\EDAI Email\agent_context.md`
- `d:\Code\EDAI Email\docker-compose.yml`
- `d:\Code\EDAI Email\docker-compose.dev.yml`
- `d:\Code\EDAI Email\.env.example`
- `d:\Code\EDAI Email\backend\requirements.txt`
- `d:\Code\EDAI Email\backend\Dockerfile`
- `d:\Code\EDAI Email\backend\app\config.py`
- `d:\Code\EDAI Email\backend\app\database.py`
- `d:\Code\EDAI Email\backend\app\main.py`
- `d:\Code\EDAI Email\backend\app\models\` (all model files)
- `d:\Code\EDAI Email\backend\alembic\` (migrations)
- `d:\Code\EDAI Email\backend\kb_documents\` (6 policy docs)
- `d:\Code\EDAI Email\backend\fixtures\` (5 scenario JSONs)
- `d:\Code\EDAI Email\backend\app\core\security.py`
- `d:\Code\EDAI Email\backend\app\api\auth.py`
- `d:\Code\EDAI Email\backend\app\services\gemini_adapter.py`
- `d:\Code\EDAI Email\backend\scripts\seed.py`
- `d:\Code\EDAI Email\dev.md`
- `d:\Code\EDAI Email\README.md`
