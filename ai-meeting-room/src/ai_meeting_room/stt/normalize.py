"""Fix common STT mishearings for wake words and agent names."""

from __future__ import annotations

import re

# Start-of-utterance wake words (order matters — more specific first).
_RELAY_START = (
    (re.compile(r"^(hey\s+)?relief\b", re.IGNORECASE), r"\1Relay"),
    (re.compile(r"^(hey\s+)?replay\b", re.IGNORECASE), r"\1Relay"),
    (re.compile(r"^(hey\s+)?relaid\b", re.IGNORECASE), r"\1Relay"),
    (re.compile(r"^(hey\s+)?really\b(?=[,\s]|$)", re.IGNORECASE), r"\1Relay"),
    (re.compile(r"^(hey\s+)?delay\b(?=[,\s]|$)", re.IGNORECASE), r"\1Relay"),
)

_CURSOR_START = (
    (re.compile(r"^(hey\s+)?curser\b", re.IGNORECASE), r"\1Cursor"),
    (re.compile(r"^(hey\s+)?courser\b", re.IGNORECASE), r"\1Cursor"),
    (re.compile(r"^(hey\s+)?Kerr\s+sir\b", re.IGNORECASE), r"\1Cursor"),
    (re.compile(r"^(hey\s+)?cursor's\b", re.IGNORECASE), r"\1Cursor"),
)

_INLINE = (
    (re.compile(r"\btell\s+curser\b", re.IGNORECASE), "tell Cursor"),
    (re.compile(r"\btell\s+courser\b", re.IGNORECASE), "tell Cursor"),
    (re.compile(r"\btell\s+Kerr\s+sir\b", re.IGNORECASE), "tell Cursor"),
    (re.compile(r"\bpass\s+(?:to\s+)?curser\b", re.IGNORECASE), "pass to Cursor"),
    (re.compile(r"\bpass\s+(?:to\s+)?courser\b", re.IGNORECASE), "pass to Cursor"),
    (re.compile(r"\bask\s+curser\b", re.IGNORECASE), "ask Cursor"),
    (re.compile(r"\bask\s+courser\b", re.IGNORECASE), "ask Cursor"),
    (re.compile(r"\bRelay\s+really\b", re.IGNORECASE), "Relay"),
    (re.compile(r"\bRelay\s+replay\b", re.IGNORECASE), "Relay"),
)

# Agent names occasionally mangled at the start.
_AGENT_START = (
    (re.compile(r"^(hey\s+)?missie\b", re.IGNORECASE), r"\1Missy"),
    (re.compile(r"^(hey\s+)?mizzy\b", re.IGNORECASE), r"\1Missy"),
    (re.compile(r"^(hey\s+)?architect's\b", re.IGNORECASE), r"\1Architect"),
    (re.compile(r"^(hey\s+)?project\s+alfa\b", re.IGNORECASE), r"\1Project Alpha"),
)


def normalize_transcript(text: str) -> str:
    """Apply lightweight corrections before routing speech."""
    cleaned = text.strip()
    if not cleaned:
        return cleaned

    for pattern, repl in _RELAY_START + _CURSOR_START + _AGENT_START:
        cleaned = pattern.sub(repl, cleaned, count=1)

    for pattern, repl in _INLINE:
        cleaned = pattern.sub(repl, cleaned)

    return cleaned


def default_stt_keyterms() -> list[str]:
    return [
        "Relay",
        "Cursor",
        "Missy",
        "Architect",
        "Project Alpha",
        "Alpha",
        "Fred",
        "Bridge",
    ]
