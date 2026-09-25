# AURA — Agent Context

**Purpose:** This file gives any AI agent (or developer) the essential context needed to continue
work on AURA without re-reading all source documents from scratch. Read this file first.

---

## What Is AURA?

AURA (Agentic CRM Intelligence Platform) is a supervised, RAG-grounded email triage system for
B2B support/sales inboxes. It is built as a local demo using synthetic data only.

**Fictional company:** Nexus Software Inc. (B2B SaaS, project management + team collaboration)

**Key constraints that must NEVER be violated:**
1. **Critical urgency items must NEVER produce a draft or simulated send.** This is the most important safety invariant. It is tested explicitly.
2. **Gemini API must NEVER receive real customer data or PII.** The `SYNTHETIC_DATA_ONLY=true` guard enforces this.
3. **`POST /api/drafts/{id}/approve` must REJECT any Critical-linked draft** as an invariant violation.
4. **Dry-run mode must NEVER create any ticket, escalation, legal flag, draft, or outbound message** — only the agent run + proposed plan.
5. **Every generated draft MUST cite policy document and chunk IDs.** Drafts without citations cannot be approved.

---

## Tech Stack Quick Reference

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async (asyncpg) |
| LLM | DeepSeek V4 Flash 0731 via OpenRouter (OpenAI-compatible httpx client) |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (384-dim, CPU) |
| Database | PostgreSQL 16 + pgvector |
| Async Jobs | ARQ (async Redis queue) |
| Cache/Queue | Redis 7 |
| Frontend | React 18, TypeScript, Vite, TailwindCSS, Recharts, React Query |
| Auth | JWT (python-jose HS256) + bcrypt (passlib) |
| Testing | pytest, pytest-asyncio, httpx |
| Dev mode | Python venv in `backend/.venv`, Node in `frontend/node_modules` |
| Docker | Compose for full-stack deploy; `docker-compose.dev.yml` for DB+Redis only |

---

## Project Structure

```
d:\Code\EDAI Email\
├── backend\
│   ├── app\
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── config.py            # Pydantic settings (env vars)
│   │   ├── database.py          # Async SQLAlchemy engine + session
│   │   ├── core\
│   │   │   └── security.py      # JWT + bcrypt auth helpers
│   │   ├── models\              # SQLAlchemy ORM (15 entities)
│   │   ├── schemas\             # Pydantic request/response schemas
│   │   ├── api\                 # FastAPI routers (auth, ingest, threads, agent, analytics...)
│   │   ├── services\            # Business logic (gemini_adapter, web_enrichment...)
│   │   ├── intelligence\        # prefilter.py, classifier.py, sentiment_trend.py
│   │   ├── agent\               # react_loop.py + tools/
│   │   ├── rag\                 # embedder.py, retriever.py
│   │   └── worker\              # ARQ async worker tasks
│   ├── alembic\                 # DB migrations
│   ├── kb_documents\            # 6 Markdown policy files
│   ├── fixtures\                # 5 synthetic scenario JSONs
│   ├── scripts\                 # seed.py, seed_kb.py
│   └── tests\                   # unit + integration tests
├── frontend\
│   └── src\
│       ├── pages\               # MissionControl, ThreadWorkspace, Analytics
│       ├── components\
│       ├── hooks\
│       └── api\                 # HTTP client
├── docker-compose.yml           # Full stack (for demo)
├── docker-compose.dev.yml       # DB + Redis only (for venv dev)
├── .env.example                 # All required env vars (copy to .env)
├── dev.md                       # How to run in venv mode (step-by-step)
├── decisions.md                 # All architectural decisions
├── progress.md                  # Session-by-session progress log
└── agent_context.md             # This file
```

---

## Database Entities (15 total)

| Entity | Key Notes |
|---|---|
| `users` | Seeded: operator@nexus.example, supervisor@nexus.example |
| `accounts` | Seeded: AcmeCorp, TechStartup Inc., RetailCorp, GlobalTech |
| `contacts` | Normalized email; FK to account |
| `threads` | External thread/reply IDs; queue; status |
| `messages` | Unique `external_message_id`; sanitized body; job tracking |
| `classifications` | **Append-only**; index on `(contact_id, created_at)` for sentiment trend |
| `kb_documents` | 6 versioned policy docs |
| `kb_chunks` | 384-dim pgvector embedding; ivfflat cosine index |
| `rag_retrievals` | Records every retrieval (chunk, rank, score, timestamp) |
| `agent_runs` | One per processed email; JSONB trace (redacted); dry-run flag |
| `drafts` | Approval-required; citations required; reject if Critical |
| `tickets` | Source message + queue + status |
| `escalations` | Priority + queue; Supervisor-resolvable for High/Critical |
| `legal_flags` | Issue type + status; Supervisor-resolvable |
| `market_intel_cache` | Web enrichment results; 6h TTL |
| `audit_log` | **Immutable** append-only; records every agent run, approval, action |

---

## API Routes Quick Reference

| Area | Endpoints |
|---|---|
| Auth | POST /auth/login, POST /auth/logout, GET /auth/me |
| Ingestion | POST /api/ingest, POST /api/replay, GET /api/jobs/{job_id} |
| Inbox/Thread | GET /api/dashboard/stats, GET /api/threads, GET /api/threads/{id}, GET /api/messages/{id} |
| Agent/Actions | POST /api/messages/{id}/agent-runs, GET /api/agent-runs/{id}, PATCH /api/drafts/{id}, POST /api/drafts/{id}/approve, GET /api/tickets, GET /api/escalations, GET /api/legal-flags |
| CRM/Analytics | GET /api/contacts/{email}, PATCH /api/contacts/{email}/status, GET /api/analytics/sentiment-trend, GET /api/analytics/category-breakdown, GET /api/analytics/at-risk-accounts |
| RAG/Web/Audit | GET /api/rag/search, GET /api/market-intelligence, GET /api/audit/{entity_type}/{entity_id}, GET /health |

---

## Intelligence Pipeline (3 Layers)

**Layer 1 — Pre-filter (synchronous, deterministic)**
- Blocklist: `crypto giveaway`, `guaranteed profit`, `wire transfer`, `work from home`, click-through scams
- Domain denylist: configurable
- Internal: `@demo-company.example` → internal queue
- Urgency rules: ransomware/breach/extortion → Critical; DSAR/GDPR/C&D → High; billing/outage → Medium

**Layer 2 — LLM Classification (DeepSeek V4 Flash 0731 via OpenRouter)**
- Categories: `security`, `legal_compliance`, `reputation`, `billing_refund`, `product_support`, `sales_pricing`, `general_inquiry`
- Urgency: `low`, `medium`, `high`, `critical`
- Confidence < 0.70 → `human_review_required = true`
- Precedence: security > legal > reputation > billing > product > sales > inquiry

**Layer 3 — Sentiment Trend (on-demand)**
- 3 consecutive scores < -0.35 for same contact → at-risk alert
- No rollup table; computed via indexed query on `classifications`

---

## Agent (ReAct Loop)

- Max 4 tool calls per run
- Persists: rationale, action, observation (NOT private chain-of-thought)
- Dry-run: persist agent_run + proposed plan ONLY (no drafts, tickets, etc.)
- **Critical routing:** always `escalate_to_human`, NEVER `draft_reply`
- Tools: `search_knowledge_base`, `get_thread_history`, `draft_reply`, `escalate_to_human`, `create_internal_ticket`, `flag_for_legal`
- Contract-only (disabled): `get_contact_profile`, `check_account_status` → return `tool_not_enabled`

---

## 5 Acceptance Scenarios (Phase 2 Exit Criteria)

| # | Name | Expected Outcome |
|---|---|---|
| 1 | DSAR | legal flag + compliance ticket + approval-required holding ack (cites compliance policy) |
| 2 | Ransomware/Extortion | Critical security escalation; NO draft; NO simulated send |
| 3 | Own-product Misinformation | Policy retrieved, empathetic cited draft, escalation with discrepancy summary |
| 4 | Reputation Crisis | Async web-enrichment triggered, retention escalation, policy-grounded retention suggestion |
| 5 | Conflicting Thread Signals | Full thread history → correct previously agreed pricing tier identified |

---

## Environment Variables (required)

```bash
DATABASE_URL=postgresql+asyncpg://aura:aura_dev_password@localhost:5432/aura_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
OPENROUTER_API_KEY=<your openrouter key>
LLM_MODEL=deepseek/deepseek-v4-flash-0731
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_CACHE_DIR=./data/model_cache
SYNTHETIC_DATA_ONLY=true
ENRICHMENT_REVIEW_URL=https://www.g2.com/products/nexus-software
ENRICHMENT_COMPETITOR_URL=https://competitor.example.com/pricing
ENVIRONMENT=development
```

---

## How to Continue Work

### Start Dev Environment
```bash
# 1. Start DB + Redis
docker compose -f docker-compose.dev.yml up -d

# 2. Activate venv (Windows)
cd backend
.venv\Scripts\activate

# 3. Copy env (first time only)
copy ..\.env.example ..\.env
# Edit .env and set GEMINI_API_KEY

# 4. Run migrations (first time or after schema changes)
alembic upgrade head

# 5. Seed DB (first time only)
python scripts/seed.py
python scripts/seed_kb.py

# 6. Start backend
uvicorn app.main:app --reload

# 7. In another terminal: start frontend
cd frontend
npm run dev
```

### Run Tests
```bash
cd backend
pytest tests/ -v
pytest tests/test_scenarios.py -v  # acceptance scenarios
```

### Key Files to Read When Resuming
1. `progress.md` — what was done last session
2. `decisions.md` — all architecture decisions
3. `task.md` (in artifact dir) — task completion status
4. This file (`agent_context.md`) — all context
