#!/usr/bin/env python3
"""
One-shot bootstrap: validate credentials, probe OmniRoute, create ElevenLabs agents,
write agent IDs back to .env.

Run from ai-meeting-room/:
  PYTHONPATH=src python3 scripts/bootstrap.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _load_env() -> None:
    load_dotenv(ENV_PATH)
    load_dotenv(ROOT.parent / ".env")  # fallback: /agent/.env


def _read_env() -> str:
    if ENV_PATH.exists():
        return ENV_PATH.read_text()
    return ""


def _upsert_env(lines: dict[str, str]) -> None:
    content = _read_env()
    for key, value in lines.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        entry = f"{key}={value}"
        if pattern.search(content):
            content = pattern.sub(entry, content)
        else:
            content = content.rstrip() + "\n" + entry + "\n"
    ENV_PATH.write_text(content)


async def _probe_omniroute(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    if not api_key:
        return False, "OMNIROUTE_API_KEY not set"
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": True,
                },
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    return False, f"HTTP {response.status_code}: {body[:200]!r}"
                chunk = b""
                async for part in response.aiter_bytes():
                    chunk += part
                    if len(chunk) > 80:
                        break
                if b"data:" in chunk or b"choices" in chunk:
                    return True, "streaming OK"
                return False, f"unexpected response: {chunk[:200]!r}"
    except Exception as exc:
        return False, str(exc)


async def _probe_elevenlabs(api_key: str) -> tuple[bool, str]:
    from elevenlabs import AsyncElevenLabs

    client = AsyncElevenLabs(api_key=api_key)
    try:
        await client.conversational_ai.agents.list()
        return True, "convai_read OK"
    except Exception as exc:
        msg = str(exc)
        if "convai_read" in msg or "convai_write" in msg:
            return False, "API key missing ConvAI permissions (need convai_read + convai_write)"
        return False, msg


async def main() -> int:
    _load_env()
    sys.path.insert(0, str(ROOT / "src"))

    from ai_meeting_room.config import get_settings
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "setup_elevenlabs_agents", ROOT / "scripts" / "setup_elevenlabs_agents.py"
    )
    setup_mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(setup_mod)

    settings = get_settings()
    print("AI Meeting Room — bootstrap")
    print("=" * 50)

    blockers: list[str] = []

    # LiveKit
    if settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret:
        print("✓ LiveKit credentials present")
    else:
        blockers.append("LiveKit: set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")

    # ElevenLabs
    from ai_meeting_room.adapters.secrets import resolve_elevenlabs_api_key

    el_key = await resolve_elevenlabs_api_key(settings, required=False)

    if el_key:
        ok, msg = await _probe_elevenlabs(el_key)
        print(f"{'✓' if ok else '✗'} ElevenLabs: {msg}")
        if not ok:
            blockers.append(
                "ElevenLabs: create a new API key at elevenlabs.io → API Keys "
                "with Conversational AI (convai_read + convai_write) enabled, "
                "then update ELEVENLABS_API_KEY in .env"
            )
    else:
        blockers.append("ElevenLabs: set ELEVENLABS_API_KEY in .env")

    # OmniRoute
    ok, msg = await _probe_omniroute(
        settings.omniroute_base_url, settings.omniroute_api_key, settings.omniroute_model
    )
    print(f"{'✓' if ok else '✗'} OmniRoute: {msg}")
    if not ok:
        blockers.append("OmniRoute: set OMNIROUTE_API_KEY in .env (Bearer token for omniroute-api.asymetryk.com)")

    if blockers:
        print("\nBlocked — fix these, then re-run bootstrap:")
        for i, b in enumerate(blockers, 1):
            print(f"  {i}. {b}")
        return 1

    # Create agents
    print("\nCreating ElevenLabs agents…")
    await setup_mod.setup_agents(settings)

    # Pull agent IDs from env if user already had them; bootstrap can't capture print output easily
    # Re-list and write IDs
    from elevenlabs import AsyncElevenLabs

    client = AsyncElevenLabs(api_key=el_key)
    listing = await client.conversational_ai.agents.list()
    updates: dict[str, str] = {}
    from ai_meeting_room.agents.definitions import ALL_AGENTS

    for agent_def in ALL_AGENTS:
        prefix = f"Meeting Room — {agent_def.display_name}"
        for a in listing.agents or []:
            if a.name == prefix:
                env_name = f"ELEVENLABS_AGENT_ID_{agent_def.key.upper()}"
                updates[env_name] = a.agent_id
                print(f"✓ {agent_def.display_name}: {a.agent_id}")

    if updates:
        _upsert_env(updates)
        print(f"\nWrote agent IDs to {ENV_PATH}")

    print("\nBootstrap complete. Start the meeting:")
    print(f"  cd {ROOT} && PYTHONPATH=src python3 -m ai_meeting_room.main run")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
