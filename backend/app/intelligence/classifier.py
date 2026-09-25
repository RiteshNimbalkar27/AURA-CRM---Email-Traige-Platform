"""
AURA Intelligence Pipeline — Layer 2: LLM Classification Wrapper
Applies Layer 1 pre-filter first, then calls the LLM adapter for classification.

Safety invariants:
  - BLOCK result from pre-filter raises ValueError (message is never sent to LLM).
  - CRITICAL urgency_override always forces result.urgency = "critical" (cannot be
    downgraded by LLM output).
  - INTERNAL routing is flagged in the result rationale but still classified.
"""
import logging
from typing import Optional

from app.intelligence.prefilter import PrefilterAction, run_prefilter
from app.services.llm_adapter import ClassificationResult, get_llm_adapter

logger = logging.getLogger(__name__)


async def classify_message(
    subject: str,
    body: str,
    thread_context: list[dict] | None = None,
) -> ClassificationResult:
    """
    Classify an email through the two-layer intelligence pipeline.

    Layer 1 — Synchronous pre-filter (deterministic rules).
    Layer 2 — LLM classification via OpenRouter adapter.

    Args:
        subject:        Email subject line.
        body:           Raw or sanitized email body.
        thread_context: Optional list of prior thread messages passed to the LLM
                        for context (format: [{received_at, sender_email, body_excerpt}]).

    Returns:
        ClassificationResult with category, urgency, sentiment, confidence, etc.

    Raises:
        ValueError: If pre-filter action is BLOCK (spam/scam detected).
    """
    # ------------------------------------------------------------------
    # Extract sender from thread_context if available (best-effort).
    # The caller should always provide sender_email as the first element
    # in thread_context or via a dedicated kwarg; we default to empty string
    # so prefilter still works on subject+body rules.
    # ------------------------------------------------------------------
    sender_email: str = ""
    if thread_context:
        sender_email = thread_context[0].get("sender_email", "") if thread_context else ""

    # ------------------------------------------------------------------
    # Layer 1: Pre-filter
    # ------------------------------------------------------------------
    prefilter_result = run_prefilter(
        subject=subject,
        body=body,
        sender_email=sender_email,
    )

    logger.info(
        "Prefilter result: action=%s urgency_override=%s matched_rule=%s",
        prefilter_result.action,
        prefilter_result.urgency_override,
        prefilter_result.matched_rule,
    )

    if prefilter_result.action == PrefilterAction.BLOCK:
        logger.warning(
            "Message BLOCKED by pre-filter: %s", prefilter_result.reason
        )
        raise ValueError(
            f"Message blocked by pre-filter: {prefilter_result.reason}"
        )

    # ------------------------------------------------------------------
    # Build augmented thread_context: prepend urgency hint if overridden
    # so the LLM receives it as additional context.
    # ------------------------------------------------------------------
    augmented_context: list[dict] | None = thread_context

    if prefilter_result.urgency_override:
        hint: dict = {
            "received_at": "SYSTEM_HINT",
            "sender_email": "aura-prefilter",
            "body_excerpt": (
                f"[PRE-FILTER HINT] Urgency override detected: "
                f"{prefilter_result.urgency_override.upper()}. "
                f"Reason: {prefilter_result.reason}. "
                f"Matched rule: {prefilter_result.matched_rule}. "
                f"Ensure your classification reflects this urgency level."
            ),
        }
        augmented_context = [hint] + (thread_context or [])
        logger.info(
            "Injecting urgency hint into LLM context: %s",
            prefilter_result.urgency_override,
        )

    if prefilter_result.action == PrefilterAction.INTERNAL:
        internal_hint: dict = {
            "received_at": "SYSTEM_HINT",
            "sender_email": "aura-prefilter",
            "body_excerpt": (
                "[PRE-FILTER HINT] This message is from an internal sender "
                "(demo-company.example). Route to 'internal' queue."
            ),
        }
        augmented_context = [internal_hint] + (thread_context or [])
        logger.info("Message flagged as INTERNAL by pre-filter.")

    # ------------------------------------------------------------------
    # Layer 2: LLM Classification
    # ------------------------------------------------------------------
    adapter = get_llm_adapter()
    result: ClassificationResult = await adapter.classify_email(
        subject=subject,
        body=body,
        thread_context=augmented_context,
    )

    # ------------------------------------------------------------------
    # Post-processing: enforce critical urgency override (safety invariant).
    # If the pre-filter flagged critical, the LLM result MUST be critical
    # regardless of what the model returned.
    # ------------------------------------------------------------------
    if prefilter_result.urgency_override == "critical":
        if result.urgency != "critical":
            logger.warning(
                "LLM returned urgency=%s but pre-filter override forces critical. "
                "Overriding result urgency.",
                result.urgency,
            )
        # Use object.__setattr__ to bypass Pydantic immutability if model is frozen
        try:
            result.urgency = "critical"
        except Exception:
            # Pydantic v2 model_config frozen=True path
            result = result.model_copy(update={"urgency": "critical"})

    logger.info(
        "Classification complete: category=%s urgency=%s confidence=%.2f "
        "human_review=%s prefilter_action=%s",
        result.category,
        result.urgency,
        result.confidence,
        result.human_review_required,
        prefilter_result.action,
    )

    return result
