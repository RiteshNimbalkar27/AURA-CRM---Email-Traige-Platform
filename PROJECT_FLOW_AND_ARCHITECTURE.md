# AURA — Project Flow & System Architecture

> **AURA** (Agentic CRM Intelligence Platform) is a locally deployed, supervised email triage system for B2B SaaS inboxes (Nexus Software Inc.).
> This document details the end-to-end data pipeline, decision rules, RAG retrieval mechanism, ReAct agent loop, and human-in-the-loop governance invariants.

---

## 1. High-Level System Architecture

```mermaid
flowchart TD
    subgraph Ingestion["1. Ingestion Layer"]
        Inbound["Inbound Email\n(POST /api/ingest)"] --> Sanitize["HTML Strip & Body Truncation\n(Max 10,000 chars)"]
        Sanitize --> Dedup{"Deduplication Check\n(external_message_id)"}
        Dedup -- Duplicate --> RetDup["Return Existing Job / Message\n(HTTP 202 duplicate: true)"]
        Dedup -- Unique --> ThreadLink["Thread Linking Fallback\n1. external_thread_id\n2. reply_to_external_id\n3. normalized sender + subject"]
        ThreadLink --> SaveMsg["Persist Message & Thread\n(job_status: queued)"]
        SaveMsg --> ARQEnqueue["Enqueue ARQ Job\n(classify_message_task)"]
    end

    subgraph Intelligence["2. Intelligence Pipeline"]
        ARQEnqueue --> L1Prefilter["Layer 1: Deterministic Pre-filter\n(prefilter.py)"]
        
        L1Prefilter -- Block Spam/Scam --> BlockSpam["Reject / Fail Job\n(Never sent to LLM)"]
        L1Prefilter -- Internal Domain --> RouteInternal["Flag Internal Queue\n(@demo-company.example)"]
        L1Prefilter -- Urgency Override --> ForceUrgency["Set Urgency Hint\n(Critical / High / Medium)"]
        L1Prefilter -- Allow --> L2Classifier["Layer 2: LLM Classification\n(DeepSeek V4 Flash via OpenRouter)"]
        ForceUrgency --> L2Classifier
        RouteInternal --> L2Classifier
        
        L2Classifier --> SchemaCheck{"Pydantic JSON Validation\n& Critical Urgency Guard"}
        SchemaCheck --> SaveCls["Persist Classification Record\n(Append-only)"]
        SaveCls --> UpdateQueue["Route Thread to Queue\n(security | legal_compliance |\nreputation_retention | support_operations)"]
    end

    subgraph RAG["3. Policy RAG Engine"]
        KB[("6 Policy Markdown Docs\nChunked @ 400 tokens / 50 overlap")] --> Embed["all-MiniLM-L6-v2 (CPU)\n384-dim Vectors"]
        Embed --> PGVector[("PostgreSQL 16 + pgvector\n(kb_chunks cosine distance <=>)")]
        PGVector --> Retrieve["Retriever (top-k cosine similarity)\n+ Record RAGRetrieval Audit Rows"]
    end

    subgraph AgentLoop["4. Supervised ReAct Agent Loop (Phase 2)"]
        SaveCls --> TriggerAgent["Trigger Agent Run\n(Live or Dry-Run)"]
        TriggerAgent --> ReAct["ReAct Reasoning Loop\n(Max 4 Tool Calls)"]
        
        ReAct <--> Tools["Agent Tools:\n- search_knowledge_base\n- get_thread_history\n- draft_reply (requires citations)\n- escalate_to_human\n- create_internal_ticket\n- flag_for_legal"]
        Retrieve -.-> Tools
        
        ReAct --> Trace["Persist Redacted JSONB Trace\n(step, rationale, action, observation)"]
    end

    subgraph Governance["5. Human-in-the-Loop Governance"]
        ReAct --> DraftAction{"Draft Reply Created?"}
        DraftAction -- Yes --> DraftCheck{"Is Thread Critical?"}
        DraftCheck -- Critical --> DenyDraft["HARD INVARIANT:\nCritical Items NEVER Draft or Reply"]
        DraftCheck -- Non-Critical --> PendingDraft["Draft (pending_approval)\nMust cite Doc & Chunk IDs"]
        PendingDraft --> OperatorUI["Mission Control Inbox\n(Operator / Supervisor UI)"]
        OperatorUI --> Approve["POST /api/drafts/{id}/approve\n(Simulated Outbound Send)"]
        
        ReAct --> EscalationTicket["Create Escalation / Ticket / Legal Flag"]
        EscalationTicket --> OperatorUI
    end
```

---

## 2. Step-by-Step Data Flow

### Step 1: Ingestion & Thread Linking (`app/api/ingest.py`)
1. **Endpoint**: `POST /api/ingest` accepts `{ external_message_id, external_thread_id?, reply_to_external_id?, sender_email, subject, body, received_at }`.
2. **Sanitization**:
   - `BeautifulSoup` strips HTML tags, raw scripts, and styles. Blank bodies return `HTTP 422 Unprocessable Entity`.
   - Large bodies (>10,000 characters) are sliced into the first 8,000 + last 2,000 characters to protect LLM context windows while preserving headers and sign-offs.
3. **Deduplication**:
   - Query `messages.external_message_id`. If matched, return the existing `message_id`, `thread_id`, and `job_id` with `duplicate: true`. No duplicate record or background job is created.
4. **Three-Tier Thread Linking**:
   - **Tier 1 (Exact External Thread ID)**: Match `threads.external_thread_id`.
   - **Tier 2 (Reply Reference)**: Look up `reply_to_external_id` in `messages.external_message_id` and attach to that parent message's thread.
   - **Tier 3 (Fuzzy Subject + Sender)**: Iteratively strip `Re:`, `Fwd:`, `Fw:` prefixes; match normalized subject and sender against the most recent open thread.
   - **Fallback**: Create a brand-new `Thread` record assigned to `support_operations`.
5. **Job Enqueue**:
   - Persists message with `job_status="queued"`.
   - Dispatches `classify_message_task` to the Redis ARQ queue.

---

### Step 2: Layer 1 Deterministic Pre-Filter (`app/intelligence/prefilter.py`)
Synchronous, deterministic rules evaluated before any external API call:

| Rule Branch | Criteria / Keywords | Action & Urgency Override | Target Queue / Behavior |
|---|---|---|---|
| **Rule 1: Spam / Scam** | `crypto giveaway`, `guaranteed profit`, `wire transfer`, `work from home`, `click here to claim`, `you've been selected` | `action="block"` | Message fails immediately. Never sent to LLM. |
| **Rule 2: Internal Domain** | Sender domain ends with `@demo-company.example` | `action="internal"` | Route to internal triage queue. |
| **Rule 3: Critical Security** | `ransomware`, `data breach`, `leaked credentials`, `unauthorized access`, `extortion`, `dark web` | `action="allow"`, `urgency_override="critical"` | Pre-pends urgency instruction; forces final urgency to `critical`. |
| **Rule 4: High Compliance/PR** | `dsar`, `gdpr`, `cease-and-desist`, `lawsuit`, `legal action`, `public review threat`, `press inquiry`, `investor inquiry` | `action="allow"`, `urgency_override="high"` | Routes to legal or reputation queues. |
| **Rule 5: Medium Operational** | `refund`, `billing dispute`, `service outage`, `misinformation`, `cancellation request` | `action="allow"`, `urgency_override="medium"` | Operational escalation threshold. |
| **Default** | No keyword matches | `action="allow"`, `urgency_override=None` | Pure LLM classification. |

---

### Step 3: Layer 2 LLM Classification (`app/intelligence/classifier.py`)
1. **Model Adapter**: DeepSeek V4 Flash 0731 via OpenRouter (OpenAI-compatible `/chat/completions`).
2. **Context Window**: Includes sanitized body, subject, and recent thread history (last 5 messages) plus any pre-filter system hints.
3. **Structured Output**: Strictly parsed into Pydantic model:
   - `category`: `security` | `legal_compliance` | `reputation` | `billing_refund` | `product_support` | `sales_pricing` | `general_inquiry`
   - `urgency`: `low` | `medium` | `high` | `critical`
   - `sentiment_score`: Continuous `[-1.0, 1.0]`
   - `confidence`: Continuous `[0.0, 1.0]`
   - `entities`: `{ people, organizations, topics, dates }`
   - `rationale` & `proposed_action`
4. **Safety Invariants**:
   - If pre-filter flagged `critical`, the output urgency is locked to `critical` (model downgrade is strictly prohibited).
   - If `confidence < 0.70`, `human_review_required` is automatically set to `true`.
5. **Persistence**:
   - Inserted as an **append-only** record into `classifications` (never updated, preserving full audit history).
   - Message updated to `job_status="completed"`.

---

### Step 4: RAG Policy Retrieval (`app/rag/embedder.py` & `retriever.py`)
1. **Knowledge Base Documents**:
   - 6 versioned Markdown policies in `backend/kb_documents/`:
     1. `api_limits_and_deprecations.md`
     2. `escalation_ownership_matrix.md`
     3. `gdpr_hipaa_soc2_data_residency.md`
     4. `pricing_tiers_and_discounts.md`
     5. `refunds_and_retention_offers.md`
     6. `sla_and_credits.md`
2. **Chunking & Embeddings**:
   - Chunked at 400 tokens with 50-token overlap.
   - Embedded locally using `all-MiniLM-L6-v2` (384-dimensional dense vectors, CPU-optimized).
3. **Search & Audit**:
   - Cosine distance search using pgvector's `<=>` operator:
     $$\text{score} = 1.0 - (\text{embedding} \iff \text{query\_vector})$$
   - Returns top $k$ chunks (default: 3).
   - Every search logs immutable `rag_retrievals` audit rows linking `agent_run_id`, `chunk_id`, `rank`, and `score`.

---

### Step 5: Layer 3 Sentiment & Risk Analytics
- Computed on-demand via composite index `(contact_id, created_at)` on `classifications`.
- **At-Risk Trigger**: If a contact has $\ge 3$ consecutive messages with `sentiment_score < -0.35`, the contact operational status transitions to `at_risk`.
- No separate rollup table is used; dynamic queries maintain real-time accuracy without sync anomalies.

---

### Step 6: Supervised ReAct Agent Loop (Phase 2)
1. **Loop Structure**: Custom Thought $\to$ Action $\to$ Observation loop capped at a hard maximum of **4 tool executions**.
2. **Auditable Traces**:
   - Private model chain-of-thought is discarded.
   - A sanitized, redacted JSONB trace is persisted to `agent_runs.trace`:
     ```json
     [
       {"step": 1, "rationale": "Checking customer thread history to understand invoice discrepancy", "action": "get_thread_history", "observation": "..."},
       {"step": 2, "rationale": "Searching refund policy for Enterprise tier customers", "action": "search_knowledge_base", "observation": "..."}
     ]
     ```
3. **Dry-Run Mode (`mode="dry_run"`)**:
   - Runs the full ReAct loop and plans all proposed actions.
   - Mutates **zero** production state: creates no ticket, escalation, legal flag, draft, or outbound send.
   - Persists only the `AgentRun` record marked with `outcome="dry_run"`.

---

### Step 7: Tool Execution Matrix

| Tool Name | Input Parameters | Output Payload | Status |
|---|---|---|---|
| `search_knowledge_base` | `query: str`, `max_results: int (1..3)` | `{ chunks: [{ chunk_id, document_id, title, excerpt, score }] }` | **MVP Active** |
| `get_thread_history` | `sender_email: str`, `limit: int (1..50)` | `{ threads: [{ thread_id, messages: [...] }] }` | **MVP Active** |
| `draft_reply` | `message_id: UUID`, `tone: str`, `policy_refs: [chunk_id]` | `{ draft_id, body, citations: [...], requires_approval: true }` | **MVP Active** |
| `escalate_to_human` | `message_id: UUID`, `reason: str`, `priority: str`, `queue: str` | `{ escalation_id, queue, priority, status: "open", brief }` | **MVP Active** |
| `create_internal_ticket` | `source_message_id: UUID`, `title: str`, `body: str`, `assignee_queue: str` | `{ ticket_id, assignee_queue, status: "open" }` | **MVP Active** |
| `flag_for_legal` | `message_id: UUID`, `issue_type: str`, `summary: str` | `{ legal_flag_id, issue_type, status: "open", queue: "legal_compliance" }` | **MVP Active** |
| `get_contact_profile` | `email: str` | `{ ok: false, error: "tool_not_enabled" }` | Contract Stub |
| `check_account_status` | `email: str` | `{ ok: false, error: "tool_not_enabled" }` | Contract Stub |

---

### Step 8: Human-in-the-Loop Governance & Safety Invariants

```mermaid
stateDiagram-v2
    [*] --> Triage: Ingestion & Classification
    Triage --> CriticalCheck: Evaluate Urgency
    
    CriticalCheck --> CriticalPath: urgency == "critical"
    CriticalCheck --> StandardPath: urgency != "critical"
    
    state CriticalPath {
        [*] --> ImmediateEscalation: Queue: security
        ImmediateEscalation --> BlockDraft: draft_reply tool DISABLED
        BlockDraft --> SecOpsNotification: Alert Supervisor
        SecOpsNotification --> [*]
    }
    
    state StandardPath {
        [*] --> AgentDraft: draft_reply (citing KB Chunks)
        AgentDraft --> PendingApproval: status: pending_approval
        PendingApproval --> OperatorReview: Operator Inspects
        OperatorReview --> ApproveSend: POST /api/drafts/{id}/approve
        OperatorReview --> RejectDraft: Reject / Edit Draft
        ApproveSend --> SimulatedSend: Outbound Simulation
        RejectDraft --> [*]
        SimulatedSend --> [*]
    }
```

> [!CAUTION]
> **The Critical Invariant Rule**: If an email is classified as `critical` (ransomware, extortion, data leak, unauthorized access):
> 1. The agent loop is strictly forbidden from executing `draft_reply`.
> 2. `POST /api/drafts/{id}/approve` contains a hard backend check: any attempt to approve a reply tied to a Critical message raises `HTTP 400 Bad Request`.
> 3. No outbound email can ever be simulated or sent.

---

## 3. Database Entity Relationship Diagram

The PostgreSQL database encompasses 15 core entities:

```mermaid
erDiagram
    users ||--o{ drafts : "approved_by"
    users ||--o{ escalations : "resolved_by"
    users ||--o{ legal_flags : "resolved_by"
    
    accounts ||--o{ contacts : "has"
    accounts ||--o{ threads : "associated_with"
    
    contacts ||--o{ threads : "participates_in"
    contacts ||--o{ messages : "sends"
    contacts ||--o{ classifications : "evaluated_for"
    
    threads ||--o{ messages : "contains"
    threads ||--o{ classifications : "tagged_with"
    
    messages ||--o{ classifications : "classified_as"
    messages ||--o{ agent_runs : "processed_by"
    messages ||--o{ drafts : "generates"
    messages ||--o{ tickets : "creates"
    messages ||--o{ escalations : "triggers"
    messages ||--o{ legal_flags : "flags"
    
    agent_runs ||--o{ drafts : "produces"
    agent_runs ||--o{ tickets : "creates"
    agent_runs ||--o{ escalations : "escalates"
    agent_runs ||--o{ legal_flags : "flags"
    agent_runs ||--o{ rag_retrievals : "records"
    
    kb_documents ||--o{ kb_chunks : "contains"
    kb_chunks ||--o{ rag_retrievals : "retrieved_in"
    
    users {
        uuid id PK
        string email UK
        string hashed_password
        string role "operator | supervisor"
        boolean is_active
    }
    
    threads {
        uuid id PK
        string external_thread_id UK
        string subject
        string queue
        string status "open | in_progress | resolved"
        timestamp last_message_at
    }
    
    messages {
        uuid id PK
        string external_message_id UK
        uuid thread_id FK
        string sender_email
        text body_sanitized
        string job_status "pending | queued | processing | completed | failed"
        timestamp received_at
    }
    
    classifications {
        uuid id PK
        uuid message_id FK
        string category
        string urgency "low | medium | high | critical"
        float sentiment_score
        float confidence
        boolean human_review_required
        jsonb entities
    }
    
    agent_runs {
        uuid id PK
        uuid message_id FK
        string mode "live | dry_run"
        int tool_calls_count
        jsonb trace "redacted"
        string outcome
    }
    
    drafts {
        uuid id PK
        uuid message_id FK
        text body
        string tone
        jsonb citations
        string status "pending_approval | approved | rejected"
        uuid approved_by FK
    }
```

---

## 4. Acceptance Scenarios Matrix

| Scenario | Input Case | Expected Intelligence | Tool Invocations | Expected Artifacts & Governance |
|---|---|---|---|---|
| **01: DSAR Compliance** | Customer demands erasure under GDPR Article 17 | `category: legal_compliance`<br>`urgency: high` | 1. `search_knowledge_base`<br>2. `flag_for_legal`<br>3. `create_internal_ticket`<br>4. `draft_reply` | - Legal Flag (`dsar`)<br>- Compliance Ticket<br>- Holding Ack Draft citing GDPR doc<br>- Approval required |
| **02: Ransomware Incident** | Attacker claims server encryption, demands BTC | `category: security`<br>`urgency: critical` (L1 Pre-filter lock) | 1. `escalate_to_human` | - Critical Escalation to `security`<br>- **NO draft created**<br>- **NO reply approved/sent** |
| **03: Misinformation / Outage** | Customer complains about conflicting outage SLA | `category: billing_refund`<br>`urgency: medium` | 1. `search_knowledge_base`<br>2. `create_internal_ticket`<br>3. `draft_reply` | - Ticket to Ops<br>- Empathetic Draft with SLA policy citations<br>- Operator approval flow |
| **04: Reputation Crisis** | Customer threatens negative G2 review & viral post | `category: reputation`<br>`urgency: high` | 1. `escalate_to_human`<br>2. `search_knowledge_base`<br>3. `draft_reply` | - Retention Escalation<br>- Web enrichment trigger<br>- Retention offer draft |
| **05: Conflicting Signals** | Thread disputes pricing tier previously offered | `category: sales_pricing`<br>`urgency: medium` | 1. `get_thread_history`<br>2. `search_knowledge_base`<br>3. `draft_reply` | - Full thread history inspected<br>- Correct legacy pricing honored<br>- Grounded draft citing pricing policy |

---

## 5. Security & Isolation Invariants

1. **Synthetic Data Only**: All processing is strictly confined to fictional demo data. Regex guards reject social security numbers or credit card patterns prior to any LLM API call.
2. **Deterministic Precedence**: Critical security threats always take precedence over billing or sales inquiries, preventing LLM prompt injection or downgrade attacks from obscuring security events.
3. **Immutable Audit Trails**: Classifications, RAG retrievals, agent traces, and audit logs are append-only.
4. **Local Infrastructure**: Embeddings (`all-MiniLM-L6-v2`) and pgvector store operate entirely on local CPU and Docker containers; zero persistent customer data leaves the host environment.
