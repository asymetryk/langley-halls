"""Parse spoken or typed host commands for the meeting room."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ai_meeting_room.agents.definitions import ALL_AGENTS, agent_by_key
from ai_meeting_room.agents.tuning import NAME_ALIASES, contains_alias

HostAction = Literal["kick", "invite", "chair", "pause", "resume", "status"]


@dataclass(frozen=True)
class HostCommand:
    action: HostAction
    agent_key: str | None = None


def resolve_agent_key(text: str) -> str | None:
    """Map free text to an agent key."""
    lower = text.strip().lower()
    for key, aliases in NAME_ALIASES.items():
        if any(contains_alias(lower, alias) for alias in aliases):
            return key
    normalized = lower.replace(" ", "_")
    if agent_by_key(normalized):
        return normalized
    return None


def parse_host_command(transcript: str) -> HostCommand | None:
    """
    Detect host control phrases.

    Examples:
      - "room kick fred"
      - "kick fred from the call"
      - "invite missy back"
      - "make architect the chair"
      - "room pause" / "room resume" / "room status"
    """
    text = transcript.strip()
    lower = text.lower()

    if re.search(r"\broom\s+pause\b|\bstop\s+listening\b|\bmute\s+the\s+room\b", lower):
        return HostCommand("pause")
    if re.search(r"\broom\s+resume\b|\bstart\s+listening\b|\bunmute\s+the\s+room\b", lower):
        return HostCommand("resume")
    if re.search(r"\broom\s+status\b|\bwho(?:'s| is)\s+in\b", lower):
        return HostCommand("status")

    chair_match = re.search(
        r"(?:make|set)\s+(.+?)\s+(?:the\s+)?(?:chair|moderator|host)"
        r"|(?:chair|moderator)\s+(?:is|to)\s+(.+)",
        lower,
    )
    if chair_match:
        name = chair_match.group(1) or chair_match.group(2)
        key = resolve_agent_key(name or "")
        if key:
            return HostCommand("chair", agent_key=key)

    kick_match = re.search(r"(?:room\s+)?kick\s+(.+?)(?:\s+from|\s+out|\s+off|$)", lower)
    if kick_match:
        key = resolve_agent_key(kick_match.group(1))
        if key:
            return HostCommand("kick", agent_key=key)

    remove_match = re.search(r"\bremove\s+(.+?)(?:\s+from|\s+out|$)", lower)
    if remove_match:
        key = resolve_agent_key(remove_match.group(1))
        if key:
            return HostCommand("kick", agent_key=key)

    invite_match = re.search(
        r"(?:room\s+)?(?:invite|bring)\s+(.+?)(?:\s+back|\s+in|$)",
        lower,
    )
    if invite_match:
        key = resolve_agent_key(invite_match.group(1))
        if key:
            return HostCommand("invite", agent_key=key)

    return None


def all_agent_keys() -> set[str]:
    return {agent.key for agent in ALL_AGENTS}
