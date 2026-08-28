"""File-based bridge between the LiveKit room and the Cursor thread."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

MessageKind = Literal["human", "agent", "thread_in", "thread_out", "system"]


@dataclass
class RelayMessage:
    id: str
    ts: str
    kind: MessageKind
    speaker: str
    text: str
    spoken: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class RelayStore:
    """Append-only JSONL log the Cursor agent can read/write."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log = self._dir / "messages.jsonl"
        self._inbox = self._dir / "inbox.jsonl"
        self._state = self._dir / "state.json"

    @property
    def directory(self) -> Path:
        return self._dir

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def append(
        self,
        *,
        kind: MessageKind,
        speaker: str,
        text: str,
        spoken: bool = False,
    ) -> RelayMessage:
        message = RelayMessage(
            id=uuid.uuid4().hex[:12],
            ts=self._now(),
            kind=kind,
            speaker=speaker,
            text=text,
            spoken=spoken,
        )
        with self._log.open("a", encoding="utf-8") as handle:
            handle.write(message.to_json() + "\n")
        self._write_state(message)
        return message

    def queue_inbound(self, text: str) -> RelayMessage:
        message = RelayMessage(
            id=uuid.uuid4().hex[:12],
            ts=self._now(),
            kind="thread_in",
            speaker="Cursor",
            text=text,
            spoken=False,
        )
        with self._inbox.open("a", encoding="utf-8") as handle:
            handle.write(message.to_json() + "\n")
        return message

    def pop_unspoken_inbound(self) -> list[RelayMessage]:
        if not self._inbox.exists():
            return []
        lines = [line for line in self._inbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        pending: list[RelayMessage] = []
        updated: list[str] = []
        for line in lines:
            payload = json.loads(line)
            message = RelayMessage(**payload)
            if not message.spoken:
                message.spoken = True
                payload["spoken"] = True
                pending.append(message)
            updated.append(json.dumps(payload, ensure_ascii=False))
        if pending:
            self._inbox.write_text("\n".join(updated) + ("\n" if updated else ""), encoding="utf-8")
        return pending

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._log.exists():
            return []
        lines = self._log.read_text(encoding="utf-8").splitlines()
        items = [json.loads(line) for line in lines[-limit:]]
        return items

    def _write_state(self, message: RelayMessage) -> None:
        state = {
            "updated_at": message.ts,
            "last_speaker": message.speaker,
            "last_text": message.text,
            "last_kind": message.kind,
        }
        self._state.write_text(json.dumps(state, indent=2), encoding="utf-8")
