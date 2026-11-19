"""Tests for addressed and bounded agent-to-agent messaging."""

import pytest

from agenticos.collaboration import (
    AgentCoordinator,
    AgentMessage,
    AgentProfile,
)


def make_coordinator(*, capacity: int = 10) -> AgentCoordinator:
    coordinator = AgentCoordinator(max_pending_per_agent=capacity)
    coordinator.register_agent(AgentProfile("planner", "Planner"))
    coordinator.register_agent(AgentProfile("coder", "Coder"))
    return coordinator


def test_messages_are_delivered_in_fifo_order_to_recipient() -> None:
    coordinator = make_coordinator()
    first = AgentMessage("planner", "coder", "Implement the API")
    second = AgentMessage("planner", "coder", "Add input validation")

    coordinator.send_message(first)
    coordinator.send_message(second)

    received = coordinator.receive_messages("coder", limit=1)
    assert received == (first,)
    assert coordinator.messages.pending_count("coder") == 1
    assert coordinator.receive_messages("coder") == (second,)


def test_message_bus_rejects_unknown_agents_and_full_inboxes() -> None:
    coordinator = make_coordinator(capacity=1)
    coordinator.send_message(AgentMessage("planner", "coder", "First"))

    with pytest.raises(OverflowError, match="inbox is full"):
        coordinator.send_message(AgentMessage("planner", "coder", "Second"))

    with pytest.raises(KeyError, match="Unknown agent"):
        coordinator.send_message(AgentMessage("planner", "missing", "Hello"))


def test_message_contract_and_receive_limit_validation() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        AgentMessage("planner", "coder", " ")

    coordinator = make_coordinator()
    with pytest.raises(ValueError, match="at least 1"):
        coordinator.receive_messages("coder", limit=0)
