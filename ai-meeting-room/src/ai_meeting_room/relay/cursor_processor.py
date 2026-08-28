"""Process Cursor inbox — generate replies and deliver back to the room."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ai_meeting_room.demo.speak_demo import _omniroute_line
from ai_meeting_room.relay.cursor_watcher import CursorInbox, ForwardMode, is_for_cursor

if TYPE_CHECKING:
    from ai_meeting_room.config import Settings
    from ai_meeting_room.demo.interactive_meeting import InteractiveMeeting

logger = logging.getLogger(__name__)

CURSOR_SYSTEM = """You are the Cursor coding agent. The human is speaking to you from a LiveKit voice meeting via Relay.
Other agents (Fred, Missy, Architect, Project Alpha) are NOT you. Reply as Cursor only.
Keep answers to 1-2 short spoken sentences unless they asked for detail."""


async def process_cursor_inbox(
    meeting: InteractiveMeeting,
    inbox: CursorInbox,
    settings: Settings,
    *,
    speak: bool = True,
) -> int:
    """Reply to pending room messages and mark them delivered."""
    pending = inbox.pending()
    if not pending:
        return 0

    lines = [f"[{m.get('ts', '')}] {m.get('text', '')}" for m in pending[-5:]]
    user = "The human said from the meeting room:\n" + "\n".join(lines)

    try:
        reply = await _omniroute_line(
            settings,
            system=CURSOR_SYSTEM,
            user=user,
            max_tokens=120,
        )
    except Exception:
        logger.exception("Cursor inbox OmniRoute failed")
        return 0

    if meeting._relay:
        meeting._relay.store.append(
            kind="thread_in",
            speaker="Cursor",
            text=reply,
            spoken=speak,
        )

    if speak:
        await meeting.deliver_thread_message(reply, speak=True)

    count = inbox.mark_delivered()
    logger.info("Processed %s cursor inbox message(s): %s", count, reply[:80])
    return count


def backfill_inbox_from_log(inbox: CursorInbox, log_path: Path, *, mode: ForwardMode = "relay") -> int:
    """Scan full relay log for lines not yet in the cursor inbox."""
    if not log_path.exists():
        return 0
    queued = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        kind = payload.get("kind", "")
        text = payload.get("text", "").strip()
        if not text:
            continue
        forward = kind == "thread_out" or (kind == "human" and is_for_cursor(text, mode=mode))
        if forward and inbox.enqueue(
            msg_id=payload["id"],
            ts=payload.get("ts", ""),
            speaker=payload.get("speaker", "You"),
            text=text,
            source_kind=kind,
        ):
            queued += 1
    return queued
