"""
AURA Agent Action API
=====================
Endpoints for triggering agent runs, inspecting results, editing/approving
drafts, and listing operational artifacts (tickets, escalations, legal flags).

All write operations require at least Operator or Supervisor role.
Read-only list views are accessible to any authenticated user.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import AgentRun, Draft, Escalation, LegalFlag, Ticket
from app.models.email import Message
from app.models.intelligence import Classification

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OPERATOR_ROLES = {"operator", "supervisor"}


def _require_operator_or_supervisor(current_user) -> None:
    """Raise 403 if the user is not an operator or supervisor."""
    if current_user.role not in _OPERATOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "insufficient_role",
                "message": "Operator or Supervisor role required.",
                "details": {"required_roles": list(_OPERATOR_ROLES), "current_role": current_user.role},
            },
        )


# ---------------------------------------------------------------------------
# Pydantic request / response schemas (local — no separate schemas file needed
# for these tightly scoped models)
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    """Optional body for POST /messages/{message_id}/agent-runs."""
    mode: Literal["live", "dry_run"] = Field(
        default="live",
        description="'live' persists all side-effects; 'dry_run' is read-only simulation.",
    )


class AgentRunResponse(BaseModel):
    agent_run_id: str
    mode: str
    outcome: str
    tool_calls_count: int
    trace: list | None


class AgentRunDetailResponse(BaseModel):
    agent_run_id: str
    message_id: str
    classification_id: str | None
    mode: str
    outcome: str
    tool_calls_count: int
    trace: list | None
    created_at: str


class DraftUpdateRequest(BaseModel):
    """Body for PATCH /drafts/{draft_id}."""
    body: str = Field(..., min_length=1, description="New draft body text.")


class DraftApproveResponse(BaseModel):
    draft_id: str
    status: str
    approved_by: str
    approved_at: str
    message: str


# ---------------------------------------------------------------------------
# POST /messages/{message_id}/agent-runs
# ---------------------------------------------------------------------------


@router.post(
    "/messages/{message_id}/agent-runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger an agent run on a message",
    description=(
        "Runs the AURA ReAct agent loop against the specified message. "
        "Requires Operator or Supervisor role. "
        "Use mode='dry_run' to simulate without persisting side-effects."
    ),
)
async def trigger_agent_run(
    message_id: str,
    body: AgentRunRequest = AgentRunRequest(),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[object, Depends(get_current_user)] = None,
) -> AgentRunResponse:
    """
    POST /api/messages/{message_id}/agent-runs

    Triggers the AURA agent ReAct loop for the given message.
    Returns a summary of the agent run including its persisted ID, outcome,
    tool call count and the redacted trace.
    """
    _require_operator_or_supervisor(current_user)

    # --- 1. Fetch message ---------------------------------------------------
    try:
        import uuid as _uuid
        msg_uuid = _uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "message_not_found",
                "message": f"Message '{message_id}' not found.",
                "details": {},
            },
        )

    result = await db.execute(select(Message).where(Message.id == msg_uuid))
    message: Message | None = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "message_not_found",
                "message": f"Message '{message_id}' not found.",
                "details": {},
            },
        )

    # --- 2. Fetch latest Classification (or use default) -------------------
    cls_result = await db.execute(
        select(Classification)
        .where(Classification.message_id == msg_uuid)
        .order_by(desc(Classification.created_at))
        .limit(1)
    )
    classification: Classification | None = cls_result.scalar_one_or_none()
    urgency = classification.urgency if classification else "medium"
    classification_id = classification.id if classification else None

    # --- 3. Call agent ------------------------------------------------------
    try:
        from app.agent.react_loop import run_agent  # type: ignore[import]

        agent_run: AgentRun = await run_agent(
            message=message,
            classification=classification,
            urgency=urgency,
            mode=body.mode,
            db=db,
            triggered_by=current_user,
        )
    except ImportError as exc:
        logger.exception("react_loop module not found: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "agent_module_unavailable",
                "message": "Agent module is not yet available.",
                "details": {"error": str(exc)},
            },
        )
    except Exception as exc:
        logger.exception("Agent run failed for message %s: %s", message_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "agent_run_failed",
                "message": "The agent encountered an unexpected error.",
                "details": {"error": str(exc)},
            },
        )

    return AgentRunResponse(
        agent_run_id=str(agent_run.id),
        mode=agent_run.mode,
        outcome=agent_run.outcome,
        tool_calls_count=agent_run.tool_calls_count,
        trace=agent_run.trace,
    )


# ---------------------------------------------------------------------------
# GET /agent-runs/{agent_run_id}
# ---------------------------------------------------------------------------


@router.get(
    "/agent-runs/{agent_run_id}",
    response_model=AgentRunDetailResponse,
    summary="Retrieve a specific agent run",
    description="Returns the full details of an agent run, including its trace and outcome.",
)
async def get_agent_run(
    agent_run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[object, Depends(get_current_user)] = None,
) -> AgentRunDetailResponse:
    """
    GET /api/agent-runs/{agent_run_id}

    Fetches full AgentRun details by ID.
    Requires Operator or Supervisor role.
    """
    _require_operator_or_supervisor(current_user)

    try:
        import uuid as _uuid
        run_uuid = _uuid.UUID(agent_run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "agent_run_not_found",
                "message": f"AgentRun '{agent_run_id}' not found.",
                "details": {},
            },
        )

    result = await db.execute(select(AgentRun).where(AgentRun.id == run_uuid))
    run: AgentRun | None = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "agent_run_not_found",
                "message": f"AgentRun '{agent_run_id}' not found.",
                "details": {},
            },
        )

    return AgentRunDetailResponse(
        agent_run_id=str(run.id),
        message_id=str(run.message_id),
        classification_id=str(run.classification_id) if run.classification_id else None,
        mode=run.mode,
        outcome=run.outcome,
        tool_calls_count=run.tool_calls_count,
        trace=run.trace,
        created_at=run.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# PATCH /drafts/{draft_id}
# ---------------------------------------------------------------------------


@router.patch(
    "/drafts/{draft_id}",
    summary="Edit a pending draft",
    description=(
        "Updates the body of a draft that is still in 'pending_approval' status. "
        "Editing is blocked once a draft has been approved or rejected."
    ),
)
async def update_draft(
    draft_id: str,
    body: DraftUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[object, Depends(get_current_user)] = None,
) -> dict:
    """
    PATCH /api/drafts/{draft_id}

    Allows an operator or supervisor to edit the body of a pending draft.
    Returns the full updated draft record.
    """
    _require_operator_or_supervisor(current_user)

    try:
        import uuid as _uuid
        draft_uuid = _uuid.UUID(draft_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "draft_not_found",
                "message": f"Draft '{draft_id}' not found.",
                "details": {},
            },
        )

    result = await db.execute(select(Draft).where(Draft.id == draft_uuid))
    draft: Draft | None = result.scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "draft_not_found",
                "message": f"Draft '{draft_id}' not found.",
                "details": {},
            },
        )

    if draft.status != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "draft_not_editable",
                "message": f"Draft cannot be edited in its current status: '{draft.status}'.",
                "details": {"current_status": draft.status, "required_status": "pending_approval"},
            },
        )

    draft.body = body.body
    draft.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return {
        "draft_id": str(draft.id),
        "message_id": str(draft.message_id),
        "agent_run_id": str(draft.agent_run_id) if draft.agent_run_id else None,
        "body": draft.body,
        "tone": draft.tone,
        "citations": draft.citations,
        "status": draft.status,
        "approved_by": str(draft.approved_by) if draft.approved_by else None,
        "approved_at": draft.approved_at.isoformat() if draft.approved_at else None,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /drafts/{draft_id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/drafts/{draft_id}/approve",
    response_model=DraftApproveResponse,
    summary="Approve a pending draft",
    description=(
        "Approves a draft reply for simulated send. "
        "SAFETY: Drafts linked to messages classified as 'critical' urgency are blocked "
        "from approval and must be escalated instead."
    ),
)
async def approve_draft(
    draft_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[object, Depends(get_current_user)] = None,
) -> DraftApproveResponse:
    """
    POST /api/drafts/{draft_id}/approve

    Sets draft.status = 'approved' and records the approver and timestamp.
    Blocks approval if the related message's latest classification has
    urgency == 'critical' (returns 403).
    """
    _require_operator_or_supervisor(current_user)

    try:
        import uuid as _uuid
        draft_uuid = _uuid.UUID(draft_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "draft_not_found",
                "message": f"Draft '{draft_id}' not found.",
                "details": {},
            },
        )

    result = await db.execute(select(Draft).where(Draft.id == draft_uuid))
    draft: Draft | None = result.scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "draft_not_found",
                "message": f"Draft '{draft_id}' not found.",
                "details": {},
            },
        )

    # --- Safety check: block approval for critical urgency messages ---------
    cls_result = await db.execute(
        select(Classification)
        .where(Classification.message_id == draft.message_id)
        .order_by(desc(Classification.created_at))
        .limit(1)
    )
    latest_classification: Classification | None = cls_result.scalar_one_or_none()
    if latest_classification is not None and latest_classification.urgency == "critical":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "critical_draft_blocked",
                "message": "Critical urgency drafts cannot be approved.",
                "details": {
                    "message_id": str(draft.message_id),
                    "urgency": "critical",
                    "classification_id": str(latest_classification.id),
                },
            },
        )

    # --- Approve ------------------------------------------------------------
    now = datetime.now(timezone.utc)
    draft.status = "approved"
    draft.approved_by = current_user.id
    draft.approved_at = now
    draft.updated_at = now
    await db.flush()

    return DraftApproveResponse(
        draft_id=str(draft.id),
        status="approved",
        approved_by=str(current_user.id),
        approved_at=now.isoformat(),
        message="Draft approved. Simulated send queued.",
    )


# ---------------------------------------------------------------------------
# GET /tickets
# ---------------------------------------------------------------------------


@router.get(
    "/tickets",
    summary="List tickets",
    description="Paginated list of support tickets with optional status and queue filters.",
)
async def list_tickets(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[object, Depends(get_current_user)] = None,
    status_filter: str | None = Query(default=None, alias="status", description="Filter by ticket status (e.g. 'open', 'in_progress', 'resolved')."),
    assignee_queue: str | None = Query(default=None, description="Filter by assignee queue name."),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of results to return."),
    offset: int = Query(default=0, ge=0, description="Number of results to skip for pagination."),
) -> dict:
    """
    GET /api/tickets

    Returns a paginated list of Ticket rows. Any authenticated user may call this.
    """
    query = select(Ticket).order_by(desc(Ticket.created_at))

    if status_filter is not None:
        query = query.where(Ticket.status == status_filter)
    if assignee_queue is not None:
        query = query.where(Ticket.assignee_queue == assignee_queue)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    tickets = result.scalars().all()

    return {
        "tickets": [
            {
                "id": str(t.id),
                "source_message_id": str(t.source_message_id),
                "agent_run_id": str(t.agent_run_id) if t.agent_run_id else None,
                "assignee_queue": t.assignee_queue,
                "title": t.title,
                "body": t.body,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
            }
            for t in tickets
        ],
        "limit": limit,
        "offset": offset,
        "count": len(tickets),
    }


# ---------------------------------------------------------------------------
# GET /escalations
# ---------------------------------------------------------------------------


@router.get(
    "/escalations",
    summary="List escalations",
    description="Paginated list of escalations with optional status, queue, and priority filters.",
)
async def list_escalations(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[object, Depends(get_current_user)] = None,
    status_filter: str | None = Query(default=None, alias="status", description="Filter by escalation status (e.g. 'open', 'in_progress', 'resolved')."),
    queue: str | None = Query(default=None, description="Filter by escalation queue."),
    priority: str | None = Query(default=None, description="Filter by priority level (e.g. 'low', 'medium', 'high', 'critical')."),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of results to return."),
    offset: int = Query(default=0, ge=0, description="Number of results to skip for pagination."),
) -> dict:
    """
    GET /api/escalations

    Returns a paginated list of Escalation rows. Any authenticated user may call this.
    """
    query = select(Escalation).order_by(desc(Escalation.created_at))

    if status_filter is not None:
        query = query.where(Escalation.status == status_filter)
    if queue is not None:
        query = query.where(Escalation.queue == queue)
    if priority is not None:
        query = query.where(Escalation.priority == priority)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    escalations = result.scalars().all()

    return {
        "escalations": [
            {
                "id": str(e.id),
                "source_message_id": str(e.source_message_id),
                "agent_run_id": str(e.agent_run_id) if e.agent_run_id else None,
                "queue": e.queue,
                "priority": e.priority,
                "brief": e.brief,
                "status": e.status,
                "resolved_by": str(e.resolved_by) if e.resolved_by else None,
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
                "resolution_notes": e.resolution_notes,
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
            }
            for e in escalations
        ],
        "limit": limit,
        "offset": offset,
        "count": len(escalations),
    }


# ---------------------------------------------------------------------------
# GET /legal-flags
# ---------------------------------------------------------------------------


@router.get(
    "/legal-flags",
    summary="List legal flags",
    description="Paginated list of legal flag records with optional legal_status and issue_type filters.",
)
async def list_legal_flags(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[object, Depends(get_current_user)] = None,
    legal_status: str | None = Query(default=None, description="Filter by legal status (e.g. 'open', 'under_review', 'resolved')."),
    issue_type: str | None = Query(default=None, description="Filter by issue type (e.g. 'dsar', 'gdpr', 'lawsuit')."),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of results to return."),
    offset: int = Query(default=0, ge=0, description="Number of results to skip for pagination."),
) -> dict:
    """
    GET /api/legal-flags

    Returns a paginated list of LegalFlag rows. Any authenticated user may call this.
    """
    query = select(LegalFlag).order_by(desc(LegalFlag.created_at))

    if legal_status is not None:
        query = query.where(LegalFlag.legal_status == legal_status)
    if issue_type is not None:
        query = query.where(LegalFlag.issue_type == issue_type)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    flags = result.scalars().all()

    return {
        "legal_flags": [
            {
                "id": str(f.id),
                "source_message_id": str(f.source_message_id),
                "agent_run_id": str(f.agent_run_id) if f.agent_run_id else None,
                "issue_type": f.issue_type,
                "summary": f.summary,
                "legal_status": f.legal_status,
                "resolved_by": str(f.resolved_by) if f.resolved_by else None,
                "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
                "created_at": f.created_at.isoformat(),
                "updated_at": f.updated_at.isoformat(),
            }
            for f in flags
        ],
        "limit": limit,
        "offset": offset,
        "count": len(flags),
    }
