"""Build bounded prompt context from session and project memory."""

from agenticos.memory.store import MemoryMessage


def build_memory_context(
    messages: list[MemoryMessage],
    project_items: list[dict[str, object]],
    *,
    max_characters: int = 12_000,
) -> str:
    """Render recent history and project notes within a deterministic character budget."""
    if max_characters < 1:
        raise ValueError("Context budget must be positive")

    sections: list[str] = []
    remaining = max_characters
    header = "Relevant project and conversation context:\n"
    remaining -= len(header)

    for item in project_items:
        block = f"[Project: {item['source_key']}]\n{item['content']}\n"
        if len(block) > remaining:
            break
        sections.append(block)
        remaining -= len(block)

    for message in messages:
        block = f"[{message.role}]\n{message.content}\n"
        if len(block) > remaining:
            break
        sections.append(block)
        remaining -= len(block)

    if not sections:
        return ""
    return header + "\n".join(sections)
