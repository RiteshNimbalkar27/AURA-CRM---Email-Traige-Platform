"""
AURA LLM Adapter — OpenRouter (OpenAI-compatible)
Thin wrapper around OpenRouter's /chat/completions endpoint.
Default model: deepseek/deepseek-chat-v4-free  (DeepSeek V4 Flash 0731)

CRITICAL: SYNTHETIC_DATA_ONLY guard must be checked before every API call.
Real customer data or PII must NEVER be sent to the LLM.
"""
import json
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when the LLM API call fails after retries."""
    pass


class SyntheticDataViolation(Exception):
    """Raised when non-synthetic data is detected before an LLM call."""
    pass


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class ClassificationResult(BaseModel):
    category: str = Field(
        description="One of: security, legal_compliance, reputation, billing_refund, "
                    "product_support, sales_pricing, general_inquiry"
    )
    urgency: str = Field(description="One of: low, medium, high, critical")
    sentiment_score: float = Field(
        ge=-1.0, le=1.0,
        description="Continuous sentiment from -1.0 (very negative) to 1.0 (very positive)"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence in classification")
    human_review_required: bool = Field(default=False)
    entities: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Extracted entities: {people, organizations, topics, dates}",
    )
    rationale: str = Field(description="Brief explanation of classification decision")
    proposed_action: str = Field(description="Recommended next action")
    model_name: str = Field(default="deepseek/deepseek-v4-flash-0731")
    model_config = {"protected_namespaces": ()}

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid = {
            "security", "legal_compliance", "reputation", "billing_refund",
            "product_support", "sales_pricing", "general_inquiry",
        }
        if v not in valid:
            raise ValueError(f"category must be one of {valid}")
        return v

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v: str) -> str:
        valid = {"low", "medium", "high", "critical"}
        if v not in valid:
            raise ValueError(f"urgency must be one of {valid}")
        return v

    def model_post_init(self, __context: Any) -> None:
        """Auto-set human_review_required if confidence < 0.70."""
        if self.confidence < 0.70:
            object.__setattr__(self, "human_review_required", True)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CLASSIFICATION_SYSTEM_PROMPT = """You are AURA, an AI email triage system for Nexus Software Inc. (a B2B SaaS company).
Classify incoming support emails with accurate structured output.

CRITICAL RULES:
1. Ransomware threats, extortion, data breach claims, security incidents → category=security, urgency=critical
2. DSAR, GDPR requests, cease-and-desist, lawsuit threats → category=legal_compliance, urgency=high
3. Public review threats, press inquiries, investor mentions → category=reputation, urgency=high
4. Use most-severe precedence: security > legal_compliance > reputation > billing_refund > product_support > sales_pricing > general_inquiry
5. confidence < 0.70 → human_review_required must be true

All data is synthetic demo data. No real customer information.

You MUST respond with ONLY valid JSON matching this schema exactly:
{
  "category": "<one of the 7 categories>",
  "urgency": "<low|medium|high|critical>",
  "sentiment_score": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "human_review_required": <true|false>,
  "entities": {
    "people": [],
    "organizations": [],
    "topics": [],
    "dates": []
  },
  "rationale": "<2-3 sentence explanation>",
  "proposed_action": "<recommended next action>"
}

Do not include markdown fences, commentary, or any text outside the JSON object."""

DRAFT_SYSTEM_PROMPT = """You are drafting professional customer support replies for Nexus Software Inc.
Ground every response ONLY in the provided policy knowledge base chunks.
You MUST cite sources in this exact format: [Source: Document Title, Chunk: chunk_id]
Never invent policies. Keep replies 150-300 words. Sign as: Nexus Software Support Team."""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class LLMAdapter:
    """Adapter for OpenRouter's OpenAI-compatible /chat/completions endpoint."""

    def __init__(self) -> None:
        self._settings = settings
        self._base_url = settings.openrouter_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aura.nexus-software.example",
            "X-Title": "AURA Email Triage System",
        }

    # ------------------------------------------------------------------
    # Safety guard
    # ------------------------------------------------------------------

    def _check_synthetic_guard(self, text: str) -> None:
        """
        SAFETY GUARD: Refuse to call the LLM if SYNTHETIC_DATA_ONLY is True
        and the text contains obvious PII patterns that suggest real data.
        """
        if not self._settings.synthetic_data_only:
            logger.warning("SYNTHETIC_DATA_ONLY is False — ensure only demo data is processed!")
            return
        ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
        cc_pattern = r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b"
        if re.search(ssn_pattern, text) or re.search(cc_pattern, text):
            raise SyntheticDataViolation(
                "Potential real PII detected in input. Refusing to call LLM API. "
                "AURA processes synthetic demo data only."
            )

    # ------------------------------------------------------------------
    # Low-level HTTP call
    # ------------------------------------------------------------------

    async def _chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """POST to OpenRouter /chat/completions and return the assistant message text."""
        payload = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        # Extract content from response
        choices = data.get("choices", [])
        if not choices:
            raise LLMError(f"No choices in LLM response: {data}")
        msg = choices[0].get("message", {})
        content = msg.get("content") or ""
        if not content and msg.get("reasoning"):
            content = msg.get("reasoning")
        if not content:
            finish_reason = choices[0].get("finish_reason", "unknown")
            raise LLMError(f"Empty LLM response content (finish_reason={finish_reason})")
        return content

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def classify_email(
        self,
        subject: str,
        body: str,
        thread_context: list[dict] | None = None,
    ) -> ClassificationResult:
        """
        Classify an email using structured JSON output.
        Returns a validated ClassificationResult.
        """
        self._check_synthetic_guard(f"{subject} {body}")

        # Truncate body per spec: first 8000 + last 2000 chars if oversized
        MAX_BODY = 10_000
        if len(body) > MAX_BODY:
            body = body[:8000] + "\n...[truncated]...\n" + body[-2000:]

        # Build context string
        context_str = ""
        if thread_context:
            context_str = "\n\nPREVIOUS THREAD MESSAGES:\n"
            for msg in thread_context[-5:]:
                context_str += (
                    f"[{msg.get('received_at', 'unknown')}] "
                    f"{msg.get('sender_email', 'unknown')}: "
                    f"{msg.get('body_excerpt', '')[:500]}\n"
                )

        user_message = f"""Classify this email for Nexus Software Inc. support triage:

SUBJECT: {subject}

BODY:
{body}
{context_str}
"""
        messages = [
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        try:
            raw = await self._chat_completion(messages, temperature=0.1, max_tokens=512)

            # Strip possible markdown fences
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)

            parsed = json.loads(cleaned)
            result = ClassificationResult(**parsed)
            result.model_name = self._settings.llm_model
            logger.info(
                f"Classification: category={result.category}, "
                f"urgency={result.urgency}, confidence={result.confidence:.2f}"
            )
            return result

        except SyntheticDataViolation:
            raise
        except json.JSONDecodeError as e:
            logger.error(f"LLM returned invalid JSON: {e}\nRaw: {raw!r}")
            raise LLMError(f"Classification failed: invalid JSON from model: {e}") from e
        except Exception as e:
            logger.error(f"LLM classification error: {e}")
            raise LLMError(f"Classification failed: {e}") from e

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def generate_draft(
        self,
        message_context: dict,
        policy_chunks: list[dict],
        tone: str = "empathetic",
    ) -> str:
        """
        Generate a draft reply grounded in retrieved policy chunks.
        Citations are REQUIRED — included in the prompt.
        """
        self._check_synthetic_guard(message_context.get("body", ""))

        if not policy_chunks:
            raise LLMError(
                "Cannot generate draft: no policy chunks provided. Citations are required."
            )

        policy_context = "\n\n".join([
            f"[POLICY SOURCE: {c.get('title', 'Unknown')} | CHUNK ID: {c.get('chunk_id', 'unknown')}]\n"
            f"{c.get('excerpt', '')}"
            for c in policy_chunks
        ])

        user_message = f"""Draft a {tone} customer support reply on behalf of Nexus Software Inc.

CUSTOMER EMAIL:
From: {message_context.get('sender_email', 'customer')}
Subject: {message_context.get('subject', '')}
Body: {message_context.get('body', '')[:3000]}

RELEVANT POLICY KNOWLEDGE BASE:
{policy_context}

INSTRUCTIONS:
1. Write a professional, {tone} reply addressing the customer's concern
2. Ground your response ONLY in the policy chunks provided above
3. You MUST include citations: [Source: Document Title, Chunk: chunk_id]
4. Keep the reply concise (150-300 words)
5. Do NOT invent policies
6. This is a DRAFT — it requires Operator approval before sending
7. Sign as: Nexus Software Support Team"""

        messages = [
            {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        try:
            return await self._chat_completion(messages, temperature=0.3, max_tokens=600)
        except Exception as e:
            logger.error(f"LLM draft generation error: {e}")
            raise LLMError(f"Draft generation failed: {e}") from e

    async def smoke_test(self) -> dict:
        """
        Verify OpenRouter API connectivity with a minimal test call.
        Returns: {ok: bool, model: str, response_preview: str}
        """
        try:
            messages = [
                {"role": "user", "content": "Reply with exactly: AURA smoke test OK"},
            ]
            text = await self._chat_completion(messages, temperature=0.0, max_tokens=20)
            return {
                "ok": True,
                "model": self._settings.llm_model,
                "provider": "openrouter",
                "response_preview": text[:100],
            }
        except Exception as e:
            logger.error(f"LLM smoke test failed: {e}")
            return {
                "ok": False,
                "model": self._settings.llm_model,
                "provider": "openrouter",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_adapter: LLMAdapter | None = None


def get_llm_adapter() -> LLMAdapter:
    """Return a singleton LLMAdapter instance."""
    global _adapter
    if _adapter is None:
        _adapter = LLMAdapter()
    return _adapter


# Backward-compat aliases used in older code paths
GeminiAdapter = LLMAdapter
get_gemini_adapter = get_llm_adapter
GeminiError = LLMError
