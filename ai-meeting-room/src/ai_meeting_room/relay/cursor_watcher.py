"""Watch relay log and queue room messages for the Cursor agent."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ai_meeting_room.relay.participant import is_addressing_relay

ForwardMode = Literal["relay", "all"]

CURSOR_ADDRESS = re.compile(r"^(?:hey\s+)?cursor\b", re.IGNORECASE)
TELL_CURSOR = re.compile(r"\btell\s+cursor\b", re.IGNORECASE)


@dataclass
class CursorInboxMessage:
    id: str
    ts: str
    speaker: str
    text: str
    source_kind: str
    delivered: bool = False
    agent_executed: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def is_for_cursor(text: str, *, mode: ForwardMode) -> bool:
    if mode == "all":
        return True
    if is_addressing_relay(text):
        return True
    stripped = text.strip()
    if CURSOR_ADDRESS.match(stripped):
        return True
    if TELL_CURSOR.search(stripped):
        return True
    return False


class CursorInbox:
    """Pending messages from the room waiting for the Cursor agent."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._inbox = self._dir / "cursor_inbox.jsonl"
        self._offset_file = self._dir / "watcher.offset"
        self._seen_ids: set[str] = set()
        self._load_seen()

    @property
    def path(self) -> Path:
        return self._inbox

    def _load_seen(self) -> None:
        if not self._inbox.exists():
            return
        for line in self._inbox.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            self._seen_ids.add(payload["id"])

    def read_log_offset(self) -> int:
        if not self._offset_file.exists():
            return 0
        try:
            return int(self._offset_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return 0

    def write_log_offset(self, offset: int) -> None:
        self._offset_file.write_text(str(offset), encoding="utf-8")

    def enqueue(self, *, msg_id: str, ts: str, speaker: str, text: str, source_kind: str) -> bool:
        if msg_id in self._seen_ids:
            return False
        message = CursorInboxMessage(
            id=msg_id,
            ts=ts,
            speaker=speaker,
            text=text,
            source_kind=source_kind,
        )
        with self._inbox.open("a", encoding="utf-8") as handle:
            handle.write(message.to_json() + "\n")
        self._seen_ids.add(msg_id)
        return True

    def write_agent_wake(self, *, pending_count: int, newest_id: str | None = None) -> None:
        """Signal that the Cloud Agent should poll agent-pending."""
        wake = {
            "pending_count": pending_count,
            "newest_id": newest_id,
            "ts": datetime.now(UTC).isoformat(),
            "poll_url": "http://127.0.0.1:8092/relay/cursor/agent-pending",
            "complete_url": "http://127.0.0.1:8092/relay/cursor/agent-complete",
        }
        (self._dir / "cursor_agent_wake.json").write_text(
            json.dumps(wake, indent=2),
            encoding="utf-8",
        )

    def pending(self) -> list[dict[str, Any]]:
        """Legacy alias — messages still waiting for the real Cursor agent."""
        return self.pending_for_agent()

    def pending_for_agent(self) -> list[dict[str, Any]]:
        if not self._inbox.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in self._inbox.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not payload.get("agent_executed"):
                items.append(payload)
        return items

    def mark_agent_executed(self, msg_ids: list[str] | None = None) -> int:
        if not self._inbox.exists():
            return 0
        lines = self._inbox.read_text(encoding="utf-8").splitlines()
        updated: list[str] = []
        count = 0
        for line in lines:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not payload.get("agent_executed") and (msg_ids is None or payload["id"] in msg_ids):
                payload["agent_executed"] = True
                payload["delivered"] = True
                count += 1
            updated.append(json.dumps(payload, ensure_ascii=False))
        self._inbox.write_text("\n".join(updated) + ("\n" if updated else ""), encoding="utf-8")
        return count

    def mark_delivered(self, msg_ids: list[str] | None = None) -> int:
        if not self._inbox.exists():
            return 0
        lines = self._inbox.read_text(encoding="utf-8").splitlines()
        updated: list[str] = []
        count = 0
        for line in lines:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not payload.get("delivered") and (msg_ids is None or payload["id"] in msg_ids):
                payload["delivered"] = True
                count += 1
            updated.append(json.dumps(payload, ensure_ascii=False))
        self._inbox.write_text("\n".join(updated) + ("\n" if updated else ""), encoding="utf-8")
        return count

    def watch_messages_log(self, log_path: Path, *, mode: ForwardMode) -> int:
        """Scan new relay log lines and enqueue cursor-bound messages."""
        if not log_path.exists():
            return 0
        data = log_path.read_bytes()
        offset = self.read_log_offset()
        if offset > len(data):
            offset = 0
        chunk = data[offset:]
        if not chunk:
            return 0

        new_text = chunk.decode("utf-8")
        queued = 0
        for line in new_text.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            kind = payload.get("kind", "")
            text = payload.get("text", "").strip()
            if not text:
                continue

            forward = False
            if kind == "thread_out":
                forward = True
            elif kind == "human" and is_for_cursor(text, mode=mode):
                forward = True

            if forward and self.enqueue(
                msg_id=payload["id"],
                ts=payload.get("ts", ""),
                speaker=payload.get("speaker", "You"),
                text=text,
                source_kind=kind,
            ):
                queued += 1

        self.write_log_offset(len(data))
        return queued
