"""Tests for STT transcript normalization."""

from ai_meeting_room.stt.normalize import normalize_transcript


def test_relay_mishearings() -> None:
    assert normalize_transcript("Really, tell Cursor to commit") == "Relay, tell Cursor to commit"
    assert normalize_transcript("Hey replay, are you there?") == "Hey Relay, are you there?"
    assert normalize_transcript("Relief, pass this along") == "Relay, pass this along"


def test_cursor_mishearings() -> None:
    assert normalize_transcript("Curser, check the repo") == "Cursor, check the repo"
    assert normalize_transcript("Hey Kerr sir, status?") == "Hey Cursor, status?"
    assert normalize_transcript("tell curser to push") == "tell Cursor to push"


def test_agent_mishearings() -> None:
    assert normalize_transcript("Missie, thoughts?") == "Missy, thoughts?"
    assert normalize_transcript("Project alfa, what's next?") == "Project Alpha, what's next?"


def test_unchanged_normal_speech() -> None:
    assert normalize_transcript("I really like this idea") == "I really like this idea"
    assert normalize_transcript("the cursor on screen") == "the cursor on screen"
