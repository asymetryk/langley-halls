"""Relay participant helpers."""

from __future__ import annotations

import re

from ai_meeting_room.agents.tuning import contains_alias

RELAY_ALIASES = ("relay", "cursor", "bridge", "thread")

PASS_TO_CURSOR = re.compile(
    r"(?:relay|cursor|bridge|thread)[,\s]+(?:please\s+)?(?:tell|ask|send|pass|say)\s+(?:cursor\s+)?(.+)",
    re.IGNORECASE,
)


def is_addressing_relay(transcript: str) -> bool:
    lower = transcript.strip().lower()
    return any(contains_alias(lower, alias) for alias in RELAY_ALIASES)


def extract_cursor_message(transcript: str) -> str | None:
    """Pull the payload when the human asks Relay to pass something to Cursor."""
    match = PASS_TO_CURSOR.search(transcript.strip())
    if match:
        text = match.group(1).strip(" .")
        if text.lower().startswith("to "):
            text = text[3:]
        return text
    if is_addressing_relay(transcript):
        # Fallback: strip leading addressee words.
        text = transcript.strip()
        for alias in RELAY_ALIASES:
            text = re.sub(rf"^\s*{re.escape(alias)}\s*[,:]?\s*", "", text, flags=re.IGNORECASE)
        cleaned = text.strip(" .")
        if cleaned and len(cleaned.split()) >= 3:
            return cleaned
    return None
