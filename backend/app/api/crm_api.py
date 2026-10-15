"""
AURA CRM & Analytics API
=========================
Endpoints for contact management, sentiment/category analytics, at-risk
account detection, market-intelligence enrichment, and audit-log lookup.

All endpoints require a valid JWT (via ``get_current_user``).
Write operations (PATCH) additionally require the ``supervisor`` role.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import cast, Date, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import AgentRun, Draft, Escalation, LegalFlag, Ticket
from app.models.audit import AuditLog
from app.models.crm import Account, Contact
from app.models.email import Thread
from app.models.intelligence import Classification

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_supervisor(current_user: Any) -> None:
    """Raise HTTP 403 if the authenticated user is not a supervisor.

    Args:
        current_user: The authenticated user object from ``get_current_user``.

    Raises:
        HTTPException: 403 Forbidden if ``current_user.role != 'supervisor'``.
    """
    if current_user.role != "supervisor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "supervisor_required",
                "message": "Supervisor role is required for this operation.",
                "details": {"required_role": "supervisor", "current_role": current_user.role},
            },
        )


def _cutoff_utc(days: int) -> datetime:
    """Return a UTC-aware datetime *days* before now.

    Args:
        days: Number of days to look back.

    Returns:
        UTC-aware ``datetime`` representing the cutoff point.
    """
    return datetime.now(timezone.utc) - timedelta(days=days)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ContactStatusUpdate(BaseModel):
    """Request body for PATCH /contacts/{email}/status."""

    status: Literal["active", "at_risk", "churned"] = Field(
        ..., description="New operational status for the contact."
    )


# ===========================================================================
# GET /contacts/{email}
# ===========================================================================


@router.get(
    "/contacts/{email}",
    summary="Fetch contact profile",
    description=(
        "Returns a contact's profile, linked account, thread count, "
        "and the last 5 classification records."
    ),
    tags=["CRM & Analytics"],
)
async def get_contact(
    email: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    GET /api/contacts/{email}

    Fetch a contact by email address including account details, open-thread
    count, and the five most recent classification records.

    Args:
        email: Contact email address (URL path parameter).
        db: Async database session.
        current_user: Authenticated user (any role).

    Returns:
        Dict with ``contact_id``, ``email``, ``name``, ``account_name``,
        ``operational_status``, ``thread_count``, and ``recent_classifications``.

    Raises:
        HTTPException: 404 if no contact with the given email exists.
    """
    result = await db.execute(
        select(Contact)
        .where(Contact.email == email)
        .options(selectinload(Contact.account))
    )
    contact: Contact | None = result.scalar_one_or_none()

    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "contact_not_found",
                "message": f"No contact found with email '{email}'.",
                "details": {"email": email},
            },
        )

    # Thread count
    thread_count_row = await db.execute(
        select(func.count()).select_from(Thread).where(Thread.contact_id == contact.id)
    )
    thread_count: int = thread_count_row.scalar_one()

    # Last 5 classifications
    cls_rows = await db.execute(
        select(Classification)
        .where(Classification.contact_id == contact.id)
        .order_by(desc(Classification.created_at))
        .limit(5)
    )
    recent_cls = cls_rows.scalars().all()

    return {
        "contact_id": str(contact.id),
        "email": contact.email,
        "name": None,                  # Contact model has no name field; reserved for future
        "account_name": contact.account.name if contact.account else None,
        "operational_status": contact.operational_status,
        "thread_count": thread_count,
        "recent_classifications": [
            {
                "classification_id": str(c.id),
                "category": c.category,
                "urgency": c.urgency,
                "sentiment_score": c.sentiment_score,
                "confidence": c.confidence,
                "classified_at": c.created_at.isoformat(),
            }
            for c in recent_cls
        ],
    }


# ===========================================================================
# PATCH /contacts/{email}/status
# ===========================================================================


@router.patch(
    "/contacts/{email}/status",
    summary="Update contact operational status",
    description=(
        "Updates the ``operational_status`` field of a contact. "
        "Requires **supervisor** role."
    ),
    tags=["CRM & Analytics"],
)
async def update_contact_status(
    email: str,
    body: ContactStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    PATCH /api/contacts/{email}/status

    Update ``contact.operational_status`` to one of ``active | at_risk | churned``.
    Only users with the ``supervisor`` role may call this endpoint.

    Args:
        email: Contact email address (URL path parameter).
        body: JSON body containing the new ``status`` value.
        db: Async database session.
        current_user: Authenticated user — must be ``supervisor``.

    Returns:
        Updated contact fields.

    Raises:
        HTTPException: 403 if not supervisor; 404 if contact not found.
    """
    _require_supervisor(current_user)

    result = await db.execute(select(Contact).where(Contact.email == email))
    contact: Contact | None = result.scalar_one_or_none()

    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "contact_not_found",
                "message": f"No contact found with email '{email}'.",
                "details": {"email": email},
            },
        )

    old_status = contact.operational_status
    contact.operational_status = body.status
    contact.updated_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info(
        "Contact %s status updated from '%s' → '%s' by user %s",
        email, old_status, body.status, current_user.email,
    )

    return {
        "contact_id": str(contact.id),
        "email": contact.email,
        "operational_status": contact.operational_status,
        "updated_at": contact.updated_at.isoformat(),
        "updated_by": current_user.email,
    }


# ===========================================================================
# GET /analytics/sentiment-trend
# ===========================================================================


@router.get(
    "/analytics/sentiment-trend",
    summary="Daily average sentiment trend",
    description=(
        "Returns the daily average sentiment score for the last N days. "
        "Optionally filter by a specific contact email."
    ),
    tags=["CRM & Analytics"],
)
async def get_sentiment_trend(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=365, description="Number of days to look back")] = 30,
    contact_email: Annotated[
        str | None,
        Query(description="Optional contact email to filter by"),
    ] = None,
) -> dict[str, Any]:
    """
    GET /api/analytics/sentiment-trend

    Aggregate ``sentiment_score`` grouped by calendar date for the last
    *days* days.  Optionally scoped to a single contact.

    Args:
        db: Async database session.
        current_user: Authenticated user (any role).
        days: Lookback window in days (1–365, default 30).
        contact_email: If supplied, restrict results to that contact's
            classifications.

    Returns:
        Dict with ``days``, ``contact_email``, and a list of ``{date, avg_sentiment, count}``
        records ordered chronologically.
    """
    cutoff = _cutoff_utc(days)

    stmt = (
        select(
            cast(Classification.created_at, Date).label("date"),
            func.avg(Classification.sentiment_score).label("avg_sentiment"),
            func.count().label("count"),
        )
        .where(Classification.created_at >= cutoff)
        .group_by(cast(Classification.created_at, Date))
        .order_by(cast(Classification.created_at, Date))
    )

    if contact_email is not None:
        contact_result = await db.execute(
            select(Contact.id).where(Contact.email == contact_email)
        )
        contact_id: uuid.UUID | None = contact_result.scalar_one_or_none()
        if contact_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "contact_not_found",
                    "message": f"No contact found with email '{contact_email}'.",
                    "details": {"email": contact_email},
                },
            )
        stmt = stmt.where(Classification.contact_id == contact_id)

    rows = (await db.execute(stmt)).fetchall()

    return {
        "days": days,
        "contact_email": contact_email,
        "trend": [
            {
                "date": str(row.date),
                "avg_sentiment": round(float(row.avg_sentiment), 4),
                "count": row.count,
            }
            for row in rows
        ],
    }


# ===========================================================================
# GET /analytics/category-breakdown
# ===========================================================================


@router.get(
    "/analytics/category-breakdown",
    summary="Classification category distribution",
    description="Returns the count per category for the last N days.",
    tags=["CRM & Analytics"],
)
async def get_category_breakdown(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=365, description="Number of days to look back")] = 30,
) -> dict[str, Any]:
    """
    GET /api/analytics/category-breakdown

    Count classifications per category within the last *days* days, ordered
    by count descending.

    Args:
        db: Async database session.
        current_user: Authenticated user (any role).
        days: Lookback window in days (1–365, default 30).

    Returns:
        Dict with ``days`` and a list of ``{category, count}`` records.
    """
    cutoff = _cutoff_utc(days)

    rows = (await db.execute(
        select(
            Classification.category,
            func.count().label("count"),
        )
        .where(Classification.created_at >= cutoff)
        .group_by(Classification.category)
        .order_by(desc(func.count()))
    )).fetchall()

    return {
        "days": days,
        "breakdown": [
            {"category": row.category, "count": row.count}
            for row in rows
        ],
    }


# ===========================================================================
# GET /analytics/at-risk-accounts
# ===========================================================================


@router.get(
    "/analytics/at-risk-accounts",
    summary="At-risk account summary",
    description=(
        "Returns accounts that have at least one contact with "
        "``operational_status = 'at_risk'``, together with their most "
        "recent sentiment score."
    ),
    tags=["CRM & Analytics"],
)
async def get_at_risk_accounts(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    GET /api/analytics/at-risk-accounts

    Aggregates at-risk contacts per account and appends the latest
    ``sentiment_score`` for each contact (if classifications exist).

    Args:
        db: Async database session.
        current_user: Authenticated user (any role).

    Returns:
        Dict with a list of account records, each containing
        ``{account_id, account_name, at_risk_count, contacts}``.
    """
    # Load all at-risk contacts with their accounts eagerly
    at_risk_result = await db.execute(
        select(Contact)
        .where(Contact.operational_status == "at_risk")
        .options(selectinload(Contact.account))
        .order_by(Contact.account_id)
    )
    at_risk_contacts: list[Contact] = list(at_risk_result.scalars().all())

    if not at_risk_contacts:
        return {"at_risk_accounts": []}

    # Fetch latest sentiment per contact in one query
    contact_ids = [c.id for c in at_risk_contacts]
    latest_cls_subq = (
        select(
            Classification.contact_id,
            func.max(Classification.created_at).label("max_at"),
        )
        .where(Classification.contact_id.in_(contact_ids))
        .group_by(Classification.contact_id)
        .subquery()
    )
    sentiment_rows = (await db.execute(
        select(Classification.contact_id, Classification.sentiment_score)
        .join(
            latest_cls_subq,
            (Classification.contact_id == latest_cls_subq.c.contact_id)
            & (Classification.created_at == latest_cls_subq.c.max_at),
        )
    )).fetchall()
    last_sentiment: dict[uuid.UUID, float] = {
        row.contact_id: row.sentiment_score for row in sentiment_rows
    }

    # Group contacts by account
    accounts_map: dict[str, dict[str, Any]] = {}
    no_account_key = "__no_account__"

    for contact in at_risk_contacts:
        if contact.account_id is not None and contact.account is not None:
            acct_key = str(contact.account_id)
            if acct_key not in accounts_map:
                accounts_map[acct_key] = {
                    "account_id": acct_key,
                    "account_name": contact.account.name,
                    "at_risk_count": 0,
                    "contacts": [],
                }
            bucket = accounts_map[acct_key]
        else:
            if no_account_key not in accounts_map:
                accounts_map[no_account_key] = {
                    "account_id": None,
                    "account_name": None,
                    "at_risk_count": 0,
                    "contacts": [],
                }
            bucket = accounts_map[no_account_key]

        bucket["at_risk_count"] += 1
        bucket["contacts"].append({
            "contact_id": str(contact.id),
            "email": contact.email,
            "last_sentiment": last_sentiment.get(contact.id),
        })

    return {
        "at_risk_accounts": sorted(
            accounts_map.values(),
            key=lambda a: a["at_risk_count"],
            reverse=True,
        )
    }


# ===========================================================================
# GET /market-intelligence
# ===========================================================================


@router.get(
    "/market-intelligence",
    summary="Retrieve cached/fresh market intelligence",
    description=(
        "Triggers web enrichment for either the configured review URL or "
        "competitor-pricing URL and returns the cached or freshly fetched "
        "result.  ``?url=review`` maps to ``ENRICHMENT_REVIEW_URL``; "
        "``?url=competitor`` maps to ``ENRICHMENT_COMPETITOR_URL``."
    ),
    tags=["CRM & Analytics"],
)
async def get_market_intelligence(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
    url: Annotated[
        Literal["review", "competitor"],
        Query(description="Which URL to enrich: 'review' or 'competitor'"),
    ] = "review",
) -> dict[str, Any]:
    """
    GET /api/market-intelligence

    Resolves the short alias (``review`` | ``competitor``) to the full URL
    declared in config, then delegates to
    :func:`app.services.web_enrichment.get_or_fetch_market_intel`.

    Args:
        db: Async database session.
        current_user: Authenticated user (any role).
        url: Alias — ``'review'`` or ``'competitor'``.

    Returns:
        Enrichment payload: ``{url, fetched_at, summary, raw_text, status, stale, error}``.
    """
    try:
        from app.services.web_enrichment import get_or_fetch_market_intel
    except ImportError as exc:
        logger.exception("web_enrichment module unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "enrichment_unavailable",
                "message": "Web enrichment service is not available.",
                "details": {"error": str(exc)},
            },
        )

    settings = get_settings()
    target_url = (
        settings.enrichment_review_url
        if url == "review"
        else settings.enrichment_competitor_url
    )

    try:
        result = await get_or_fetch_market_intel(db=db, url=target_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "enrichment_url_not_allowed",
                "message": str(exc),
                "details": {"url": target_url},
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Market intel fetch failed for %s: %s", target_url, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_code": "enrichment_fetch_error",
                "message": "Failed to fetch market intelligence data.",
                "details": {"error": str(exc)},
            },
        )

    return result


# ===========================================================================
# GET /audit/{entity_type}/{entity_id}
# ===========================================================================

_VALID_ENTITY_TYPES = frozenset(
    {"agent_run", "draft", "ticket", "escalation", "legal_flag"}
)


@router.get(
    "/audit/{entity_type}/{entity_id}",
    summary="Audit log lookup",
    description=(
        "Returns all audit log entries for a specific entity. "
        "``entity_type`` must be one of: "
        "``agent_run | draft | ticket | escalation | legal_flag``."
    ),
    tags=["CRM & Analytics"],
)
async def get_audit_log(
    entity_type: str,
    entity_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    GET /api/audit/{entity_type}/{entity_id}

    Looks up the ``audit_log`` table for all rows matching the given
    ``entity_type`` and ``entity_id`` UUID.

    Args:
        entity_type: One of ``agent_run | draft | ticket | escalation | legal_flag``.
        entity_id:   UUID of the entity to audit.
        db: Async database session.
        current_user: Authenticated user (any role).

    Returns:
        Dict with ``entity_type``, ``entity_id``, ``count``, and a list
        of audit ``entries``.

    Raises:
        HTTPException: 400 for an invalid entity_type or malformed UUID.
    """
    if entity_type not in _VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "invalid_entity_type",
                "message": (
                    f"Invalid entity_type '{entity_type}'. "
                    f"Must be one of: {sorted(_VALID_ENTITY_TYPES)}."
                ),
                "details": {"valid_types": sorted(_VALID_ENTITY_TYPES)},
            },
        )

    try:
        entity_uuid = uuid.UUID(entity_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "invalid_entity_id",
                "message": f"'{entity_id}' is not a valid UUID.",
                "details": {"entity_id": entity_id},
            },
        )

    rows = (await db.execute(
        select(AuditLog)
        .where(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_uuid,
        )
        .order_by(desc(AuditLog.created_at))
    )).scalars().all()

    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "count": len(rows),
        "entries": [
            {
                "audit_id": str(r.id),
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "actor_email": r.actor_email,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": str(r.entity_id),
                "change_metadata": r.change_metadata,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
