"""
AURA ReAct Agent Loop
=====================
A fully custom Reasoning + Acting (ReAct) loop for email triage.
Does NOT depend on LangChain, AutoGen, or any third-party agent framework.

Design contract
---------------
* Max 4 tool calls per run (``MAX_TOOL_CALLS``).
* Maintains a ``trace`` list of ``{step, rationale, action, observation}`` dicts.
  — No private chain-of-thought is stored; only the public reasoning trace.
* Accepts ``mode='live'`` or ``mode='dry_run'``.
  — In ``dry_run`` mode: ``AgentRun`` is persisted with ``outcome='dry_run'``
    but NO Tickets, Escalations, Drafts, or LegalFlags are written.
* All tool results are wrapped in ``{ok, tool_name, data, error?}``.

Safety invariants (HARD RULES)
--------------------------------
1. ``urgency == 'critical'`` → NEVER call ``draft_reply``.  Always
   escalate to the security queue via ``escalate_to_human``.
2. Tool-call limit: stop after ``MAX_TOOL_CALLS`` with ``outcome='completed'``.
3. Contract-only stubs (``get_contact_profile``, ``check_account_status``) always
   return ``{ok: False, error: 'tool_not_enabled'}``.

Entry-point
-----------
``run_agent(...)`` — see its docstring below.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentRun, Draft, Escalation, LegalFlag, Ticket
from app.models.email import Message, Thread  # noqa: F401 — referenced by relationships
from app.services.llm_adapter import LLMError, get_llm_adapter
from app.rag.retriever import retrieve_and_record  # noqa: F401 — used indirectly via tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOOL_CALLS: int = 4
"""Hard cap on tool invocations per agent run."""

_STUB_TOOLS: frozenset[str] = frozenset({"get_contact_profile", "check_account_status"})
"""Tools that are registered but not yet enabled — always return an error."""

# ---------------------------------------------------------------------------
# System prompt (describes all tools for the LLM)
# ---------------------------------------------------------------------------

_REACT_SYSTEM_PROMPT = """\
You are AURA, an AI email triage agent for Nexus Software Inc. (B2B SaaS).
Your job is to reason step-by-step and use the available tools to handle an incoming customer email.

CRITICAL SAFETY RULES (never break these):
1. If urgency == "critical": you MUST call escalate_to_human with queue="security". \
NEVER call draft_reply for critical emails.
2. You may call at most {max_tool_calls} tools per run. After that you must return done.
3. All data is synthetic demo data. Never include real PII in tool arguments.

AVAILABLE TOOLS (call one at a time):
---------------------------------------------------------------------
Tool: search_knowledge_base
  Purpose: Search the internal knowledge base for relevant policy/documentation chunks.
  Input JSON: {{"query": "<string>", "max_results": <int 1-3>}}
  Output:     {{"chunks": [{{"chunk_id": "<uuid>", "document_id": "<uuid>",
                             "title": "<string>", "excerpt": "<string>", "score": <float>}}]}}

Tool: get_thread_history
  Purpose: Retrieve prior email thread history for this sender.
  Input JSON: {{"sender_email": "<email>", "limit": <int 1-50>}}
  Output:     {{"threads": [{{"thread_id": "<uuid>",
                              "messages": [{{"message_id": "<uuid>", "received_at": "<iso>",
                                            "subject": "<string>", "body_excerpt": "<string>",
                                            "classification": "<category|null>"}}]}}]}}

Tool: draft_reply
  Purpose: Generate a grounded draft reply to the customer (requires policy chunks).
           DO NOT call this if urgency == "critical".
  Input JSON: {{"message_id": "<uuid>", "tone": "<empathetic|formal|assertive>",
               "policy_refs": ["<chunk_id>", ...]}}
  Output:     {{"draft_id": "<uuid>", "body": "<string>",
               "citations": [{{"document_id": "<uuid>", "chunk_id": "<uuid>"}}],
               "requires_approval": true}}

Tool: escalate_to_human
  Purpose: Escalate this email to a human operator queue.
  Input JSON: {{"message_id": "<uuid>", "reason": "<string>",
               "priority": "<low|medium|high|critical>",
               "queue": "<security|legal_compliance|reputation_retention|support_operations>"}}
  Output:     {{"escalation_id": "<uuid>", "queue": "<string>",
               "priority": "<string>", "status": "open", "brief": "<string>"}}

Tool: create_internal_ticket
  Purpose: Open an internal operational ticket for follow-up.
  Input JSON: {{"source_message_id": "<uuid>", "title": "<string>",
               "body": "<string>", "assignee_queue": "<string>"}}
  Output:     {{"ticket_id": "<uuid>", "assignee_queue": "<string>", "status": "open"}}

Tool: flag_for_legal
  Purpose: Flag this email for the legal/compliance team.
  Input JSON: {{"message_id": "<uuid>",
               "issue_type": "<dsar|gdpr|cease_and_desist|lawsuit|regulatory>",
               "summary": "<string>"}}
  Output:     {{"legal_flag_id": "<uuid>", "issue_type": "<string>",
               "status": "open", "queue": "legal_compliance"}}

Tool: get_contact_profile   [STUB — not enabled]
Tool: check_account_status  [STUB — not enabled]
  These tools are not available. Calling them returns an error.
---------------------------------------------------------------------

RESPONSE FORMAT (strict JSON, no markdown fences, no extra keys):
Either call a tool:
  {{"action": "<tool_name>", "args": {{...}}, "rationale": "<why>"}}
Or signal completion:
  {{"action": "done", "rationale": "<summary of what was done>"}}

Think carefully before each tool call. Do not repeat tool calls unnecessarily.
"""


# ---------------------------------------------------------------------------
# Tool registry factory
# ---------------------------------------------------------------------------

def get_tool_registry(
    db: AsyncSession,
    agent_run_id: uuid.UUID,
    message_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Build and return the tool registry for a single agent run.

    Each entry maps a tool name to an **async callable** with signature::

        async (args: dict) -> dict

    The returned dict wraps results in ``{ok, tool_name, data, error?}``
    automatically — callers do **not** need to add that wrapper.

    The tools in ``_STUB_TOOLS`` are pre-populated with a stub that always
    returns ``{ok: False, error: 'tool_not_enabled'}``.

    The real tool implementations live in ``app.agent.tools`` and are imported
    lazily here to avoid circular imports.  If that package is not yet
    present (e.g. during unit tests), ``ImportError`` is caught and the tool
    falls back to a stub so the loop can still run in ``dry_run`` mode.

    Args:
        db:           Active ``AsyncSession`` for DB writes performed by tools.
        agent_run_id: UUID of the current ``AgentRun`` row.
        message_id:   UUID of the email ``Message`` being processed.

    Returns:
        ``dict[str, async callable]``
    """

    # --- stub factory --------------------------------------------------
    def _make_stub(name: str):
        async def _stub(args: dict) -> dict:
            return {"ok": False, "tool_name": name, "error": "tool_not_enabled"}
        return _stub

    registry: dict[str, Any] = {t: _make_stub(t) for t in _STUB_TOOLS}

    # --- real tools (lazy import) ---------------------------------------
    try:
        from app.agent.tools import (  # type: ignore[import]
            search_knowledge_base,
            get_thread_history,
            draft_reply,
            escalate_to_human,
            create_internal_ticket,
            flag_for_legal,
        )

        async def _search_knowledge_base(args: dict) -> dict:
            return await search_knowledge_base(
                query=args.get("query", ""),
                max_results=int(args.get("max_results", 3)),
                db=db,
                agent_run_id=agent_run_id,
                message_id=message_id,
            )

        async def _get_thread_history(args: dict) -> dict:
            return await get_thread_history(
                sender_email=args.get("sender_email", ""),
                limit=int(args.get("limit", 10)),
                db=db,
            )

        async def _draft_reply(args: dict) -> dict:
            return await draft_reply(
                message_id=uuid.UUID(str(args.get("message_id", message_id))),
                tone=args.get("tone", "empathetic"),
                policy_refs=args.get("policy_refs", []),
                db=db,
                agent_run_id=agent_run_id,
            )

        async def _escalate_to_human(args: dict) -> dict:
            return await escalate_to_human(
                message_id=uuid.UUID(str(args.get("message_id", message_id))),
                reason=args.get("reason", ""),
                priority=args.get("priority", "high"),
                queue=args.get("queue", "support_operations"),
                db=db,
                agent_run_id=agent_run_id,
            )

        async def _create_internal_ticket(args: dict) -> dict:
            return await create_internal_ticket(
                source_message_id=uuid.UUID(str(args.get("source_message_id", message_id))),
                title=args.get("title", ""),
                body=args.get("body", ""),
                assignee_queue=args.get("assignee_queue", "support_operations"),
                db=db,
                agent_run_id=agent_run_id,
            )

        async def _flag_for_legal(args: dict) -> dict:
            return await flag_for_legal(
                message_id=uuid.UUID(str(args.get("message_id", message_id))),
                issue_type=args.get("issue_type", "regulatory"),
                summary=args.get("summary", ""),
                db=db,
                agent_run_id=agent_run_id,
            )

        registry.update({
            "search_knowledge_base": _search_knowledge_base,
            "get_thread_history": _get_thread_history,
            "draft_reply": _draft_reply,
            "escalate_to_human": _escalate_to_human,
            "create_internal_ticket": _create_internal_ticket,
            "flag_for_legal": _flag_for_legal,
        })

    except ImportError as exc:
        logger.warning(
            "app.agent.tools not yet available — all active tools will stub: %s", exc
        )
        # Fall back: register stub callables for every known active tool
        for name in (
            "search_knowledge_base",
            "get_thread_history",
            "draft_reply",
            "escalate_to_human",
            "create_internal_ticket",
            "flag_for_legal",
        ):
            if name not in registry:
                registry[name] = _make_stub(name)

    return registry


# ---------------------------------------------------------------------------
# LLM interaction helpers
# ---------------------------------------------------------------------------

def _build_react_messages(
    urgency: str,
    category: str,
    subject: str,
    body: str,
    sender_email: str,
    message_id: uuid.UUID,
    trace: list[dict],
) -> list[dict]:
    """
    Construct the OpenRouter chat messages list for one ReAct iteration.

    The system prompt describes all tools.  The user message contains the
    email payload plus the running trace so the LLM has full context.

    Args:
        urgency:      Urgency level from upstream classification.
        category:     Category from upstream classification.
        subject:      Email subject line.
        body:         Sanitized email body (will be truncated to 3 000 chars).
        sender_email: Sender's email address.
        message_id:   UUID of the email message row.
        trace:        Current trace list (may be empty on first iteration).

    Returns:
        List of ``{"role": ..., "content": ...}`` dicts for the LLM.
    """
    system_content = _REACT_SYSTEM_PROMPT.format(max_tool_calls=MAX_TOOL_CALLS)

    # Truncate body so we don't blow the context window
    body_preview = body[:3000]
    if len(body) > 3000:
        body_preview += "\n...[body truncated]..."

    # Serialise trace for the LLM
    trace_str = json.dumps(trace, indent=2) if trace else "[]"

    user_content = (
        f"EMAIL TO TRIAGE\n"
        f"---------------\n"
        f"message_id : {message_id}\n"
        f"sender     : {sender_email}\n"
        f"urgency    : {urgency}\n"
        f"category   : {category}\n"
        f"subject    : {subject}\n"
        f"body       :\n{body_preview}\n\n"
        f"CURRENT TRACE (steps taken so far):\n{trace_str}\n\n"
        f"What is your next action? Respond with strict JSON only."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_llm_decision(raw: str) -> dict:
    """
    Extract a JSON decision object from a raw LLM response string.

    Strips markdown code fences if present, then parses JSON.  Returns a dict
    with at minimum ``{"action": str, "rationale": str}`` and optionally
    ``{"args": dict}``.

    Args:
        raw: Raw string from the LLM.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If the response cannot be parsed as valid JSON or is missing
                    required keys.
    """
    cleaned = raw.strip()

    # Strip optional markdown fences (```json ... ``` or ``` ... ```)
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned non-JSON response: {exc}\nRaw: {raw!r}"
        ) from exc

    if "action" not in parsed:
        raise ValueError(f"LLM response missing 'action' key: {parsed!r}")
    if "rationale" not in parsed:
        # Be lenient — inject an empty rationale rather than crashing
        parsed["rationale"] = ""

    return parsed


# ---------------------------------------------------------------------------
# Tool execution wrapper
# ---------------------------------------------------------------------------

async def _execute_tool(
    tool_name: str,
    args: dict,
    registry: dict[str, Any],
    mode: str,
    urgency: str,
) -> dict:
    """
    Look up *tool_name* in *registry*, apply safety invariants, and call it.

    Safety invariants enforced here (in addition to the LLM prompt):
    - ``urgency == 'critical'`` and ``tool_name == 'draft_reply'`` → blocked.
    - Unknown tool names return a structured error rather than raising.

    In ``dry_run`` mode, all write-side tools (draft_reply, escalate_to_human,
    create_internal_ticket, flag_for_legal) are intercepted and their result is
    replaced with a ``{ok: True, dry_run: True, ...}`` sentinel so the trace
    still records the *intent* of the action without any DB side-effects.

    Args:
        tool_name: Name of the tool to call.
        args:      Parsed argument dict from the LLM decision.
        registry:  Tool registry returned by :func:`get_tool_registry`.
        mode:      ``'live'`` or ``'dry_run'``.
        urgency:   Urgency level (``'critical'`` blocks ``draft_reply``).

    Returns:
        Wrapped result: ``{ok, tool_name, data?, error?}``
    """
    _WRITE_TOOLS = frozenset(
        {"draft_reply", "escalate_to_human", "create_internal_ticket", "flag_for_legal"}
    )

    # --- Safety: block draft_reply for critical emails ------------------
    if urgency == "critical" and tool_name == "draft_reply":
        logger.warning(
            "SAFETY BLOCK: draft_reply called with urgency=critical — rejected."
        )
        return {
            "ok": False,
            "tool_name": tool_name,
            "error": (
                "draft_reply is forbidden for urgency=critical. "
                "You MUST escalate to the security queue instead."
            ),
        }

    # --- Unknown tool ---------------------------------------------------
    if tool_name not in registry:
        logger.warning("Unknown tool requested by LLM: %r", tool_name)
        return {
            "ok": False,
            "tool_name": tool_name,
            "error": f"Unknown tool: {tool_name!r}",
        }

    # --- dry_run intercept for write-side tools -------------------------
    if mode == "dry_run" and tool_name in _WRITE_TOOLS:
        logger.info("dry_run: intercepting write tool %r — skipping DB write", tool_name)
        return {
            "ok": True,
            "tool_name": tool_name,
            "dry_run": True,
            "data": {
                "message": (
                    f"[DRY RUN] Tool '{tool_name}' would have been called with: {json.dumps(args)}"
                )
            },
        }

    # --- Real call ------------------------------------------------------
    try:
        fn = registry[tool_name]
        data = await fn(args)

        # If the tool itself returned an error envelope pass it through
        if isinstance(data, dict) and "ok" in data:
            return data

        return {"ok": True, "tool_name": tool_name, "data": data}

    except Exception as exc:
        logger.error(
            "Tool %r raised an exception: %s", tool_name, exc, exc_info=True
        )
        return {
            "ok": False,
            "tool_name": tool_name,
            "error": f"Tool execution error: {exc}",
        }


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

async def run_agent(
    message_id: uuid.UUID,
    classification_id: uuid.UUID | None,
    urgency: str,
    category: str,
    subject: str,
    body: str,
    sender_email: str,
    db: AsyncSession,
    mode: str = "live",
) -> AgentRun:
    """
    Execute the AURA ReAct agent loop for a single email message.

    The loop drives an LLM through a series of Reason→Act→Observe cycles until
    the LLM signals ``{"action": "done"}`` or the hard cap of ``MAX_TOOL_CALLS``
    is reached.

    Persistence contract
    --------------------
    * An ``AgentRun`` row is created at the start with ``outcome='running'``
      (not a real outcome value — set to something transient) and committed
      incrementally via ``flush()`` after each tool call.
    * ``outcome`` is set to ``'completed'``, ``'failed'``, or ``'dry_run'``
      at the end and committed with a single ``db.commit()``.
    * In ``dry_run`` mode: ``AgentRun`` is written but NO Tickets, Drafts,
      Escalations, or LegalFlags are created.

    Args:
        message_id:        UUID of the ``Message`` row being triaged.
        classification_id: UUID of the upstream ``Classification`` row, if any.
        urgency:           One of ``'low'``, ``'medium'``, ``'high'``, ``'critical'``.
        category:          Category string from classification pipeline.
        subject:           Email subject line.
        body:              Sanitized email body text.
        sender_email:      Sender's email address.
        db:                Active ``AsyncSession`` (caller-managed lifecycle).
        mode:              ``'live'`` (default) or ``'dry_run'``.

    Returns:
        The persisted and committed ``AgentRun`` ORM object.

    Raises:
        Does **not** raise — all errors are caught and recorded in the
        ``AgentRun.trace`` with ``outcome='failed'``.
    """
    logger.info(
        "run_agent start: message_id=%s urgency=%s category=%s mode=%s",
        message_id, urgency, category, mode,
    )

    # ------------------------------------------------------------------
    # 1. Create the AgentRun row
    # ------------------------------------------------------------------
    agent_run = AgentRun(
        id=uuid.uuid4(),
        message_id=message_id,
        classification_id=classification_id,
        mode=mode,
        tool_calls_count=0,
        trace=[],
        outcome="completed",  # will be overwritten on failure or dry_run
    )
    db.add(agent_run)
    await db.flush()  # get the id into the DB without committing

    logger.debug("AgentRun created: id=%s", agent_run.id)

    # ------------------------------------------------------------------
    # 2. Build tool registry
    # ------------------------------------------------------------------
    registry = get_tool_registry(
        db=db,
        agent_run_id=agent_run.id,
        message_id=message_id,
    )

    # ------------------------------------------------------------------
    # 3. Safety pre-check: critical urgency → force escalate
    # ------------------------------------------------------------------
    #  We inject a synthetic first trace step so the LLM sees the constraint
    #  has already been applied, preventing it from trying to draft a reply.
    if urgency == "critical":
        logger.warning(
            "urgency=critical detected for message_id=%s — "
            "will enforce security escalation.",
            message_id,
        )

    # ------------------------------------------------------------------
    # 4. ReAct loop
    # ------------------------------------------------------------------
    trace: list[dict] = []
    adapter = get_llm_adapter()
    outcome: str = "completed"

    try:
        for step in range(1, MAX_TOOL_CALLS + 2):
            # Build prompt
            messages = _build_react_messages(
                urgency=urgency,
                category=category,
                subject=subject,
                body=body,
                sender_email=sender_email,
                message_id=message_id,
                trace=trace,
            )

            # Ask the LLM for the next decision
            logger.debug("ReAct iteration %d/%d — calling LLM", step, MAX_TOOL_CALLS)
            try:
                raw_response = await adapter._chat_completion(
                    messages=messages,
                    temperature=0.1,
                    max_tokens=512,
                )
            except LLMError as llm_exc:
                logger.error("LLM call failed on step %d: %s", step, llm_exc)
                trace.append({
                    "step": step,
                    "rationale": "LLM call failed — aborting loop.",
                    "action": "error",
                    "observation": {"ok": False, "error": str(llm_exc)},
                })
                outcome = "failed"
                break

            # Parse the LLM decision
            try:
                decision = _parse_llm_decision(raw_response)
            except ValueError as parse_exc:
                logger.error("Failed to parse LLM decision on step %d: %s", step, parse_exc)
                trace.append({
                    "step": step,
                    "rationale": "LLM returned unparseable response.",
                    "action": "error",
                    "observation": {"ok": False, "error": str(parse_exc)},
                })
                outcome = "failed"
                break

            action: str = decision["action"]
            rationale: str = decision.get("rationale", "")
            args: dict = decision.get("args", {})

            # --- Done signal -------------------------------------------
            if action == "done":
                trace.append({
                    "step": step,
                    "rationale": rationale,
                    "action": "done",
                    "observation": None,
                })
                logger.info(
                    "Agent signalled done at step %d for message_id=%s",
                    step, message_id,
                )
                break

            # --- Tool call limit exceeded ------------------------------
            if agent_run.tool_calls_count >= MAX_TOOL_CALLS:
                logger.warning(
                    "Tool call limit (%d) reached for message_id=%s — stopping loop.",
                    MAX_TOOL_CALLS, message_id,
                )
                trace.append({
                    "step": step,
                    "rationale": (
                        f"Stopped: tool call limit of {MAX_TOOL_CALLS} reached."
                    ),
                    "action": "limit_reached",
                    "observation": None,
                })
                break

            # --- Execute the tool -------------------------------------
            logger.info(
                "Step %d: executing tool=%r args=%r (mode=%s)",
                step, action, args, mode,
            )
            observation = await _execute_tool(
                tool_name=action,
                args=args,
                registry=registry,
                mode=mode,
                urgency=urgency,
            )

            # Append trace step (no private CoT)
            trace.append({
                "step": step,
                "rationale": rationale,
                "action": action,
                "observation": observation,
            })

            # Update AgentRun incrementally after each real tool call
            agent_run.tool_calls_count += 1
            agent_run.trace = list(trace)  # replace with fresh copy for JSONB
            db.add(agent_run)
            await db.flush()

            logger.debug(
                "Tool call %d/%d complete: tool=%r ok=%s",
                agent_run.tool_calls_count, MAX_TOOL_CALLS,
                action, observation.get("ok"),
            )

    except Exception as exc:
        logger.error(
            "Unexpected error in run_agent for message_id=%s: %s",
            message_id, exc, exc_info=True,
        )
        trace.append({
            "step": len(trace) + 1,
            "rationale": "Unexpected agent loop error.",
            "action": "error",
            "observation": {"ok": False, "error": str(exc)},
        })
        outcome = "failed"

    # ------------------------------------------------------------------
    # 5. Finalise AgentRun
    # ------------------------------------------------------------------
    if mode == "dry_run":
        outcome = "dry_run"

    agent_run.trace = trace
    agent_run.outcome = outcome
    db.add(agent_run)
    await db.commit()

    logger.info(
        "run_agent complete: message_id=%s agent_run_id=%s outcome=%s tool_calls=%d",
        message_id, agent_run.id, outcome, agent_run.tool_calls_count,
    )

    return agent_run
