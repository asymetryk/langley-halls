"""Tests for Relay addressing."""

import asyncio
from pathlib import Path

from ai_meeting_room.relay.bridge import RelayBridge
from ai_meeting_room.relay.store import RelayStore
from ai_meeting_room.relay.participant import (
    extract_cursor_message,
    is_addressing_cursor,
    is_addressing_relay,
    is_cursor_or_relay_bound,
)


def test_addressing_relay_by_name() -> None:
    assert is_addressing_relay("Relay, tell Cursor we need a dashboard")
    assert is_addressing_relay("Hey bridge pass this along")
    assert not is_addressing_relay("hey cursor pass this along")
    assert not is_addressing_relay("this thread is confusing")
    assert not is_addressing_relay("Missy what do you think?")


def test_addressing_cursor_direct() -> None:
    assert is_addressing_cursor("Cursor, can you hear me?")
    assert is_addressing_cursor("hey Cursor look at the logs")
    assert is_addressing_cursor("ask Cursor for a summary")
    assert is_addressing_cursor("tell Cursor we need a dashboard")
    assert not is_addressing_cursor("Missy what do you think?")
    assert not is_addressing_cursor("does everyone agree with that?")
    assert not is_addressing_cursor("the cursor on this design is too large")


def test_cursor_or_relay_bound_skips_chair_lines() -> None:
    assert is_cursor_or_relay_bound("Cursor, can you hear me?")
    assert is_cursor_or_relay_bound("hey Cursor are you there")
    assert is_cursor_or_relay_bound("Relay, are you there?")
    assert is_cursor_or_relay_bound("Relay tell Cursor we need a dashboard")
    assert not is_cursor_or_relay_bound("does everyone agree with that?")
    assert not is_cursor_or_relay_bound("Missy what do you think?")


def test_extract_cursor_message() -> None:
    assert extract_cursor_message("Relay tell Cursor to mute Fred") == "mute Fred"


def test_handle_human_logs_cursor_direct_without_speaking(tmp_path: Path) -> None:
    store = RelayStore(tmp_path)
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    bridge = RelayBridge(store, speak)

    async def run() -> None:
        assert await bridge.handle_human("Cursor, can you hear me?")
        assert await bridge.handle_human("Hey Relay")
        assert not await bridge.handle_human("does everyone agree with that?")

    asyncio.run(run())
    assert spoken == []
    out = [row for row in store.tail(10) if row["kind"] == "thread_out"]
    assert [row["text"] for row in out] == [
        "Cursor, can you hear me?",
        "Hey Relay",
    ]
