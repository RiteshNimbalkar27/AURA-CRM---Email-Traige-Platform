"""
AURA Agent package.

Public API
----------
``run_agent`` — the main ReAct loop entry-point.

Usage::

    from app.agent import run_agent

    agent_run = await run_agent(
        message_id=...,
        classification_id=...,
        urgency="high",
        category="billing_refund",
        subject="...",
        body="...",
        sender_email="customer@example.com",
        db=db_session,
        mode="live",
    )
"""
from app.agent.react_loop import run_agent  # noqa: F401

__all__ = ["run_agent"]
