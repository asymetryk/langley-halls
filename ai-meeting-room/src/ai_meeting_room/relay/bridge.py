"""In-room Relay bridge to the Cursor thread."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ai_meeting_room.relay.participant import extract_cursor_message, is_addressing_relay
from ai_meeting_room.relay.store import RelayStore

if TYPE_CHECKING:
    pass

SpeakFn = Callable[[str], Awaitable[None]]


class RelayBridge:
    def __init__(self, store: RelayStore, speak: SpeakFn) -> None:
        self._store = store
        self._speak = speak

    @property
    def store(self) -> RelayStore:
        return self._store

    def tail(self, limit: int = 50) -> list[dict]:
        return self._store.tail(limit)

    def log_human(self, text: str) -> None:
        self._store.append(kind="human", speaker="You", text=text)

    def log_agent(self, speaker: str, text: str) -> None:
        self._store.append(kind="agent", speaker=speaker, text=text)

    def append_system(self, text: str) -> None:
        self._store.append(kind="system", speaker="Room", text=text)

    def queue_thread_message(self, text: str) -> None:
        self._store.queue_inbound(text)

    def log_thread_out(self, text: str, *, spoken: bool) -> None:
        self._store.append(kind="thread_out", speaker="Cursor", text=text, spoken=spoken)

    async def handle_human(self, text: str) -> bool:
        """Handle speech directed at Relay. Returns True if consumed."""
        if not is_addressing_relay(text):
            return False

        payload = extract_cursor_message(text) or text
        self._store.append(kind="thread_out", speaker="You", text=payload)
        await self._speak("Got it — I'll pass that to Cursor.")
        return True

    async def deliver_from_thread(self, text: str, *, speak: bool) -> None:
        self._store.append(kind="thread_in", speaker="Cursor", text=text, spoken=speak)
        if speak:
            await self._speak(text)

    def pop_inbound(self) -> list:
        return self._store.pop_unspoken_inbound()
