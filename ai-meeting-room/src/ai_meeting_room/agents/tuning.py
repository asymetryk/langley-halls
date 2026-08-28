"""Turn-taking and response routing for interactive meetings."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

NAME_ALIASES: dict[str, list[str]] = {
    "fred": ["fred"],
    "missy": ["missy"],
    "architect": ["architect"],
    "project_alpha": ["project alpha", "alpha"],
}

ROOM_WIDE_ALIASES = ("everyone", "team", "anybody", "anyone", "you all", "you guys", "the room")

FILLER_ONLY = re.compile(
    r"^(?:um+|uh+|hmm+|yeah|yep|yup|ok|okay|right|sure|thanks|thank you|got it|cool|nice|alright)[\s.!]*$",
    re.IGNORECASE,
)

CONVERSATION_CLOSE = re.compile(
    r"\b(?:thanks|thank you|that(?:'s| is) all|never mind|nevermind|moving on|we're done|we are done|"
    r"over to you|next topic|change of subject|anyway)\b",
    re.IGNORECASE,
)

SPOKEN_STYLE = """
Spoken-audio rules:
- Reply in 1-2 short sentences unless the human explicitly asks for detail.
- When the human addressed you or is answering your question, talk like a real person in a meeting.
- After your answer, ask ONE short follow-up question when it fits — keep the back-and-forth going.
- If they are answering your last question, respond to what they said; do not re-introduce yourself.
- No bullet points, markdown, or lists.
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


def is_room_wide(transcript: str) -> bool:
    lower = transcript.lower()
    return any(contains_alias(lower, phrase) for phrase in ROOM_WIDE_ALIASES)


def closes_conversation(transcript: str) -> bool:
    return bool(CONVERSATION_CLOSE.search(transcript.strip()))


def is_response_worthy(transcript: str, *, in_active_thread: bool = False) -> bool:
    """Ignore noise and backchannels."""
    text = transcript.strip()
    if not text or is_filler_only(text):
        return False
    if named_addressee(text) or is_room_wide(text):
        return True
    if in_active_thread:
        return len(text.split()) >= 2
    return False


def agent_asked_question(reply: str) -> bool:
    return "?" in reply.strip()


@dataclass
class ConversationState:
    """Tracks who the human is currently talking with in the room."""

    partner_key: str | None = None
    awaiting_reply: bool = False
    last_turn_at: float = field(default_factory=time.monotonic)
    idle_timeout_sec: float = 60.0

    def is_active(self) -> bool:
        if not self.partner_key:
            return False
        return (time.monotonic() - self.last_turn_at) <= self.idle_timeout_sec

    def touch(self, partner_key: str | None, *, awaiting_reply: bool = False) -> None:
        self.partner_key = partner_key
        self.awaiting_reply = awaiting_reply
        self.last_turn_at = time.monotonic()

    def clear(self) -> None:
        self.partner_key = None
        self.awaiting_reply = False
        self.last_turn_at = time.monotonic()


def pick_responder(
    transcript: str,
    *,
    default_chair: str = "project_alpha",
    active_agents: set[str] | None = None,
    conversation: ConversationState | None = None,
) -> str | None:
    """
    Choose who should reply, or None if the room should stay quiet.

    - Named agent always wins (if they are in the room).
    - Room-wide phrases go to the chair.
    - During an active one-on-one, follow-ups go back to the same agent even
      without repeating their name — unless the human names someone else.
    - Unnamed speech with no active thread does not trigger anyone.
    """
    active = active_agents or set(NAME_ALIASES.keys())
    convo = conversation or ConversationState()
    text = transcript.strip()

    if closes_conversation(text):
        convo.clear()
        return None

    addressee = named_addressee(text)
    if addressee:
        if addressee not in active:
            return None
        convo.touch(addressee, awaiting_reply=False)
        return addressee

    if is_room_wide(text):
        if default_chair in active:
            convo.touch(default_chair, awaiting_reply=False)
            return default_chair
        return next(iter(active), None)

    in_thread = convo.is_active() and convo.partner_key in active
    if in_thread and is_response_worthy(text, in_active_thread=True):
        convo.touch(convo.partner_key, awaiting_reply=False)
        return convo.partner_key

    return None


def conversation_prompt_note(
    *,
    agent_key: str,
    conversation: ConversationState,
    transcript: str,
) -> str:
    """Extra LLM context for natural back-and-forth."""
    if conversation.partner_key != agent_key:
        return (
            "The human just addressed you by name in a group room. "
            "Answer them directly, then ask one short follow-up question if natural."
        )
    if conversation.awaiting_reply:
        return (
            "The human is answering your previous question. "
            "Respond to what they said, then ask one brief follow-up if useful."
        )
    if named_addressee(transcript) == agent_key:
        return (
            "The human opened a direct conversation with you. "
            "Answer, then invite them to continue with one short question."
        )
    return "You are mid-conversation with this human. Keep it natural and concise."
