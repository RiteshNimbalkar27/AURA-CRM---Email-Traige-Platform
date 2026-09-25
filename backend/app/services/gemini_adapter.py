"""
DEPRECATED: gemini_adapter.py
This module is kept for backward compatibility only.
All LLM functionality has moved to llm_adapter.py (OpenRouter / DeepSeek).
"""
from app.services.llm_adapter import (  # noqa: F401  re-exports
    LLMAdapter as GeminiAdapter,
    LLMError as GeminiError,
    SyntheticDataViolation,
    ClassificationResult,
    get_llm_adapter as get_gemini_adapter,
)

__all__ = [
    "GeminiAdapter",
    "GeminiError",
    "SyntheticDataViolation",
    "ClassificationResult",
    "get_gemini_adapter",
]
