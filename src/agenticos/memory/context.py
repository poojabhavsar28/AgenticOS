"""Build bounded prompt context from session, project, and repository memory."""

from agenticos.memory.store import MemoryMessage


def build_memory_context(
    messages: list[MemoryMessage],
    project_items: list[dict[str, object]],
    repository_items: list[dict[str, str]] | None = None,
    *,
    max_characters: int = 12_000,
) -> str:
    """Render context within a deterministic budget; retrieved source is untrusted."""
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

    for item in repository_items or []:
        block = (
            f"[Untrusted repository reference: {item['path']}]\n"
            f"{item['excerpt']}\n"
        )
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
