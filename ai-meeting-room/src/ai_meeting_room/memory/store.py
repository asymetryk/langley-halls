"""Per-agent memory store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MemoryEntry:
    speaker: str
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentMemory:
    """Simple in-process memory per AI participant."""

    def __init__(self, agent_name: str, max_entries: int = 50) -> None:
        self.agent_name = agent_name
        self._entries: list[MemoryEntry] = []
        self._max_entries = max_entries

    def remember(self, speaker: str, text: str) -> None:
        self._entries.append(MemoryEntry(speaker=speaker, text=text))
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

    def summary(self) -> str:
        if not self._entries:
            return ""
        lines = [f"- [{e.timestamp}] {e.speaker}: {e.text}" for e in self._entries[-10:]]
        return "\n".join(lines)

    def as_messages(self) -> list[tuple[str, str]]:
        return [(e.speaker, e.text) for e in self._entries]
