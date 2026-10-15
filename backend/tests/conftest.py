"""
AURA Test Configuration — conftest.py
======================================
Provides session-scoped fixtures and async helper functions for all acceptance
tests.  Uses the *dev* database (same DATABASE_URL as the running application)
because this is a demo system — no separate test DB is provisioned.

Key fixtures
------------
- ``app``              — The FastAPI application object (session scope).
- ``http_client``      — ``httpx.AsyncClient`` wired to the test app (session scope).
- ``operator_token``   — JWT for ``operator@nexus-software.example`` (session scope).
- ``auth_headers``     — ``{"Authorization": "Bearer <token>"}`` shorthand.

Helper coroutines (not fixtures — called explicitly in tests)
-------------------------------------------------------------
- ``ingest_and_wait``  — POST /api/ingest then poll /api/messages/{id} until
                         job_status == "completed" (or timeout).
- ``run_agent``        — POST /api/messages/{id}/agent-runs and return the
                         agent-run response payload.
"""

import asyncio
import sys
from typing import Any

import pytest
import pytest_asyncio
import httpx

# ---------------------------------------------------------------------------
# Windows: psycopg async requires SelectorEventLoop, not ProactorEventLoop.
# Must be set before any asyncio.run() or event-loop creation occurs.
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    """
    Return the FastAPI application instance.

    Imported here (not at module level) so that the Windows event-loop policy
    is already set before SQLAlchemy/asyncpg initialises its own loop state.
    """
    from app.main import app as _app  # noqa: WPS433
    return _app


@pytest_asyncio.fixture(scope="session")
async def http_client(app):
    """
    Async HTTP client bound to the FastAPI test application.

    Uses ``httpx.AsyncClient`` with ``ASGITransport`` so no real TCP socket
    is opened — requests are dispatched directly into the ASGI app.

    Scope is *session* so the client (and its underlying connection pool) is
    created once and shared across all tests, saving startup overhead.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=60.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def operator_token(http_client: httpx.AsyncClient) -> str:
    """
    Authenticate as the operator user and return the raw JWT string.

    Credentials match those seeded by ``scripts/seed.py`` for the demo system.
    The token is cached at session scope — login happens once per test run.
    """
    response = await http_client.post(
        "/auth/login",
        json={
            "email": "operator@nexus.example",
            "password": "operator_password_2024",
        },
    )
    assert response.status_code == 200, (
        f"Operator login failed ({response.status_code}): {response.text}"
    )
    data = response.json()
    token: str = data["access_token"]
    assert token, "access_token must not be empty after login"
    return token


@pytest.fixture(scope="session")
def auth_headers(operator_token: str) -> dict[str, str]:
    """
    Return an ``Authorization: Bearer`` header dict for use in all API calls.
    """
    return {"Authorization": f"Bearer {operator_token}"}


# ---------------------------------------------------------------------------
# Helper coroutines
# ---------------------------------------------------------------------------

async def ingest_and_wait(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    message: dict[str, Any],
    *,
    poll_interval: float = 2.0,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """
    Ingest a single message and block until the classification job finishes.

    Steps
    -----
    1. POST /api/ingest  → receive ``message_id``.
    2. Poll GET /api/messages/{message_id} every ``poll_interval`` seconds until
       ``job_status`` is ``"completed"`` or ``"failed"``, or ``timeout`` expires.
    3. Return the full message detail payload (including ``classifications``).

    Parameters
    ----------
    http_client:   The shared ASGI-bound test client.
    auth_headers:  Bearer-token headers for the operator user.
    message:       Dict matching ``IngestRequest`` schema (from a fixture JSON).
    poll_interval: Seconds between status polls.
    timeout:       Maximum seconds to wait for classification to complete.

    Returns
    -------
    The GET /api/messages/{id} response payload as a dict.

    Raises
    ------
    AssertionError  if ingest returns a non-202 status.
    TimeoutError    if classification does not complete within *timeout* seconds.
    """
    # 1. Ingest
    ingest_resp = await http_client.post(
        "/api/ingest",
        json=message,
        headers=auth_headers,
    )
    assert ingest_resp.status_code == 202, (
        f"POST /api/ingest returned {ingest_resp.status_code}: {ingest_resp.text}"
    )
    ingest_data = ingest_resp.json()
    message_id: str = str(ingest_data["message_id"])

    # 2. Poll for completion
    elapsed = 0.0
    while elapsed < timeout:
        msg_resp = await http_client.get(
            f"/api/messages/{message_id}",
            headers=auth_headers,
        )
        assert msg_resp.status_code == 200, (
            f"GET /api/messages/{message_id} returned {msg_resp.status_code}: {msg_resp.text}"
        )
        msg_data = msg_resp.json()
        job_status = msg_data.get("job_status", "")

        if job_status in ("completed", "failed"):
            return msg_data

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(
        f"Classification for message {message_id} did not complete within "
        f"{timeout}s (last job_status={job_status!r})"
    )


async def run_agent(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    message_id: str,
    *,
    mode: str = "live",
) -> dict[str, Any]:
    """
    Trigger the AURA agent on an already-classified message.

    Calls ``POST /api/messages/{message_id}/agent-runs`` and returns the
    response payload, which includes:

    - ``agent_run_id``    — UUID of the new AgentRun row.
    - ``outcome``         — ``"completed"`` | ``"failed"`` | ``"dry_run"``.
    - ``tool_calls_count``— Number of tool calls made during the run.
    - ``trace``           — List of redacted step dicts.
    - ``drafts``          — Drafts created during this run.
    - ``tickets``         — Tickets created during this run.
    - ``escalations``     — Escalations created during this run.
    - ``legal_flags``     — LegalFlags created during this run.

    Parameters
    ----------
    http_client:  The shared ASGI-bound test client.
    auth_headers: Bearer-token headers.
    message_id:   UUID string of the message to run the agent on.
    mode:         ``"live"`` (default) or ``"dry_run"``.

    Returns
    -------
    The response JSON as a dict.

    Raises
    ------
    AssertionError  if the response status is not 200 or 201.
    """
    resp = await http_client.post(
        f"/api/messages/{message_id}/agent-runs",
        json={"mode": mode},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), (
        f"POST /api/messages/{message_id}/agent-runs returned "
        f"{resp.status_code}: {resp.text}"
    )
    return resp.json()
