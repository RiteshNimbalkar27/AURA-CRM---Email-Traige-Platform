# AURA — Progress Log

Updated after each work session. Most recent entry at the top.

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
| 2 — Agent + Tools + Scenarios | ⬜ Not Started | — |
| 3 — Web Enrichment + Dashboard + Benchmarks | ⬜ Not Started | — |

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
