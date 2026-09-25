"""
AURA Agent Tool — create_internal_ticket
==========================================
Creates an internal work-tracking ticket linked to a source customer message.

In dry_run mode the Ticket row is NOT written to the database and a mock
``ticket_id`` is returned so the agent trace can be fully recorded.
"""
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Ticket

logger = logging.getLogger(__name__)

_MOCK_TICKET_ID = "00000000-0000-0000-0000-000000000002"


def make_create_internal_ticket(
    db: AsyncSession,
    agent_run_id: uuid.UUID,
    message_id: uuid.UUID,  # noqa: ARG001 — resolved via source_message_id_str arg
    dry_run: bool = False,
):
    """
    Factory that returns the ``create_internal_ticket`` async callable
    with all context bound via closure.

    Args:
        db:           Active SQLAlchemy AsyncSession.
        agent_run_id: UUID of the current AgentRun row.
        message_id:   UUID of the email message being processed (for reference).
        dry_run:      When True the Ticket row is NOT written to the DB.

    Returns:
        An async callable suitable for inclusion in the tool registry.
    """

    async def create_internal_ticket(
        source_message_id_str: str,
        title: str,
        body: str,
        assignee_queue: str,
    ) -> dict[str, Any]:
        """
        Create an internal ticket for follow-up action.

        Args:
            source_message_id_str: UUID string of the source Message that
                                   prompted this ticket.
            title:                 Short, human-readable title for the ticket
                                   (max 500 chars enforced by the DB column).
            body:                  Full description or context for the ticket.
            assignee_queue:        Team/queue responsible for this ticket.

        Returns:
            On success::

                {
                    "ok": True,
                    "tool_name": "create_internal_ticket",
                    "data": {
                        "ticket_id":      "<uuid | mock-uuid>",
                        "assignee_queue": "<queue>",
                        "status":         "open"
                    }
                }

            On failure::

                {"ok": False, "tool_name": "create_internal_ticket", "error": "<message>"}
        """
        tool_name = "create_internal_ticket"
        try:
            source_msg_uuid = uuid.UUID(source_message_id_str)

            if dry_run:
                ticket_id = _MOCK_TICKET_ID
                logger.info(
                    "[dry_run] create_internal_ticket: skipping DB write, "
                    "mock ticket_id=%s assignee_queue=%s",
                    ticket_id,
                    assignee_queue,
                )
            else:
                ticket = Ticket(
                    source_message_id=source_msg_uuid,
                    agent_run_id=agent_run_id,
                    assignee_queue=assignee_queue,
                    title=title[:500],  # guard against over-long titles
                    body=body,
                    status="open",
                )
                db.add(ticket)
                await db.flush()
                ticket_id = str(ticket.id)
                logger.info(
                    "create_internal_ticket: persisted Ticket id=%s "
                    "assignee_queue=%s source_message_id=%s",
                    ticket_id,
                    assignee_queue,
                    source_message_id_str,
                )

            return {
                "ok": True,
                "tool_name": tool_name,
                "data": {
                    "ticket_id": ticket_id,
                    "assignee_queue": assignee_queue,
                    "status": "open",
                },
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("create_internal_ticket error: %s", exc, exc_info=True)
            return {"ok": False, "tool_name": tool_name, "error": str(exc)}

    return create_internal_ticket
