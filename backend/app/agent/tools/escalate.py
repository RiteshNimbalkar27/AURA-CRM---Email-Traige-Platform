"""
AURA Agent Tool — escalate_to_human
=====================================
Routes a message to a human operator queue by creating an Escalation record.

Valid queues (per PLAN.md):
    security | legal_compliance | reputation_retention | support_operations

Valid priorities:
    low | medium | high | critical

In dry_run mode the Escalation row is NOT written to the database and a
mock ``escalation_id`` is returned so the agent trace can be fully recorded.
"""
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Escalation

logger = logging.getLogger(__name__)

_VALID_PRIORITIES = frozenset({"low", "medium", "high", "critical"})
_VALID_QUEUES = frozenset(
    {"security", "legal_compliance", "reputation_retention", "support_operations"}
)
_MOCK_ESCALATION_ID = "00000000-0000-0000-0000-000000000001"


def make_escalate_to_human(
    db: AsyncSession,
    agent_run_id: uuid.UUID,
    message_id: uuid.UUID,  # noqa: ARG001 — resolved via message_id_str arg
    dry_run: bool = False,
):
    """
    Factory that returns the ``escalate_to_human`` async callable
    with all context bound via closure.

    Args:
        db:           Active SQLAlchemy AsyncSession.
        agent_run_id: UUID of the current AgentRun row.
        message_id:   UUID of the email message being processed (for reference).
        dry_run:      When True the Escalation row is NOT written to the DB.

    Returns:
        An async callable suitable for inclusion in the tool registry.
    """

    async def escalate_to_human(
        message_id_str: str,
        reason: str,
        priority: str,
        queue: str,
    ) -> dict[str, Any]:
        """
        Escalate a message to a human operator queue.

        Args:
            message_id_str: UUID string of the source Message being escalated.
            reason:         Free-text description of why escalation is needed.
                            Stored as the escalation ``brief``.
            priority:       One of ``low`` | ``medium`` | ``high`` | ``critical``.
            queue:          Destination queue — one of:
                            ``security`` | ``legal_compliance`` |
                            ``reputation_retention`` | ``support_operations``.

        Returns:
            On success::

                {
                    "ok": True,
                    "tool_name": "escalate_to_human",
                    "data": {
                        "escalation_id": "<uuid | mock-uuid>",
                        "queue":         "<queue>",
                        "priority":      "<priority>",
                        "status":        "open",
                        "brief":         "<reason>"
                    }
                }

            On validation failure or DB error::

                {"ok": False, "tool_name": "escalate_to_human", "error": "<message>"}
        """
        tool_name = "escalate_to_human"
        try:
            # ------------------------------------------------------------------
            # Validate inputs
            # ------------------------------------------------------------------
            if priority not in _VALID_PRIORITIES:
                return {
                    "ok": False,
                    "tool_name": tool_name,
                    "error": (
                        f"Invalid priority '{priority}'. "
                        f"Must be one of: {sorted(_VALID_PRIORITIES)}"
                    ),
                }

            if queue not in _VALID_QUEUES:
                return {
                    "ok": False,
                    "tool_name": tool_name,
                    "error": (
                        f"Invalid queue '{queue}'. "
                        f"Must be one of: {sorted(_VALID_QUEUES)}"
                    ),
                }

            source_msg_uuid = uuid.UUID(message_id_str)

            # ------------------------------------------------------------------
            # Persist Escalation (skipped in dry_run)
            # ------------------------------------------------------------------
            if dry_run:
                escalation_id = _MOCK_ESCALATION_ID
                logger.info(
                    "[dry_run] escalate_to_human: skipping DB write, "
                    "mock escalation_id=%s queue=%s priority=%s",
                    escalation_id,
                    queue,
                    priority,
                )
            else:
                escalation = Escalation(
                    source_message_id=source_msg_uuid,
                    agent_run_id=agent_run_id,
                    queue=queue,
                    priority=priority,
                    brief=reason,
                    status="open",
                )
                db.add(escalation)
                await db.flush()
                escalation_id = str(escalation.id)
                logger.info(
                    "escalate_to_human: persisted Escalation id=%s "
                    "queue=%s priority=%s message_id=%s",
                    escalation_id,
                    queue,
                    priority,
                    message_id_str,
                )

            return {
                "ok": True,
                "tool_name": tool_name,
                "data": {
                    "escalation_id": escalation_id,
                    "queue": queue,
                    "priority": priority,
                    "status": "open",
                    "brief": reason,
                },
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("escalate_to_human error: %s", exc, exc_info=True)
            return {"ok": False, "tool_name": tool_name, "error": str(exc)}

    return escalate_to_human
