"""Turn-taking and response routing for interactive meetings."""

from __future__ import annotations

import re

NAME_ALIASES: dict[str, list[str]] = {
    "fred": ["fred"],
    "missy": ["missy"],
    "architect": ["architect"],
    "project_alpha": ["project alpha", "alpha"],
}

ROOM_WIDE_ALIASES = ("everyone", "team", "anybody", "anyone", "you all", "you guys")

FILLER_ONLY = re.compile(
    r"^(?:um+|uh+|hmm+|yeah|yep|yup|ok|okay|right|sure|thanks|thank you|got it|cool|nice|alright)[\s.!]*$",
    re.IGNORECASE,
)

QUESTION_STARTERS = (
    "what ",
    "how ",
    "why ",
    "when ",
    "where ",
    "who ",
    "which ",
    "can you",
    "could you",
    "would you",
    "do you",
    "does ",
    "is ",
    "are ",
    "should ",
    "help ",
    "tell me",
)

SPOKEN_STYLE = """
Spoken-audio rules:
- Reply in 1-2 short sentences unless the human explicitly asks for detail.
- No bullet points, markdown, or lists.
- Do not ask a follow-up question unless it is essential.
- Do not summarize the whole meeting unless asked.
"""


def contains_alias(text: str, alias: str) -> bool:
    if " " in alias:
        return alias in text
    return bool(re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE))


def named_addressee(transcript: str) -> str | None:
    """Return agent key if the human named someone directly."""
    lower = transcript.lower()
    for key, aliases in NAME_ALIASES.items():
        if any(contains_alias(lower, alias) for alias in aliases):
            return key
    return None


def is_filler_only(transcript: str) -> bool:
    return bool(FILLER_ONLY.match(transcript.strip()))


def looks_like_question(transcript: str) -> bool:
    text = transcript.strip().lower()
    if "?" in text:
        return True
    return any(text.startswith(starter) for starter in QUESTION_STARTERS)


def is_room_wide(transcript: str) -> bool:
    lower = transcript.lower()
    return any(contains_alias(lower, phrase) for phrase in ROOM_WIDE_ALIASES)


def is_response_worthy(transcript: str) -> bool:
    """Ignore noise, backchannels, and half-formed fragments."""
    text = transcript.strip()
    if not text or is_filler_only(text):
        return False
    if named_addressee(text):
        return True
    if looks_like_question(text):
        return True
    if is_room_wide(text):
        return True
    # Require a little substance before an unnamed agent speaks.
    return len(text.split()) >= 6


def pick_responder(transcript: str, *, default_chair: str = "fred") -> str | None:
    """
    Choose who should reply, or None if the room should stay quiet.

    - Named agent always wins.
    - Room-wide questions go to the chair (Fred by default).
    - Other questions with no addressee also go to the chair.
    - Statements without an addressee do not trigger a reply.
    """
    text = transcript.strip()
    if not is_response_worthy(text):
        return None

    addressee = named_addressee(text)
    if addressee:
        return addressee

    if looks_like_question(text) or is_room_wide(text):
        return default_chair

    return None
