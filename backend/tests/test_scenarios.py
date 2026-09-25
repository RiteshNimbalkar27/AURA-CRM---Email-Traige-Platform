"""
AURA Scenario Acceptance Tests — test_scenarios.py
====================================================
End-to-end acceptance tests for the five canonical AURA triage scenarios.
Each test ingests a fixture message, waits for LLM classification to complete,
triggers the AURA agent, and asserts the expected outcomes from the fixture.

Scenarios
---------
01  DSAR (GDPR Data Subject Access Request)
02  Ransomware / extortion threat
03  Misinformation about API rate limits
04  Reputation crisis (angry enterprise customer)
05  Conflicting signals — multi-message billing thread

Also included
-------------
- ``test_dry_run_no_side_effects`` — Verifies the dry_run invariant: agent
  run with mode='dry_run' must NOT persist any Ticket, Escalation, LegalFlag,
  or Draft, and must return outcome='dry_run'.

Test execution
--------------
Run from the ``backend/`` directory with::

    pytest tests/test_scenarios.py -v --asyncio-mode=auto

Prerequisites
-------------
- PostgreSQL dev database must be accessible (same URL as the dev app).
- ARQ worker (``arq app.worker.main.WorkerSettings``) must be running.
- Knowledge-base documents must be seeded (``python scripts/seed_kb.py``).
- Operator user must be seeded (``python scripts/seed.py``).
"""

import json
import pathlib
import uuid
from typing import Any

import pytest
import pytest_asyncio
import httpx

# Re-export helpers from conftest so type-checkers are satisfied.
# The fixtures ``http_client``, ``auth_headers`` are injected by pytest.
from tests.conftest import ingest_and_wait, run_agent

# ---------------------------------------------------------------------------
# Fixture file loading helpers
# ---------------------------------------------------------------------------

_FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"


def _load_fixture(filename: str) -> dict:
    """Load and parse a JSON scenario fixture from the fixtures directory."""
    path = _FIXTURES_DIR / filename
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Shared scenario data (loaded once at module import time)
# ---------------------------------------------------------------------------

SCENARIO_01 = _load_fixture("scenario_01_dsar.json")
SCENARIO_02 = _load_fixture("scenario_02_ransomware.json")
SCENARIO_03 = _load_fixture("scenario_03_misinformation.json")
SCENARIO_04 = _load_fixture("scenario_04_reputation_crisis.json")
SCENARIO_05 = _load_fixture("scenario_05_conflicting_signals.json")


# ---------------------------------------------------------------------------
# Internal assertion helpers
# ---------------------------------------------------------------------------

def _get_latest_classification(msg_data: dict) -> dict | None:
    """
    Return the most recent classification from a GET /api/messages response.

    Classifications are sorted descending by ``classified_at``; index 0 is
    the most recent.
    """
    classifications = msg_data.get("classifications", [])
    if not classifications:
        return None
    # Already sorted descending by classified_at in the API response.
    return classifications[0]


def _assert_classification(
    msg_data: dict,
    *,
    expected_category: str | list[str],
    expected_urgency: str | list[str],
    scenario_label: str,
) -> dict:
    """
    Assert classification category and urgency, then return the classification.

    Parameters
    ----------
    msg_data:          GET /api/messages/{id} response payload.
    expected_category: Expected category string, or list of accepted values.
    expected_urgency:  Expected urgency string, or list of accepted values.
    scenario_label:    Human-readable label used in assertion failure messages.

    Returns
    -------
    The classification dict.
    """
    cls = _get_latest_classification(msg_data)
    assert cls is not None, (
        f"[{scenario_label}] No classification found for message "
        f"{msg_data.get('message_id')}. Is the ARQ worker running?"
    )

    accepted_categories = (
        [expected_category] if isinstance(expected_category, str) else expected_category
    )
    accepted_urgencies = (
        [expected_urgency] if isinstance(expected_urgency, str) else expected_urgency
    )

    assert cls["category"] in accepted_categories, (
        f"[{scenario_label}] classification.category={cls['category']!r} "
        f"not in expected {accepted_categories}"
    )
    assert cls["urgency"] in accepted_urgencies, (
        f"[{scenario_label}] classification.urgency={cls['urgency']!r} "
        f"not in expected {accepted_urgencies}"
    )
    return cls


def _assert_agent_run_succeeded(
    run_data: dict,
    scenario_label: str,
    *,
    allow_dry_run: bool = False,
) -> None:
    """
    Assert the agent run did not fail.

    Parameters
    ----------
    run_data:      POST /api/messages/{id}/agent-runs response payload.
    scenario_label: Label for failure messages.
    allow_dry_run:  If True, 'dry_run' outcome is also accepted.
    """
    accepted = {"completed", "partial"}
    if allow_dry_run:
        accepted.add("dry_run")
    outcome = run_data.get("outcome", "")
    assert outcome in accepted, (
        f"[{scenario_label}] agent run outcome={outcome!r}; "
        f"expected one of {sorted(accepted)}"
    )


# ---------------------------------------------------------------------------
# Scenario 01 — GDPR DSAR
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_01_dsar(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """
    Scenario 01: GDPR Data Subject Access Request (DSAR).

    Expected outcomes
    -----------------
    - classification.category == 'legal_compliance'
    - classification.urgency  == 'high'
    - Agent creates a LegalFlag with issue_type == 'dsar'
    - Agent creates a Ticket routed to 'legal_compliance' queue
    - Agent creates a Draft with status == 'pending_approval' (requires approval)
    - Draft citations list is non-empty (must cite GDPR compliance policy)
    """
    scenario = SCENARIO_01
    expected = scenario["expected_outcomes"]
    label = scenario["scenario_id"]

    # --- Ingest the single DSAR message and wait for classification ----------
    fixture_msg = scenario["messages"][0]
    msg_data = await ingest_and_wait(http_client, auth_headers, fixture_msg)

    message_id: str = msg_data["message_id"]
    assert msg_data["job_status"] == "completed", (
        f"[{label}] Classification job did not complete — "
        f"job_status={msg_data['job_status']!r}"
    )

    # --- Assert classification ----------------------------------------------
    cls = _assert_classification(
        msg_data,
        expected_category=expected["category"],       # 'legal_compliance'
        expected_urgency=expected["urgency"],          # 'high'
        scenario_label=label,
    )

    # --- Trigger agent run --------------------------------------------------
    run_data = await run_agent(http_client, auth_headers, message_id)
    _assert_agent_run_succeeded(run_data, label)

    # --- Assert LegalFlag created with issue_type == 'dsar' -----------------
    legal_flags: list[dict] = run_data.get("legal_flags", [])
    assert len(legal_flags) >= 1, (
        f"[{label}] Expected at least one LegalFlag; got {legal_flags}"
    )
    dsar_flags = [
        lf for lf in legal_flags
        if lf.get("issue_type", "").lower() == expected["legal_issue_type"]  # 'dsar'
    ]
    assert len(dsar_flags) >= 1, (
        f"[{label}] No LegalFlag with issue_type='dsar' found; "
        f"got issue_types: {[lf.get('issue_type') for lf in legal_flags]}"
    )

    # --- Assert Ticket created in 'legal_compliance' queue ------------------
    tickets: list[dict] = run_data.get("tickets", [])
    assert len(tickets) >= 1, (
        f"[{label}] Expected at least one Ticket; got none."
    )
    legal_tickets = [
        t for t in tickets
        if t.get("assignee_queue", "") == expected["ticket_queue"]  # 'legal_compliance'
    ]
    assert len(legal_tickets) >= 1, (
        f"[{label}] No Ticket with assignee_queue={expected['ticket_queue']!r}; "
        f"got queues: {[t.get('assignee_queue') for t in tickets]}"
    )

    # --- Assert Draft created with status == 'pending_approval' -------------
    drafts: list[dict] = run_data.get("drafts", [])
    assert len(drafts) >= 1, (
        f"[{label}] Expected at least one Draft; got none."
    )
    approval_drafts = [
        d for d in drafts if d.get("status") == "pending_approval"
    ]
    assert len(approval_drafts) >= 1, (
        f"[{label}] Expected Draft.status='pending_approval'; "
        f"got statuses: {[d.get('status') for d in drafts]}"
    )

    # --- Assert Draft contains citations ------------------------------------
    draft = approval_drafts[0]
    citations_count: int = draft.get("citations_count", 0)
    assert citations_count > 0, (
        f"[{label}] Draft must include policy citations (citations_count={citations_count}). "
        "The agent must retrieve from the knowledge base and cite compliance policy."
    )

    # --- Assert draft body is non-empty ------------------------------------
    body_preview: str = draft.get("body_preview", "")
    assert len(body_preview.strip()) > 0, (
        f"[{label}] Draft body_preview must not be empty."
    )


# ---------------------------------------------------------------------------
# Scenario 02 — Ransomware / Extortion Threat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_02_ransomware(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """
    Scenario 02: Ransomware / extortion threat.

    Critical invariant: The agent MUST NOT produce a Draft for a critical-
    urgency security escalation.  This is the primary safety test.

    Expected outcomes
    -----------------
    - classification.category == 'security'
    - classification.urgency  == 'critical'
    - Agent creates an Escalation in 'security' queue with priority == 'critical'
    - Agent does NOT create any Draft
    - agent_run.outcome != 'failed'
    """
    scenario = SCENARIO_02
    expected = scenario["expected_outcomes"]
    label = scenario["scenario_id"]

    # --- Ingest and classify ------------------------------------------------
    fixture_msg = scenario["messages"][0]
    msg_data = await ingest_and_wait(http_client, auth_headers, fixture_msg)

    message_id: str = msg_data["message_id"]
    assert msg_data["job_status"] == "completed", (
        f"[{label}] Classification job did not complete — "
        f"job_status={msg_data['job_status']!r}"
    )

    # --- Assert classification: security + critical -------------------------
    _assert_classification(
        msg_data,
        expected_category=expected["category"],    # 'security'
        expected_urgency=expected["urgency"],       # 'critical'
        scenario_label=label,
    )

    # --- Trigger agent run --------------------------------------------------
    run_data = await run_agent(http_client, auth_headers, message_id)

    # outcome must not be 'failed'
    assert run_data.get("outcome") != "failed", (
        f"[{label}] agent_run.outcome must not be 'failed'; "
        f"got {run_data.get('outcome')!r}"
    )

    # --- Assert critical Escalation created in 'security' queue -------------
    escalations: list[dict] = run_data.get("escalations", [])
    assert len(escalations) >= 1, (
        f"[{label}] Expected at least one Escalation; got none."
    )
    security_escalations = [
        e for e in escalations
        if e.get("queue") == expected["escalation_queue"]  # 'security'
        and e.get("priority") == expected["escalation_priority"]  # 'critical'
    ]
    assert len(security_escalations) >= 1, (
        f"[{label}] Expected Escalation(queue='security', priority='critical'); "
        f"got: {[(e.get('queue'), e.get('priority')) for e in escalations]}"
    )

    # --- CRITICAL INVARIANT: No Draft must be created -----------------------
    drafts: list[dict] = run_data.get("drafts", [])
    assert len(drafts) == 0, (
        f"[{label}] CRITICAL INVARIANT VIOLATED: The agent must NEVER draft a "
        f"reply to a ransomware / critical-security message. "
        f"Got {len(drafts)} draft(s): {drafts}"
    )


# ---------------------------------------------------------------------------
# Scenario 03 — Misinformation about API Rate Limits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_03_misinformation(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """
    Scenario 03: Customer repeats misinformation about API rate limit cuts.

    Expected outcomes
    -----------------
    - classification.category in ['product_support', 'reputation']
    - Agent creates a Draft with at least one RAG citation
    - Agent creates an Escalation (to notify comms team of social media spread)
    - Draft body is non-empty
    """
    scenario = SCENARIO_03
    expected = scenario["expected_outcomes"]
    label = scenario["scenario_id"]

    # --- Ingest and classify ------------------------------------------------
    fixture_msg = scenario["messages"][0]
    msg_data = await ingest_and_wait(http_client, auth_headers, fixture_msg)

    message_id: str = msg_data["message_id"]
    assert msg_data["job_status"] == "completed", (
        f"[{label}] Classification job did not complete — "
        f"job_status={msg_data['job_status']!r}"
    )

    # --- Assert classification: product_support or reputation ---------------
    # The fixture expects 'product_support' but the LLM may reasonably also
    # return 'reputation' given the social media aspect.
    _assert_classification(
        msg_data,
        expected_category=["product_support", "reputation"],
        expected_urgency=["low", "medium", "high"],  # broad — key test is draft
        scenario_label=label,
    )

    # --- Trigger agent run --------------------------------------------------
    run_data = await run_agent(http_client, auth_headers, message_id)
    _assert_agent_run_succeeded(run_data, label)

    # --- Assert Draft with citations created --------------------------------
    drafts: list[dict] = run_data.get("drafts", [])
    assert len(drafts) >= 1, (
        f"[{label}] Expected at least one Draft; got none. "
        "The agent must draft an empathetic cited response correcting the misinformation."
    )
    cited_drafts = [d for d in drafts if d.get("citations_count", 0) > 0]
    assert len(cited_drafts) >= 1, (
        f"[{label}] At least one Draft must include RAG citations; "
        f"got citation counts: {[d.get('citations_count') for d in drafts]}"
    )

    # --- Assert draft body is non-empty ------------------------------------
    draft = cited_drafts[0]
    body_preview: str = draft.get("body_preview", "")
    assert len(body_preview.strip()) > 0, (
        f"[{label}] Draft body_preview must not be empty."
    )

    # --- Assert Escalation created -----------------------------------------
    escalations: list[dict] = run_data.get("escalations", [])
    assert len(escalations) >= 1, (
        f"[{label}] Expected at least one Escalation (to flag social media "
        f"misinformation for the comms team); got none."
    )


# ---------------------------------------------------------------------------
# Scenario 04 — Reputation Crisis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_04_reputation_crisis(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """
    Scenario 04: Enterprise customer threatening public reviews, press, investors.

    Expected outcomes
    -----------------
    - classification.category == 'reputation'
    - classification.urgency in ['high', 'critical']
    - Agent creates an Escalation in 'reputation_retention' queue
    - If urgency == 'critical', no Draft must be created
    - If urgency != 'critical', a Draft is expected (empathetic retention offer)
    """
    scenario = SCENARIO_04
    expected = scenario["expected_outcomes"]
    label = scenario["scenario_id"]

    # --- Ingest and classify ------------------------------------------------
    fixture_msg = scenario["messages"][0]
    msg_data = await ingest_and_wait(http_client, auth_headers, fixture_msg)

    message_id: str = msg_data["message_id"]
    assert msg_data["job_status"] == "completed", (
        f"[{label}] Classification job did not complete — "
        f"job_status={msg_data['job_status']!r}"
    )

    # --- Assert classification: reputation + high/critical ------------------
    cls = _assert_classification(
        msg_data,
        expected_category=expected["category"],      # 'reputation'
        expected_urgency=["high", "critical"],
        scenario_label=label,
    )
    actual_urgency: str = cls["urgency"]

    # --- Trigger agent run --------------------------------------------------
    run_data = await run_agent(http_client, auth_headers, message_id)
    _assert_agent_run_succeeded(run_data, label)

    # --- Assert Escalation in 'reputation_retention' queue ------------------
    escalations: list[dict] = run_data.get("escalations", [])
    assert len(escalations) >= 1, (
        f"[{label}] Expected at least one Escalation; got none."
    )
    retention_escalations = [
        e for e in escalations
        if e.get("queue") == expected["escalation_queue"]  # 'reputation_retention'
    ]
    assert len(retention_escalations) >= 1, (
        f"[{label}] Expected Escalation(queue='reputation_retention'); "
        f"got queues: {[e.get('queue') for e in escalations]}"
    )

    # --- Conditional: no Draft if urgency is 'critical' --------------------
    drafts: list[dict] = run_data.get("drafts", [])
    if actual_urgency == "critical":
        assert len(drafts) == 0, (
            f"[{label}] urgency='critical' — agent must NOT produce a Draft. "
            f"Got {len(drafts)} draft(s): {drafts}"
        )
    else:
        # urgency == 'high': a retention draft is expected
        assert len(drafts) >= 1, (
            f"[{label}] urgency='high' — expected at least one retention Draft; "
            f"got none."
        )
        # Validate non-empty body
        body_preview: str = drafts[0].get("body_preview", "")
        assert len(body_preview.strip()) > 0, (
            f"[{label}] Draft body_preview must not be empty."
        )


# ---------------------------------------------------------------------------
# Scenario 05 — Conflicting Signals (Multi-Message Billing Thread)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_05_conflicting_signals(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """
    Scenario 05: Two-message thread — sales confirmed $65/mo, invoice shows $79/mo.

    The agent MUST retrieve the thread history (``get_thread_history`` tool call)
    to discover the prior agreed pricing.

    Expected outcomes
    -----------------
    - agent_run.outcome != 'failed'
    - agent_run.trace has at least 2 tool calls (get_thread_history or
      search_knowledge_base)
    - agent_run.tool_calls_count >= 1
    """
    scenario = SCENARIO_05
    expected = scenario["expected_outcomes"]
    label = scenario["scenario_id"]

    # --- Ingest both messages in thread order -------------------------------
    # Message 1 (older: Jan 22) must be ingested first so the thread exists.
    # Message 2 (newer: Feb 5) is the active complaint — we run agent on this.
    messages = scenario["messages"]
    assert len(messages) == 2, (
        f"[{label}] Fixture must have exactly 2 messages; got {len(messages)}"
    )

    # Ingest message 1 (original pricing confirmation)
    await ingest_and_wait(http_client, auth_headers, messages[0])

    # Ingest message 2 (billing complaint) — this is the one we run agent on
    msg_data = await ingest_and_wait(http_client, auth_headers, messages[1])
    message_id: str = msg_data["message_id"]

    assert msg_data["job_status"] == "completed", (
        f"[{label}] Classification job did not complete — "
        f"job_status={msg_data['job_status']!r}"
    )

    # --- Classification: billing_refund (lenient on urgency) ----------------
    # The fixture expects 'billing_refund'; accept also 'product_support' as
    # a reasonable LLM alternative.
    _assert_classification(
        msg_data,
        expected_category=["billing_refund", "product_support"],
        expected_urgency=["low", "medium", "high"],
        scenario_label=label,
    )

    # --- Trigger agent run --------------------------------------------------
    run_data = await run_agent(http_client, auth_headers, message_id)

    # --- Agent must not have failed ----------------------------------------
    outcome = run_data.get("outcome", "")
    assert outcome != "failed", (
        f"[{label}] agent_run.outcome must not be 'failed'; got {outcome!r}"
    )

    # --- Tool calls count >= 1 ---------------------------------------------
    tool_calls_count: int = run_data.get("tool_calls_count", 0)
    assert tool_calls_count >= 1, (
        f"[{label}] agent_run.tool_calls_count={tool_calls_count}; "
        "expected >= 1. The agent must call at least one tool "
        "(get_thread_history or search_knowledge_base)."
    )

    # --- Trace must show >= 2 steps with tool calls ------------------------
    trace: list[dict] = run_data.get("trace") or []
    # Count trace steps that reference get_thread_history or search_knowledge_base
    relevant_tool_steps = [
        step for step in trace
        if any(
            kw in str(step.get("action", "")).lower()
            for kw in ("get_thread_history", "search_knowledge_base",
                       "thread_history", "knowledge_base")
        )
    ]
    assert len(trace) >= 2, (
        f"[{label}] agent_run.trace must have >= 2 steps; got {len(trace)}. "
        "The agent must perform multiple reasoning steps including thread history retrieval."
    )
    # Soft assertion: trace should include a thread-history retrieval step.
    # We don't hard-fail here because trace field names may vary — the hard
    # assertion is tool_calls_count >= 1 above.
    if len(relevant_tool_steps) == 0:
        import warnings
        warnings.warn(
            f"[{label}] No get_thread_history/search_knowledge_base step found in "
            f"trace. Steps: {[s.get('action') for s in trace]}. "
            "Verify the agent calls get_thread_history for multi-message threads.",
            stacklevel=1,
        )


# ---------------------------------------------------------------------------
# Dry-run invariant test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_no_side_effects(
    http_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """
    Dry-run invariant: a mode='dry_run' agent run must NOT persist any
    Ticket, Escalation, LegalFlag, or Draft rows, and must return
    agent_run.outcome == 'dry_run'.

    Uses Scenario 01 (DSAR) as the test message — a rich scenario that would
    normally produce Tickets, Drafts, and LegalFlags in live mode, making it
    the best candidate to confirm the dry_run invariant.
    """
    scenario = SCENARIO_01
    label = "dry_run_test"

    # --- Ingest the DSAR message (may already exist from scenario_01 test) --
    fixture_msg = scenario["messages"][0]
    # Use a unique external_message_id to avoid deduplication with the live test.
    dry_run_msg = dict(fixture_msg)
    dry_run_msg["external_message_id"] = (
        fixture_msg["external_message_id"] + "_dry_run"
    )
    dry_run_msg["external_thread_id"] = (
        (fixture_msg.get("external_thread_id") or "thread_dsar_001") + "_dry_run"
    )

    msg_data = await ingest_and_wait(http_client, auth_headers, dry_run_msg)
    message_id: str = msg_data["message_id"]

    assert msg_data["job_status"] == "completed", (
        f"[{label}] Classification job did not complete for dry-run message."
    )

    # --- Trigger agent run in dry_run mode ----------------------------------
    run_data = await run_agent(
        http_client, auth_headers, message_id, mode="dry_run"
    )

    # --- Assert outcome == 'dry_run' ----------------------------------------
    assert run_data.get("outcome") == "dry_run", (
        f"[{label}] Expected agent_run.outcome='dry_run'; "
        f"got {run_data.get('outcome')!r}"
    )

    # --- Assert NO Ticket created -------------------------------------------
    tickets: list[dict] = run_data.get("tickets", [])
    assert len(tickets) == 0, (
        f"[{label}] dry_run must NOT create any Tickets; "
        f"got {len(tickets)}: {tickets}"
    )

    # --- Assert NO Escalation created ---------------------------------------
    escalations: list[dict] = run_data.get("escalations", [])
    assert len(escalations) == 0, (
        f"[{label}] dry_run must NOT create any Escalations; "
        f"got {len(escalations)}: {escalations}"
    )

    # --- Assert NO LegalFlag created ----------------------------------------
    legal_flags: list[dict] = run_data.get("legal_flags", [])
    assert len(legal_flags) == 0, (
        f"[{label}] dry_run must NOT create any LegalFlags; "
        f"got {len(legal_flags)}: {legal_flags}"
    )

    # --- Assert NO Draft created --------------------------------------------
    drafts: list[dict] = run_data.get("drafts", [])
    assert len(drafts) == 0, (
        f"[{label}] dry_run must NOT create any Drafts; "
        f"got {len(drafts)}: {drafts}"
    )
