"""CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn
from dotenv import load_dotenv

from ai_meeting_room.adapters.reasoning import build_reasoning_adapter
from ai_meeting_room.adapters.secrets import build_secrets_adapter
from ai_meeting_room.agents.definitions import ALL_AGENTS
from ai_meeting_room.config import get_settings
from ai_meeting_room.orchestrator import MeetingOrchestrator
from ai_meeting_room.server.reasoning_api import create_reasoning_app


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def _cmd_validate() -> int:
    settings = get_settings()
    print("AI Meeting Room — validation")
    print("-" * 40)

    secrets = build_secrets_adapter(settings)
    el_key = await secrets.get_secret(settings.elevenlabs_secret_name)
    print(f"Baserow/env ElevenLabs key: {'found' if el_key else 'missing'}")

    try:
        adapter = build_reasoning_adapter(
            settings.reasoning_provider,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
        print(f"Reasoning adapter: {type(adapter).__name__} ({settings.reasoning_provider})")
    except ValueError as exc:
        print(f"Reasoning adapter: ERROR — {exc}")
        return 1

    print(f"LiveKit URL: {settings.livekit_url or '(not set)'}")
    print(f"Room: {settings.meeting_room_name}")
    print(f"Agents: {', '.join(a.display_name for a in ALL_AGENTS)}")

    agent_ids = {
        "Fred": settings.elevenlabs_agent_id_fred,
        "Missy": settings.elevenlabs_agent_id_missy,
        "Architect": settings.elevenlabs_agent_id_architect,
        "Project Alpha": settings.elevenlabs_agent_id_project_alpha,
    }
    for name, agent_id in agent_ids.items():
        print(f"  {name} ElevenLabs agent: {'set' if agent_id else 'missing'}")

    print("-" * 40)
    print("Validation complete.")
    return 0


async def _cmd_run() -> int:
    orchestrator = MeetingOrchestrator(get_settings())
    try:
        await orchestrator.run_until_cancelled()
    except KeyboardInterrupt:
        await orchestrator.stop()
    return 0


def _cmd_reasoning_api() -> int:
    settings = get_settings()
    app = create_reasoning_app()
    uvicorn.run(app, host=settings.reasoning_api_host, port=settings.reasoning_api_port, log_level="info")
    return 0


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="AI Meeting Room POC")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="Check configuration and adapters")
    sub.add_parser("run", help="Join all four AI participants to the LiveKit room")
    sub.add_parser("reasoning-api", help="Start Custom LLM server for ElevenLabs agents")

    args = parser.parse_args()
    _configure_logging(args.verbose)

    if args.command == "validate":
        sys.exit(asyncio.run(_cmd_validate()))
    if args.command == "run":
        sys.exit(asyncio.run(_cmd_run()))
    if args.command == "reasoning-api":
        sys.exit(_cmd_reasoning_api())


if __name__ == "__main__":
    main()
