"""Tests for Relay addressing."""

from ai_meeting_room.relay.participant import extract_cursor_message, is_addressing_relay


def test_addressing_relay() -> None:
    assert is_addressing_relay("Relay, tell Cursor we need a dashboard")
    assert is_addressing_relay("hey cursor pass this along")
    assert not is_addressing_relay("Missy what do you think?")


def test_extract_cursor_message() -> None:
    assert extract_cursor_message("Relay tell Cursor to mute Fred") == "to mute Fred"
    assert extract_cursor_message("cursor, send this: build the GUI") == "build the GUI"
