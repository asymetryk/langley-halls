"""Relay participant helpers."""

from __future__ import annotations

import re

RELAY_ALIASES = ("relay", "bridge")

# Must address Relay by name at the start, or use an explicit pass-to-cursor phrase.
RELAY_ADDRESS = re.compile(r"^(?:hey\s+)?(?:relay|bridge)\b", re.IGNORECASE)

PASS_TO_CURSOR = re.compile(
    r"^(?:relay|bridge)[,\s]+(?:please\s+)?(?:tell|ask|send|pass|relay)\s+(?:to\s+)?(?:cursor\s+)?(.+)",
    re.IGNORECASE,
)

# Direct Cursor addressing — start-of-utterance or explicit ask/tell.
CURSOR_ADDRESS = re.compile(r"^(?:hey\s+)?cursor\b", re.IGNORECASE)
ASK_OR_TELL_CURSOR = re.compile(r"\b(?:ask|tell)\s+cursor\b", re.IGNORECASE)


def is_addressing_relay(transcript: str) -> bool:
    """True only when the human clearly talks to Relay — not incidental words."""
    text = transcript.strip()
    if not text:
        return False
    if RELAY_ADDRESS.match(text):
        return True
    return bool(PASS_TO_CURSOR.search(text))


def is_addressing_cursor(transcript: str) -> bool:
    """True when the human talks to Cursor directly, not just mentions the word."""
    text = transcript.strip()
    if not text:
        return False
    if CURSOR_ADDRESS.match(text):
        return True
    return bool(ASK_OR_TELL_CURSOR.search(text))


def is_cursor_or_relay_bound(transcript: str) -> bool:
    """True when the line belongs in the Cursor/Relay inbox, not the chair."""
    return is_addressing_relay(transcript) or is_addressing_cursor(transcript)


def extract_cursor_message(transcript: str) -> str | None:
    """Pull the payload when the human asks Relay to pass something to Cursor."""
    text = transcript.strip()
    match = PASS_TO_CURSOR.search(text)
    if match:
        payload = match.group(1).strip(" .")
        if payload.lower().startswith("to "):
            payload = payload[3:]
        return payload

    if not RELAY_ADDRESS.match(text):
        return None

    # "Relay, the agents are too chatty" → pass the remainder after the name.
    remainder = RELAY_ADDRESS.sub("", text, count=1).strip(" ,:-.")
    if remainder and len(remainder.split()) >= 3:
        return remainder
    return None
