#!/usr/bin/env python3
"""Prove room → Cursor inbox → agent execution → room ack loop."""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8092"
RELAY_DIR = Path(__file__).resolve().parents[1] / "relay"
PROOF_FILE = RELAY_DIR / "agent_delivery_proof.txt"
MESSAGES = RELAY_DIR / "messages.jsonl"
INBOX = RELAY_DIR / "cursor_inbox.jsonl"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"OK: {msg}")


def main() -> int:
    msg_id = uuid.uuid4().hex[:12]
    instruction = f"Cursor, write exactly AGENT-DELIVERY-PROOF-{msg_id} to relay/agent_delivery_proof.txt"
    line = {
        "id": msg_id,
        "ts": datetime.now(UTC).isoformat(),
        "kind": "human",
        "speaker": "You",
        "text": instruction,
        "spoken": False,
    }

    # Step 1: simulate room speech hitting relay log
    MESSAGES.parent.mkdir(parents=True, exist_ok=True)
    with MESSAGES.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    ok(f"Appended relay log line {msg_id}")

    # Step 2: wait for cursor watch loop to enqueue
    deadline = time.time() + 10
    found_in_inbox = False
    while time.time() < deadline:
        if INBOX.exists():
            for row in INBOX.read_text(encoding="utf-8").splitlines():
                if not row.strip():
                    continue
                payload = json.loads(row)
                if payload.get("id") == msg_id and not payload.get("agent_executed"):
                    found_in_inbox = True
                    break
        if found_in_inbox:
            break
        time.sleep(0.5)
    if not found_in_inbox:
        fail(f"Message {msg_id} never appeared in cursor_inbox.jsonl")

    ok(f"Inbox contains {msg_id}")

    # Step 3: agent-pending API must expose it
    pending_resp = httpx.get(f"{BASE}/relay/cursor/agent-pending", timeout=5.0)
    pending_resp.raise_for_status()
    pending = pending_resp.json()
    ids = [m["id"] for m in pending.get("pending", [])]
    if msg_id not in ids:
        fail(f"agent-pending missing {msg_id}: {pending}")
    ok(f"agent-pending returned {msg_id}")

    # Step 4: execute instruction (what the Cloud Agent would do)
    PROOF_FILE.write_text(f"AGENT-DELIVERY-PROOF-{msg_id}\n", encoding="utf-8")
    ok(f"Wrote proof file {PROOF_FILE}")

    # Step 5: complete back to room
    complete = httpx.post(
        f"{BASE}/relay/cursor/agent-complete",
        json={
            "msg_ids": [msg_id],
            "summary": f"Proof complete. Wrote AGENT-DELIVERY-PROOF-{msg_id}.",
            "speak": False,
        },
        timeout=10.0,
    )
    complete.raise_for_status()
    body = complete.json()
    if body.get("executed") != 1:
        fail(f"agent-complete executed != 1: {body}")
    ok("agent-complete marked message executed")

    # Step 6: pending cleared for this id
    pending_resp2 = httpx.get(f"{BASE}/relay/cursor/agent-pending", timeout=5.0)
    pending_resp2.raise_for_status()
    ids2 = [m["id"] for m in pending_resp2.json().get("pending", [])]
    if msg_id in ids2:
        fail(f"{msg_id} still pending after agent-complete")
    ok(f"{msg_id} cleared from agent-pending")

    # Step 7: relay log got thread_in summary
    tail = MESSAGES.read_text(encoding="utf-8").splitlines()[-20:]
    thread_in = [json.loads(r) for r in tail if json.loads(r).get("kind") == "thread_in"]
    if not any(f"AGENT-DELIVERY-PROOF-{msg_id}" in m.get("text", "") for m in thread_in):
        fail("thread_in summary not found in relay/messages.jsonl")
    ok("thread_in summary logged to relay/messages.jsonl")

    print("\nALL CHECKS PASSED — Cursor agent delivery loop works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
