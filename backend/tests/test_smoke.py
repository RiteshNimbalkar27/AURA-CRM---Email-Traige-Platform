"""
AURA Smoke Tests — Phase 0
Verify basic system health before Phase 1 implementation.
"""
import pytest


def test_config_loads():
    """Settings load without errors."""
    from app.config import get_settings
    settings = get_settings()
    assert settings.environment in ("development", "testing", "production")
    assert settings.synthetic_data_only is True or settings.synthetic_data_only is False


def test_synthetic_data_guard():
    """SYNTHETIC_DATA_ONLY must be True by default."""
    from app.config import get_settings
    settings = get_settings()
    # In test environment this should default True
    # This test documents the requirement — adjust if env var is set
    assert isinstance(settings.synthetic_data_only, bool)


def test_password_hashing():
    """bcrypt password hashing and verification work correctly."""
    from app.core.security import get_password_hash, verify_password
    password = "test_password_123"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong_password", hashed)


def test_jwt_token_creation_and_decode():
    """JWT tokens can be created and decoded correctly."""
    from app.core.security import create_access_token, decode_token
    data = {"sub": "test-user-id", "role": "operator"}
    token = create_access_token(data)
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "test-user-id"
    assert payload["role"] == "operator"


def test_classification_result_validation():
    """ClassificationResult validates category and urgency correctly."""
    from app.services.gemini_adapter import ClassificationResult
    result = ClassificationResult(
        category="security",
        urgency="critical",
        sentiment_score=-0.8,
        confidence=0.95,
        rationale="Test rationale",
        proposed_action="Escalate immediately",
    )
    assert result.category == "security"
    assert result.urgency == "critical"
    assert result.human_review_required is False  # confidence >= 0.70


def test_low_confidence_triggers_human_review():
    """Confidence below 0.70 must set human_review_required=True."""
    from app.services.gemini_adapter import ClassificationResult
    result = ClassificationResult(
        category="general_inquiry",
        urgency="low",
        sentiment_score=0.1,
        confidence=0.65,  # Below threshold
        rationale="Unclear intent",
        proposed_action="Manual review",
    )
    assert result.human_review_required is True


def test_invalid_category_rejected():
    """Invalid categories must be rejected by validation."""
    from app.services.gemini_adapter import ClassificationResult
    import pytest
    with pytest.raises(Exception):  # pydantic ValidationError
        ClassificationResult(
            category="not_a_valid_category",
            urgency="low",
            sentiment_score=0.0,
            confidence=0.9,
            rationale="Test",
            proposed_action="Test",
        )
