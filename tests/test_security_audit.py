from agenticos.security import AuditLog


def test_audit_log_is_bounded_and_returns_immutable_snapshot() -> None:
    log = AuditLog(max_events=2)
    log.record("agent-a", "execute", "tool-a", "allowed")
    log.record("agent-a", "execute", "tool-b", "denied")
    log.record("agent-b", "execute", "tool-c", "allowed")
    events = log.events()
    assert len(events) == 2
    assert events[0].resource == "tool-b"
    assert isinstance(events, tuple)
