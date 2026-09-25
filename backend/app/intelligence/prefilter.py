"""
AURA Intelligence Pipeline — Layer 1: Deterministic Pre-filter
Synchronous, rule-based gate that runs before any LLM call.

Actions:
  block    — Spam/scam detected. Message should not be processed further.
  internal — Sender is from internal demo domain (@demo-company.example).
  allow    — Pass to Layer 2 (LLM classification), with optional urgency hint.

Urgency overrides (most severe wins, only set when action=allow):
  critical — ransomware, data breach, leaked credentials, extortion, dark web, unauthorized access
  high     — DSAR, GDPR, cease-and-desist, lawsuit, legal action, public review threat,
             press inquiry, investor inquiry
  medium   — refund, billing dispute, service outage, misinformation, cancellation request
"""
import logging
import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PrefilterAction(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    INTERNAL = "internal"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class PrefilterResult(BaseModel):
    """Result of the Layer 1 pre-filter check."""
    action: PrefilterAction
    urgency_override: Optional[str] = None  # critical | high | medium | None
    reason: str
    matched_rule: Optional[str] = None


# ---------------------------------------------------------------------------
# Rule sets (all lowercased for comparison)
# ---------------------------------------------------------------------------

_SPAM_TERMS: list[str] = [
    "crypto giveaway",
    "guaranteed profit",
    "wire transfer",
    "work from home",
    "click here to claim",
    "you've been selected",
]

_CRITICAL_TERMS: list[str] = [
    "ransomware",
    "data breach",
    "leaked credentials",
    "unauthorized access",
    "extortion",
    "dark web",
]

_HIGH_TERMS: list[str] = [
    "dsar",
    "gdpr",
    "cease-and-desist",
    "lawsuit",
    "legal action",
    "public review threat",
    "press inquiry",
    "investor inquiry",
]

_MEDIUM_TERMS: list[str] = [
    "refund",
    "billing dispute",
    "service outage",
    "misinformation",
    "cancellation request",
]

_INTERNAL_DOMAIN = "@demo-company.example"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _contains_term(text_lower: str, term: str) -> Optional[str]:
    """Return the term if it appears as a substring in text_lower, else None."""
    if term in text_lower:
        return term
    return None


def _first_match(text_lower: str, terms: list[str]) -> Optional[str]:
    """Return the first matching term or None."""
    for term in terms:
        if term in text_lower:
            return term
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_prefilter(
    subject: str,
    body: str,
    sender_email: str,
) -> PrefilterResult:
    """
    Execute all Layer 1 pre-filter rules synchronously.

    Args:
        subject:      Email subject line.
        body:         Raw email body text.
        sender_email: Sender's email address.

    Returns:
        PrefilterResult with action, optional urgency override, reason, and matched rule.
    """
    combined = (subject + " " + body).lower()
    sender_lower = sender_email.strip().lower()

    # ------------------------------------------------------------------
    # Rule 1: SPAM / block list
    # ------------------------------------------------------------------
    spam_match = _first_match(combined, _SPAM_TERMS)
    if spam_match:
        logger.info(
            "Prefilter BLOCK: spam term detected",
            extra={"matched_rule": spam_match, "sender": sender_email},
        )
        return PrefilterResult(
            action=PrefilterAction.BLOCK,
            urgency_override=None,
            reason=f"Spam/scam term detected in subject or body: '{spam_match}'",
            matched_rule=spam_match,
        )

    # ------------------------------------------------------------------
    # Rule 2: INTERNAL domain
    # ------------------------------------------------------------------
    if sender_lower.endswith(_INTERNAL_DOMAIN):
        logger.info(
            "Prefilter INTERNAL: sender is from internal domain",
            extra={"sender": sender_email},
        )
        return PrefilterResult(
            action=PrefilterAction.INTERNAL,
            urgency_override=None,
            reason=f"Sender domain is internal ({_INTERNAL_DOMAIN}). Routing to internal queue.",
            matched_rule="internal_domain",
        )

    # ------------------------------------------------------------------
    # Rule 3: CRITICAL urgency override
    # ------------------------------------------------------------------
    critical_match = _first_match(combined, _CRITICAL_TERMS)
    if critical_match:
        logger.info(
            "Prefilter ALLOW with urgency_override=critical",
            extra={"matched_rule": critical_match, "sender": sender_email},
        )
        return PrefilterResult(
            action=PrefilterAction.ALLOW,
            urgency_override="critical",
            reason=f"Critical security term detected: '{critical_match}'",
            matched_rule=critical_match,
        )

    # ------------------------------------------------------------------
    # Rule 4: HIGH urgency override
    # ------------------------------------------------------------------
    high_match = _first_match(combined, _HIGH_TERMS)
    if high_match:
        logger.info(
            "Prefilter ALLOW with urgency_override=high",
            extra={"matched_rule": high_match, "sender": sender_email},
        )
        return PrefilterResult(
            action=PrefilterAction.ALLOW,
            urgency_override="high",
            reason=f"High-priority compliance/legal term detected: '{high_match}'",
            matched_rule=high_match,
        )

    # ------------------------------------------------------------------
    # Rule 5: MEDIUM urgency override
    # ------------------------------------------------------------------
    medium_match = _first_match(combined, _MEDIUM_TERMS)
    if medium_match:
        logger.info(
            "Prefilter ALLOW with urgency_override=medium",
            extra={"matched_rule": medium_match, "sender": sender_email},
        )
        return PrefilterResult(
            action=PrefilterAction.ALLOW,
            urgency_override="medium",
            reason=f"Medium-priority operational term detected: '{medium_match}'",
            matched_rule=medium_match,
        )

    # ------------------------------------------------------------------
    # Default: allow, no urgency override
    # ------------------------------------------------------------------
    logger.debug("Prefilter ALLOW: no rules matched", extra={"sender": sender_email})
    return PrefilterResult(
        action=PrefilterAction.ALLOW,
        urgency_override=None,
        reason="No pre-filter rules matched. Proceeding to LLM classification.",
        matched_rule=None,
    )
