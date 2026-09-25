"""
AURA Agent Tool — flag_for_legal
==================================
Flags a message for legal team review by creating a LegalFlag record.

Valid issue types (per PLAN.md):
    dsar | gdpr | cease_and_desist | lawsuit | regulatory

In dry_run mode the LegalFlag row is NOT written to the database and a
mock ``legal_flag_id`` is returned so the agent trace can be fully recorded.

All legal flags are routed to the ``legal_compliance`` queue by default.
"""
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import LegalFlag

logger = logging.getLogger(__name__)

_VALID_ISSUE_TYPES = frozenset(
    {"dsar", "gdpr", "cease_and_desist", "lawsuit", "regulatory"}
)
_LEGAL_QUEUE = "legal_compliance"
_MOCK_LEGAL_FLAG_ID = "00000000-0000-0000-0000-000000000003"


def make_flag_for_legal(
    db: AsyncSession,
    agent_run_id: uuid.UUID,
    message_id: uuid.UUID,  # noqa: ARG001 — resolved via message_id_str arg
    dry_run: bool = False,
):
    """
    Factory that returns the ``flag_for_legal`` async callable
    with all context bound via closure.

    Args:
        db:           Active SQLAlchemy AsyncSession.
        agent_run_id: UUID of the current AgentRun row.
        message_id:   UUID of the email message being processed (for reference).
        dry_run:      When True the LegalFlag row is NOT written to the DB.

    Returns:
        An async callable suitable for inclusion in the tool registry.
    """

    async def flag_for_legal(
        message_id_str: str,
        issue_type: str,
        summary: str,
    ) -> dict[str, Any]:
        """
        Flag a message for legal team review.

        Args:
            message_id_str: UUID string of the source Message to flag.
            issue_type:     Legal issue category — one of:
                            ``dsar`` | ``gdpr`` | ``cease_and_desist`` |
                            ``lawsuit`` | ``regulatory``.
            summary:        Free-text summary of the legal concern.  Stored as
                            the LegalFlag ``summary`` field.

        Returns:
            On success::

                {
                    "ok": True,
                    "tool_name": "flag_for_legal",
                    "data": {
                        "legal_flag_id": "<uuid | mock-uuid>",
                        "issue_type":    "<issue_type>",
                        "status":        "open",
                        "queue":         "legal_compliance"
                    }
                }

            On validation failure or DB error::

                {"ok": False, "tool_name": "flag_for_legal", "error": "<message>"}
        """
        tool_name = "flag_for_legal"
        try:
            # ------------------------------------------------------------------
            # Validate issue_type
            # ------------------------------------------------------------------
            if issue_type not in _VALID_ISSUE_TYPES:
                return {
                    "ok": False,
                    "tool_name": tool_name,
                    "error": (
                        f"Invalid issue_type '{issue_type}'. "
                        f"Must be one of: {sorted(_VALID_ISSUE_TYPES)}"
                    ),
                }

            source_msg_uuid = uuid.UUID(message_id_str)

            # ------------------------------------------------------------------
            # Persist LegalFlag (skipped in dry_run)
            # ------------------------------------------------------------------
            if dry_run:
                legal_flag_id = _MOCK_LEGAL_FLAG_ID
                logger.info(
                    "[dry_run] flag_for_legal: skipping DB write, "
                    "mock legal_flag_id=%s issue_type=%s",
                    legal_flag_id,
                    issue_type,
                )
            else:
                legal_flag = LegalFlag(
                    source_message_id=source_msg_uuid,
                    agent_run_id=agent_run_id,
                    issue_type=issue_type,
                    summary=summary,
                    legal_status="open",
                )
                db.add(legal_flag)
                await db.flush()
                legal_flag_id = str(legal_flag.id)
                logger.info(
                    "flag_for_legal: persisted LegalFlag id=%s "
                    "issue_type=%s message_id=%s",
                    legal_flag_id,
                    issue_type,
                    message_id_str,
                )

            return {
                "ok": True,
                "tool_name": tool_name,
                "data": {
                    "legal_flag_id": legal_flag_id,
                    "issue_type": issue_type,
                    "status": "open",
                    "queue": _LEGAL_QUEUE,
                },
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("flag_for_legal error: %s", exc, exc_info=True)
            return {"ok": False, "tool_name": tool_name, "error": str(exc)}

    return flag_for_legal
