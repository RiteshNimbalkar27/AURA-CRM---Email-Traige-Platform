# AURA — Agentic CRM Intelligence Platform

> Supervised, RAG-grounded email triage for B2B support inboxes.
> **Synthetic demo data only. No real customer or PII data.**

[![Phase](https://img.shields.io/badge/phase-1%20ingestion%20%2B%20intelligence-green)]
[![Phase 2 Ready](https://img.shields.io/badge/phase-2%20agent%20ready-blue)]

## Overview

AURA is a locally-deployed AI email operations system that:
- Ingests and threads synthetic B2B support emails with deduplication
- Filters spam and overrides urgency via a deterministic Layer 1 pre-filter
- Classifies risk, urgency, intent, and sentiment via DeepSeek V4 Flash 0731 (OpenRouter)
- Retrieves relevant internal policies via RAG with pgvector cosine search (384-dim)
- Runs a supervised ReAct agent that drafts replies, escalates, or flags issues
- Surfaces inbox metrics, threads, and triage queues in a Mission Control dashboard

**Every outbound action requires Operator approval. Critical items never produce a reply.**

## Quick Start

See [dev.md](dev.md) for the full venv-based development guide.

```powershell
# 1. Start DB + Redis
docker compose -f docker-compose.dev.yml up -d

# 2. Setup backend
cd backend
python -m venv .venv && .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy ../.env.example ../.env  # then edit .env
alembic upgrade head
python scripts/seed.py && python scripts/seed_kb.py
uvicorn app.main:app --reload

# 3. Start frontend (new terminal)
cd frontend && npm install && npm run dev
```

## Architecture

```
Email Ingestion → Layer 1 Pre-filter → Layer 2 LLM Classification
                                    ↓
                            RAG (pgvector) ← KB Documents (6 policies)
                                    ↓
                         ReAct Agent Loop (max 4 tool calls)
                                    ↓
              Draft / Escalate / Ticket / Legal Flag
                                    ↓
                    Operator Approval (never autonomous)
```

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async (asyncpg) |
| LLM | DeepSeek V4 Flash 0731 via OpenRouter (OpenAI-compatible) |
| Embeddings | all-MiniLM-L6-v2 (local, CPU, 384-dim) |
| Database | PostgreSQL 16 + pgvector |
| Async Jobs | ARQ + Redis 7 |
| Frontend | React 18, TypeScript, Vite, TailwindCSS |

## Required Environment Variables

Copy `.env.example` to `.env` and set:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL async connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Yes | Redis connection string (`redis://localhost:6379/0`) |
| `SECRET_KEY` | Yes | JWT signing key |
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key |
| `LLM_MODEL` | Yes | Model ID (`deepseek/deepseek-v4-flash-0731`) |
| `SYNTHETIC_DATA_ONLY` | Yes | Must be `true` — guards against real PII |

## Security Notes

- `SYNTHETIC_DATA_ONLY=true` is enforced before every LLM API call.
- Real customer data and PII must **never** be ingested into this system.
- All secrets are outside source control (`.env` is gitignored).
- Role-based access is enforced server-side on all protected endpoints.

## Data Handling

This system is designed exclusively for synthetic demo data. The `.gitignore`
excludes `.env`, `data/`, and any file matching `*_real_*` or `*_live_*`.

## Project Documentation

- [PROJECT_FLOW_AND_ARCHITECTURE.md](PROJECT_FLOW_AND_ARCHITECTURE.md) — comprehensive end-to-end architecture & triage flow guide
- [decisions.md](decisions.md) — all architectural decisions
- [progress.md](progress.md) — session-by-session progress log
- [agent_context.md](agent_context.md) — AI agent context for resuming work
- [dev.md](dev.md) — detailed development setup guide
- [SPECIFICATION_SHEET.md](SPECIFICATION_SHEET.md) — full product specification
- [PLAN.md](PLAN.md) — implementation specification draft

## Seeded Demo Accounts

| Role | Email | Capabilities |
|---|---|---|
| Operator | operator@nexus.example | Triage, draft editing, approve simulated sends |
| Supervisor | supervisor@nexus.example | + Resolve High/Critical escalations and legal flags |

**Default passwords are in `dev.md`. Change before any non-local deployment.**

## Delivery Phases

| Phase | Status | Description |
|---|---|---|
| 0 — Foundation | ✅ Complete | Compose, DB, Auth, Fixtures, LLM smoke, seed scripts |
| 1 — Ingestion + Intelligence + RAG | ✅ Complete | Ingestion, pre-filter, classification, pgvector RAG, ARQ worker, inbox APIs |
| 2 — Agent + Tools + Scenarios | 🟡 Ready to Begin | 6 tools, ReAct loop, dry-run, approval gate, 5 scenario acceptance tests |
| 3 — Web Enrichment + Dashboard | ⬜ Planned | Web scraping, React frontend, analytics, benchmarks |
