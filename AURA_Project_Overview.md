# AURA
### Agentic CRM Intelligence Platform: An Autonomous, RAG-Grounded Email Operations & Triage System

## What it is
AURA is an AI-powered email operations system for support/sales inboxes. It doesn't just classify email — it ingests a live message stream, groups messages into threads, grounds its reasoning in company policy via Retrieval-Augmented Generation (RAG), and runs an autonomous, tool-using agent that decides and *takes* action: drafting a reply, escalating to a human, flagging legal/security, or opening a ticket. Every decision leaves an auditable reasoning trail.

## The problem it solves
Manual email triage is slow, inconsistent across agents, and prone to burying the signals that matter — a public-review threat, a compliance request with a legal deadline, a security incident disguised as a routine subject line. AURA replaces ad-hoc human judgment with a layered, explainable pipeline that never lets a Critical-urgency item slip through, and never auto-replies where a human legally or reputationally must be in the loop.

## Intended users and value
- **Support/sales agents & ops leads** (the system's real-world persona) — faster triage, fewer missed escalations, drafts they can approve instead of write from scratch.
- **The 4-person build team** — the actual near-term audience — gets hands-on experience with production AI-engineering patterns: RAG, tool-using agents, structured LLM output, and real API/schema design.
- **Course evaluators** — a working, demoable system judged against explicit weighted criteria (repo hygiene, architecture diagram, ER diagram/schema, KB docs, recorded walkthrough, OpenAPI spec).

## Core features and outcomes
- Real-time ingestion pipeline: schema validation, deduplication, thread linking, configurable-speed stream replay.
- 3-layer intelligence engine: millisecond heuristic pre-filter → LLM classification (category/sentiment/urgency/etc.) → sentiment trend tracking with deterioration alerts.
- RAG pipeline over 6 policy knowledge-base documents, cited in every AI-generated reply.
- Autonomous agent (ReAct-style Thought → Action → Observation) with ≥4 tools, capped tool-call budget, dry-run mode, and a hard rule: never auto-reply to Critical urgency.
- Optional live web-intelligence enrichment (review sites, competitor pricing) for reputation-sensitive threads.
- 3-view operator dashboard: Mission Control Inbox, Thread Workspace, Analytics.
- Validated against 5 curated high-stakes scenarios (DSAR, extortion threat, own-product misinformation, reputation crisis, conflicting thread signals) used as the actual demo script.
