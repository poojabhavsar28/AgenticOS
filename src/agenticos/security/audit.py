"""Minimal in-process security audit events."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class AuditEvent:
    principal_id: str
    action: str
    resource: str
    outcome: str
    occurred_at: str


class AuditLog:
    """Bounded audit event buffer; callers must persist it for durable auditing."""

    def __init__(self, *, max_events: int = 10_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self.max_events = max_events
        self._events: list[AuditEvent] = []

    def record(
        self, principal_id: str, action: str, resource: str, outcome: str
    ) -> AuditEvent:
        event = AuditEvent(
            principal_id=principal_id,
            action=action,
            resource=resource,
            outcome=outcome,
            occurred_at=datetime.now(UTC).isoformat(),
        )
        self._events.append(event)
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]
        return event

    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)
