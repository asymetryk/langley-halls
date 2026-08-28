"""Tests for Cursor inbox watcher."""

import json
from pathlib import Path

from ai_meeting_room.relay.cursor_watcher import CursorInbox, is_for_cursor


def test_is_for_cursor_relay_mode() -> None:
    assert is_for_cursor("Relay tell Cursor hello", mode="relay")
    assert is_for_cursor("Cursor, are you there?", mode="relay")
    assert not is_for_cursor("Missy what do you think?", mode="relay")


def test_is_for_cursor_all_mode() -> None:
    assert is_for_cursor("just thinking out loud", mode="all")


def test_watch_messages_log(tmp_path: Path) -> None:
    log = tmp_path / "messages.jsonl"
    log.write_text(
        json.dumps(
            {
                "id": "abc123",
                "ts": "t1",
                "kind": "human",
                "speaker": "You",
                "text": "Cursor, ping",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    inbox = CursorInbox(tmp_path)
    queued = inbox.watch_messages_log(log, mode="relay")
    assert queued == 1
    pending = inbox.pending()
    assert len(pending) == 1
    assert pending[0]["text"] == "Cursor, ping"
    assert inbox.mark_agent_executed([pending[0]["id"]]) == 1
    assert inbox.pending_for_agent() == []
