"""In-room Relay bridge to the Cursor thread."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ai_meeting_room.relay.participant import extract_cursor_message, is_cursor_or_relay_bound
from ai_meeting_room.relay.store import RelayStore

SpeakFn = Callable[[str], Awaitable[None]]
MutedFn = Callable[[], bool]


class RelayBridge:
    def __init__(
        self,
        store: RelayStore,
        speak: SpeakFn,
        *,
        is_muted: MutedFn | None = None,
    ) -> None:
        self._store = store
        self._speak = speak
        self._is_muted = is_muted or (lambda: False)

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

    async def handle_human(self, text: str) -> bool:
        """Handle speech directed at Cursor or Relay. Returns True if consumed."""
        if not is_cursor_or_relay_bound(text):
            return False

        payload = extract_cursor_message(text) or text
        self._store.append(kind="thread_out", speaker="You", text=payload)
        # Silent by default — logging is enough; speaking acks interrupt the host.
        if not self._is_muted():
            pass  # reserved for optional brief ack later
        return True

    async def deliver_from_thread(self, text: str, *, speak: bool) -> None:
        self._store.append(kind="thread_in", speaker="Cursor", text=text, spoken=speak)
        if speak and not self._is_muted():
            await self._speak(text)

    def pop_inbound(self) -> list:
        return self._store.pop_unspoken_inbound()
