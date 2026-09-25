"""
AURA Agent Tool Stubs — contract-only, MVP disabled
======================================================
These tools are defined in the AURA tool contract / PLAN.md but are NOT
enabled in the current MVP release.  They are present as stubs so that:

  1. The agent schema registry can list them (and the LLM knows they exist).
  2. Any inadvertent call fails gracefully with a clear ``tool_not_enabled``
     error rather than an unhandled exception.

Do NOT register these in ``get_tool_registry()`` until fully implemented.

Planned tools
-------------
get_contact_profile
    Would fetch a Contact + Account record from the CRM and return name,
    plan, billing status, and account health for the agent to use when
    personalising replies.

check_account_status
    Would return whether an account is active, at-risk, or churned, along
    with plan-level entitlements, so the agent can tailor triage priority.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_contact_profile(email: str) -> dict[str, Any]:
    """
    [CONTRACT STUB — NOT ENABLED IN MVP]

    Retrieve CRM contact profile for the given email address.

    Args:
        email: Email address of the contact to look up.

    Returns:
        Always returns::

            {
                "ok": False,
                "tool_name": "get_contact_profile",
                "error": "tool_not_enabled"
            }

    Notes:
        This tool will fetch Contact + Account data (name, plan,
        billing_status, operational_status) when implemented.
    """
    logger.debug("get_contact_profile called for email=%s [stub — not enabled]", email)
    return {
        "ok": False,
        "tool_name": "get_contact_profile",
        "error": "tool_not_enabled",
    }


async def check_account_status(email: str) -> dict[str, Any]:
    """
    [CONTRACT STUB — NOT ENABLED IN MVP]

    Check the billing/subscription status of the account associated with
    the given email address.

    Args:
        email: Email address used to resolve the Contact → Account.

    Returns:
        Always returns::

            {
                "ok": False,
                "tool_name": "check_account_status",
                "error": "tool_not_enabled"
            }

    Notes:
        This tool will return Account.plan, Account.billing_status, and
        Contact.operational_status when implemented.
    """
    logger.debug("check_account_status called for email=%s [stub — not enabled]", email)
    return {
        "ok": False,
        "tool_name": "check_account_status",
        "error": "tool_not_enabled",
    }
