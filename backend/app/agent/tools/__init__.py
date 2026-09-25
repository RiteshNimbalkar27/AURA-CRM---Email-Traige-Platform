"""
AURA Agent Tool Registry
========================
Central entry-point for all agent tools.  Call ``get_tool_registry()``
once per agent invocation to obtain a ``dict[str, Callable]`` where each
value is an async callable ready to be invoked by the agent loop.

Every tool callable is constructed via a factory function that closes over
the shared ``db``, ``agent_run_id``, ``message_id``, and ``dry_run``
values, plus any additional context (e.g. ``urgency`` for ``draft_reply``).

Tool registry
-------------
+---------------------------+--------------------------------------------+
| Tool name                 | Module                                     |
+===========================+============================================+
| search_knowledge_base     | app.agent.tools.search_kb                  |
| get_thread_history        | app.agent.tools.thread_history             |
| draft_reply               | app.agent.tools.draft_reply                |
| escalate_to_human         | app.agent.tools.escalate                   |
| create_internal_ticket    | app.agent.tools.ticket                     |
| flag_for_legal            | app.agent.tools.legal_flag                 |
+---------------------------+--------------------------------------------+

Contract stubs (``get_contact_profile``, ``check_account_status``) are
intentionally excluded from the registry until the MVP enables them.

Safety note
-----------
The ``urgency`` parameter is fetched by the caller from the DB-backed
Classification row and passed in here.  ``draft_reply`` closes over it so
that a critical-urgency block cannot be bypassed by the LLM passing a
different value.
"""
import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.draft_reply import make_draft_reply
from app.agent.tools.escalate import make_escalate_to_human
from app.agent.tools.legal_flag import make_flag_for_legal
from app.agent.tools.search_kb import make_search_knowledge_base
from app.agent.tools.thread_history import make_get_thread_history
from app.agent.tools.ticket import make_create_internal_ticket

__all__ = ["get_tool_registry"]


def get_tool_registry(
    db: AsyncSession,
    agent_run_id: uuid.UUID,
    message_id: uuid.UUID,
    dry_run: bool = False,
    urgency: str | None = None,
) -> dict[str, Callable]:
    """
    Build and return the complete agent tool registry for a single invocation.

    Each value in the returned dict is an *async* callable that accepts only
    the tool-specific arguments (db / agent_run_id / message_id / dry_run /
    urgency are already bound via closure).

    Args:
        db:           Active SQLAlchemy AsyncSession for the current request.
        agent_run_id: UUID of the AgentRun row created for this invocation.
        message_id:   UUID of the Message currently being triaged.
        dry_run:      When ``True`` all write operations are skipped and mock
                      IDs are returned.  Reads (KB search, thread history) still
                      execute.  Defaults to ``False``.
        urgency:      Urgency level from the message's latest Classification
                      (e.g. ``'critical'``, ``'high'``).  Passed to
                      ``draft_reply`` so it can enforce the critical-urgency
                      safety invariant.  Defaults to ``None`` (no block).

    Returns:
        A ``dict[str, Callable]`` mapping tool names to their async callables::

            {
                "search_knowledge_base":  <coroutine function>,
                "get_thread_history":     <coroutine function>,
                "draft_reply":            <coroutine function>,
                "escalate_to_human":      <coroutine function>,
                "create_internal_ticket": <coroutine function>,
                "flag_for_legal":         <coroutine function>,
            }

    Example::

        registry = get_tool_registry(
            db=db,
            agent_run_id=run.id,
            message_id=message.id,
            dry_run=False,
            urgency=classification.urgency,
        )
        result = await registry["search_knowledge_base"](query="refund policy")
    """
    return {
        "search_knowledge_base": make_search_knowledge_base(
            db=db,
            agent_run_id=agent_run_id,
            message_id=message_id,
            dry_run=dry_run,
        ),
        "get_thread_history": make_get_thread_history(
            db=db,
            agent_run_id=agent_run_id,
            message_id=message_id,
            dry_run=dry_run,
        ),
        "draft_reply": make_draft_reply(
            db=db,
            agent_run_id=agent_run_id,
            message_id=message_id,
            dry_run=dry_run,
            urgency=urgency,  # safety closure: critical urgency disables the tool
        ),
        "escalate_to_human": make_escalate_to_human(
            db=db,
            agent_run_id=agent_run_id,
            message_id=message_id,
            dry_run=dry_run,
        ),
        "create_internal_ticket": make_create_internal_ticket(
            db=db,
            agent_run_id=agent_run_id,
            message_id=message_id,
            dry_run=dry_run,
        ),
        "flag_for_legal": make_flag_for_legal(
            db=db,
            agent_run_id=agent_run_id,
            message_id=message_id,
            dry_run=dry_run,
        ),
    }
