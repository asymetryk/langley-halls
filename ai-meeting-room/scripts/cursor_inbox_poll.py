#!/usr/bin/env python3
"""Poll Cursor inbox and print new room messages (for agent hooks / cron)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

DEFAULT_BASE = "http://127.0.0.1:8092"


def fetch_pending(base: str) -> list[dict]:
    response = httpx.get(f"{base}/relay/cursor/pending", timeout=5.0)
    response.raise_for_status()
    return response.json().get("pending", [])


def ack_all(base: str) -> None:
    httpx.post(f"{base}/relay/cursor/ack", json={"msg_ids": []}, timeout=5.0).raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll AI meeting room Cursor inbox")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--once", action="store_true", help="Print pending once and exit")
    parser.add_argument("--ack", action="store_true", help="Ack after printing")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--state", type=Path, default=Path("relay/cursor_poll.state.json"))
    args = parser.parse_args()

    seen: set[str] = set()
    if args.state.exists():
        try:
            seen = set(json.loads(args.state.read_text(encoding="utf-8")).get("seen", []))
        except json.JSONDecodeError:
            seen = set()

    def emit(pending: list[dict]) -> None:
        new_items = [m for m in pending if m.get("id") not in seen]
        for message in new_items:
            print(json.dumps(message, ensure_ascii=False), flush=True)
            if message.get("id"):
                seen.add(message["id"])
        args.state.write_text(json.dumps({"seen": sorted(seen)}, indent=2), encoding="utf-8")
        if args.ack and new_items:
            ack_all(args.base)

    if args.once:
        emit(fetch_pending(args.base))
        return 0

    while True:
        try:
            emit(fetch_pending(args.base))
        except Exception as exc:
            print(f"poll error: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
