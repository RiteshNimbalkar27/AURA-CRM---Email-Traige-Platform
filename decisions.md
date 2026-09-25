# AURA — Decision Log

This file is the authoritative record of all architectural and product decisions.
Every decision resolves an open question from `SPECIFICATION_SHEET.md` Section 17
or documents a technical tradeoff made during implementation.

---

## DEC-001: LLM Provider — Gemini 1.5 Flash

**Date:** 2026-09-18
**Status:** Resolved
**Source:** PLAN.md supersedes brainstorm.md (OpenAI references are historical)

**Decision:** Use `gemini-1.5-flash` (free tier) as the sole LLM provider.

**Rationale:**
- No API budget available; Gemini free tier is sufficient for synthetic demo data.
- Supports function calling required for structured classification and agent tool use.
- Explicitly chosen in PLAN.md to supersede earlier OpenAI/Claude references.

**Constraints:**
- Synthetic data ONLY. Real customer / PII data must never be passed to Gemini.
- Rate limiting: handle 429s with exponential backoff (3 retries: 1s, 2s, 4s).
- `SYNTHETIC_DATA_ONLY=true` env guard must be checked before every Gemini call.

---

## DEC-002: Synthetic Company Identity — Nexus Software Inc.

**Date:** 2026-09-18
**Status:** Resolved

**Decision:** The fictional B2B SaaS company used throughout all KB documents, fixtures, and demo data is **Nexus Software Inc.** — a project management and team collaboration software provider.

**Plans:**
- Starter: \$29/month (up to 5 users)
- Professional: \$79/month (up to 25 users)
- Enterprise: Custom pricing (25+ users)

**Seed accounts:** AcmeCorp, TechStartup Inc., RetailCorp, GlobalTech
**Seed users:** `operator@nexus.example`, `supervisor@nexus.example`

---

## DEC-003: Auth — JWT + bcrypt, 24-hour Sessions

**Date:** 2026-09-18
**Status:** Resolved (Phase 0 decision gate)

**Decision:**
- Passwords hashed with bcrypt via `passlib[bcrypt]`
- Auth tokens: JWT signed with HS256 via `python-jose[cryptography]`
- Session duration: 1440 minutes (24 hours)
- No CSRF protection for MVP (single-tenant local deployment only)
- Stateless JWT: logout is client-side token discard (no server-side token blacklist in MVP)

**V1 note:** Session lifecycle, CSRF, and rate-limiting are V1 hardening items per Section 15.

---

## DEC-004: Async Worker — ARQ (Redis-backed)

**Date:** 2026-09-18
**Status:** Resolved

**Decision:** Use `arq` (Async Redis Queue) for background job processing.

**Rationale:**
- Pure Python async — fits FastAPI's asyncio model cleanly.
- Simpler than Celery for this project's scale.
- Redis is already required for job queue; no additional infrastructure.
- Supports job result retrieval (maps to `GET /api/jobs/{job_id}`).

**Alternative considered:** Celery — rejected because it requires more configuration and a separate sync worker process.

---

## DEC-005: Embedding Runtime — sentence-transformers (CPU only)

**Date:** 2026-09-18
**Status:** Resolved

**Decision:** Use `sentence-transformers` with `all-MiniLM-L6-v2` (384-dim) on CPU.

**Rationale:**
- Matches spec requirement exactly.
- CPU-only `torch` keeps Docker image size manageable and avoids GPU dependency.
- 384-dim vectors fit the pgvector ivfflat index efficiently.
- Model cache stored in `./data/model_cache` (project-local, not on C: drive).

---

## DEC-006: Development Mode — venv on D: Drive

**Date:** 2026-09-18
**Status:** Resolved (user requirement)

**Decision:** Backend runs in a Python venv located inside the project directory.
Frontend runs with local Node.js (node_modules inside project dir).
Only PostgreSQL + Redis run via Docker Compose in dev mode.

**Files:**
- Backend venv: `d:\Code\EDAI Email\backend\.venv\`
- Frontend deps: `d:\Code\EDAI Email\frontend\node_modules\`
- DB data: `d:\Code\EDAI Email\data\postgres\`
- Redis data: `d:\Code\EDAI Email\data\redis\`
- Model cache: `d:\Code\EDAI Email\data\model_cache\`

**Docker Compose variants:**
- `docker-compose.dev.yml` — DB + Redis only (for venv dev)
- `docker-compose.yml` — Full stack (for demo/submission)

---

## DEC-007: Frontend Stack — React 18 + TypeScript + Vite + Tailwind + Recharts

**Date:** 2026-09-18
**Status:** Resolved

**Decision:**
- React 18 with TypeScript for type safety
- Vite for fast dev server
- TailwindCSS for utility-first styling
- Recharts for analytics charts
- React Query (TanStack Query) for server state + polling
- React Router v6 for navigation
- Axios for HTTP client

---

## DEC-008: API Pagination Defaults

**Date:** 2026-09-18
**Status:** Resolved (Phase 1 decision gate)

**Decision:** All list endpoints default to `page=1`, `page_size=20`, `sort=created_at:desc`.
Maximum `page_size` capped at 100.

---

## DEC-009: Benchmark Setup

**Date:** 2026-09-18
**Status:** Resolved (Phase 1 decision gate)

**Decision:**
- Dataset: 100 classification rows seeded for benchmark tests
- Measurement: `time.perf_counter()` + `pytest-benchmark`
- Host: developer workstation (whatever machine runs the tests)
- Targets from spec Section 10:
  - Pre-filter: < 10ms
  - Thread read (50 msgs): < 100ms
  - Sentiment trend (30-day indexed): record query plan via EXPLAIN ANALYZE
  - Vector search top-3: < 200ms

---

## DEC-010: Allowlisted Web Enrichment URLs

**Date:** 2026-09-18
**Status:** Resolved (needed before Phase 3)

**Decision:** MVP uses placeholder URLs (real URLs to be confirmed by project lead before Phase 3):
- Review source: `https://www.g2.com/products/nexus-software` (placeholder)
- Competitor pricing: `https://competitor.example.com/pricing` (placeholder, will 404)

robots.txt is always checked before fetching. Failure (404, timeout, robots denied) is recorded in `market_intel_cache` and never blocks triage.

---

## DEC-011: Queue Ownership / Escalation Routing

**Date:** 2026-09-18
**Status:** Resolved (Phase 1 decision gate)

| Urgency/Category | Queue | Owner | SLA |
|---|---|---|---|
| Critical security | `security` | SecOps | < 15 min |
| Legal/compliance (DSAR, GDPR, C&D, lawsuit) | `legal_compliance` | Legal | < 4 hours |
| Reputation crisis (press, investor, public review) | `reputation_retention` | PR + CX | < 1 hour |
| Billing / product support | `support_operations` | Support | Per plan SLA |
| Internal messages | `internal` | Team lead | Best effort |
| Spam | `spam` | Auto-archived | N/A |

---

## DEC-012: Classification Category Precedence (Mixed Signals)

**Date:** 2026-09-18
**Status:** Resolved (from SPECIFICATION_SHEET.md Section 5.2)

Fixed precedence order (most severe wins):
1. `security`
2. `legal_compliance`
3. `reputation`
4. `billing_refund`
5. `product_support`
6. `sales_pricing`
7. `general_inquiry`

`sentiment_score` remains a continuous float and reflects the actual tone independently of the category decision.
