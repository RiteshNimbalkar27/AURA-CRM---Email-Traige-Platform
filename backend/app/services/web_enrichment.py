"""
AURA Web Enrichment Service
============================
Fetches public competitor-pricing and review data from configurable URLs
and caches results in the ``market_intel_cache`` DB table with a 6-hour TTL.

Safety constraints
------------------
* Only fetches URLs that are explicitly declared in Settings
  (``enrichment_review_url`` / ``enrichment_competitor_url``).
  No user-supplied URLs are ever fetched, so no PII leaks out.
* Robots.txt is respected before every fresh fetch.
* On any fresh-fetch failure the last cached row (even if stale) is returned
  so callers always get *something* useful.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.web import MarketIntelCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CACHE_TTL_HOURS: int = 6
_REQUEST_TIMEOUT: float = 15.0          # seconds
_USER_AGENT: str = "AURA-enrichment-bot/1.0 (internal; no PII)"
_MAX_BODY_CHARS: int = 20_000           # truncate very large pages


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_allowed_by_robots(url: str) -> bool:
    """
    Check whether ``_USER_AGENT`` is permitted to fetch *url* by the site's
    robots.txt.  Returns ``True`` when in doubt (parse errors, network errors)
    so that transient issues don't permanently block enrichment.

    Args:
        url: The target page URL.

    Returns:
        ``True`` if fetching is allowed (or robots.txt is unreachable),
        ``False`` if explicitly disallowed.
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()          # synchronous — acceptable for a background service
        allowed: bool = rp.can_fetch(_USER_AGENT, url)
        if not allowed:
            logger.warning("robots.txt disallows fetching %s", url)
        return allowed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read robots.txt for %s (%s) — allowing fetch", url, exc)
        return True


def _now_utc() -> datetime:
    """Return the current UTC-aware datetime."""
    return datetime.now(timezone.utc)


def _expires_at() -> datetime:
    """Return the expiry timestamp (now + TTL)."""
    return _now_utc() + timedelta(hours=_CACHE_TTL_HOURS)


async def _fetch_url(url: str) -> tuple[str, str]:
    """
    Perform an async HTTP GET and return ``(summary, raw_text)``.

    The *summary* is just the first 500 characters of the body; callers can
    use ``raw_text`` for more detailed processing.

    Args:
        url: The URL to fetch.

    Returns:
        A tuple of ``(summary, raw_text)``.

    Raises:
        httpx.HTTPError: On network or HTTP-level failures.
        ValueError: If robots.txt disallows the fetch.
    """
    if not _is_allowed_by_robots(url):
        raise ValueError(f"robots.txt disallows fetching {url}")

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
    }
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()

    raw_text = response.text[:_MAX_BODY_CHARS]
    summary = raw_text[:500].strip()
    return summary, raw_text


def _infer_target_type(url: str) -> str:
    """
    Infer the ``target_type`` label from the URL by comparing against config.

    Args:
        url: The URL being enriched.

    Returns:
        ``'review'`` or ``'competitor_pricing'``.
    """
    settings = get_settings()
    if url == settings.enrichment_review_url:
        return "review"
    return "competitor_pricing"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_or_fetch_market_intel(
    db: AsyncSession,
    url: str,
) -> dict:
    """
    Return market-intelligence data for *url*, using the DB cache when the
    cached entry is still fresh (< 6 hours old).

    Workflow
    --------
    1. Look up the most recent ``MarketIntelCache`` row for *url*.
    2. If a fresh row exists (``expires_at > now``), return it immediately.
    3. Otherwise attempt a fresh HTTP fetch + robots.txt check.
    4. Persist the result (success **or** failure) as a new cache row.
    5. If the fresh fetch fails and a stale row exists, return the stale row
       with a ``stale=True`` flag so callers can surface a warning.

    Args:
        db:  An async SQLAlchemy session (injected by FastAPI's ``get_db``).
        url: The target URL — must be one of the config-declared enrichment
             URLs to prevent arbitrary fetch of external sites.

    Returns:
        A dict with keys::

            {
                "url":        str,
                "fetched_at": ISO-8601 str,
                "summary":    str | None,
                "raw_text":   str | None,
                "status":     str,           # 'success' | 'failed' | 'robots_denied' | 'timeout'
                "stale":      bool,          # True when returning cached-but-expired data
                "error":      str | None,
            }

    Raises:
        ValueError: If *url* is not one of the allowed enrichment URLs.
    """
    settings = get_settings()
    allowed_urls = {settings.enrichment_review_url, settings.enrichment_competitor_url}
    if url not in allowed_urls:
        raise ValueError(
            f"URL '{url}' is not in the allowed enrichment URL list. "
            "Only config-declared URLs may be fetched to prevent PII leakage."
        )

    now = _now_utc()
    target_type = _infer_target_type(url)

    # ------------------------------------------------------------------
    # 1. Check cache
    # ------------------------------------------------------------------
    cached_result = await db.execute(
        select(MarketIntelCache)
        .where(MarketIntelCache.target_url == url)
        .order_by(MarketIntelCache.fetched_at.desc())
        .limit(1)
    )
    cached: MarketIntelCache | None = cached_result.scalar_one_or_none()

    # 2. Return fresh cache hit
    if cached is not None and cached.expires_at.replace(tzinfo=timezone.utc) > now:
        logger.debug("Cache HIT (fresh) for %s", url)
        response_data = cached.response_data or {}
        return {
            "url": url,
            "fetched_at": cached.fetched_at.isoformat(),
            "summary": response_data.get("summary"),
            "raw_text": response_data.get("raw_text"),
            "status": cached.status,
            "stale": False,
            "error": cached.error_message,
        }

    # ------------------------------------------------------------------
    # 3. Attempt fresh fetch
    # ------------------------------------------------------------------
    logger.info("Cache MISS for %s — fetching fresh data", url)
    fetch_status: str = "success"
    summary: str | None = None
    raw_text: str | None = None
    error_message: str | None = None

    try:
        summary, raw_text = await _fetch_url(url)
    except ValueError as exc:
        # robots.txt denied
        fetch_status = "robots_denied"
        error_message = str(exc)
        logger.warning("robots.txt denied fetch for %s: %s", url, exc)
    except httpx.TimeoutException as exc:
        fetch_status = "timeout"
        error_message = f"Timeout: {exc}"
        logger.warning("Timeout fetching %s: %s", url, exc)
    except Exception as exc:  # noqa: BLE001
        fetch_status = "failed"
        error_message = str(exc)
        logger.exception("Failed to fetch enrichment data for %s: %s", url, exc)

    # ------------------------------------------------------------------
    # 4. Persist result
    # ------------------------------------------------------------------
    response_data_payload: dict | None = None
    if fetch_status == "success":
        response_data_payload = {"summary": summary, "raw_text": raw_text}

    new_row = MarketIntelCache(
        id=uuid.uuid4(),
        target_url=url,
        target_type=target_type,
        response_data=response_data_payload,
        status=fetch_status,
        fetched_at=now,
        expires_at=_expires_at(),
        error_message=error_message,
    )
    db.add(new_row)
    try:
        await db.flush()
        logger.debug("Persisted new MarketIntelCache row for %s (status=%s)", url, fetch_status)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to persist MarketIntelCache row: %s", exc)
        await db.rollback()

    # ------------------------------------------------------------------
    # 5. On failure, fall back to stale cache
    # ------------------------------------------------------------------
    if fetch_status != "success" and cached is not None:
        logger.info("Returning stale cache for %s due to fetch failure", url)
        stale_data = cached.response_data or {}
        return {
            "url": url,
            "fetched_at": cached.fetched_at.isoformat(),
            "summary": stale_data.get("summary"),
            "raw_text": stale_data.get("raw_text"),
            "status": cached.status,
            "stale": True,
            "error": error_message,
        }

    # Fresh data (success) or first-ever failure with no stale fallback
    return {
        "url": url,
        "fetched_at": now.isoformat(),
        "summary": summary,
        "raw_text": raw_text,
        "status": fetch_status,
        "stale": False,
        "error": error_message,
    }
