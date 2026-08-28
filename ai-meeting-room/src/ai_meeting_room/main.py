"""CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import httpx
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


async def _cmd_interactive() -> int:
    from ai_meeting_room.agents.definitions import interactive_agents
    from ai_meeting_room.demo.interactive_meeting import InteractiveMeeting

    settings = get_settings()
    active = interactive_agents(excluded_keys=settings.interactive_excluded_keys())
    excluded = settings.interactive_excluded_keys()
    meeting = InteractiveMeeting(settings)
    names = ", ".join(a.display_name for a in active)
    excluded_note = f" (not in call: {', '.join(sorted(excluded))})" if excluded else ""
    logging.getLogger(__name__).info(
        "Interactive mode: your mic → STT → OmniRoute → ElevenLabs TTS. "
        "In the room: %s%s. Name someone or ask a room-wide question. "
        "Host dashboard: http://%s:%s/",
        names,
        excluded_note,
        settings.room_control_host,
        settings.room_control_port,
    )
    try:
        await meeting.run_until_cancelled()
    except KeyboardInterrupt:
        await meeting.stop()
    return 0


async def _cmd_demo() -> int:
    from ai_meeting_room.demo.speak_demo import run_speak_demo

    settings = get_settings()
    logging.getLogger(__name__).info(
        "Running speak demo (OmniRoute + ElevenLabs TTS → LiveKit). Join the room to listen."
    )
    try:
        await run_speak_demo(settings)
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_reasoning_api() -> int:
    settings = get_settings()
    app = create_reasoning_app()
    uvicorn.run(app, host=settings.reasoning_api_host, port=settings.reasoning_api_port, log_level="info")
    return 0


async def _cmd_room(args: argparse.Namespace) -> int:
    from ai_meeting_room.room.client import RoomControlClient, format_status, print_result

    settings = get_settings()
    client = RoomControlClient(settings)

    try:
        if args.room_action == "status":
            print(format_status(await client.status()))
            return 0
        if args.room_action == "kick":
            print_result(await client.kick(args.agent))
            return 0
        if args.room_action == "invite":
            print_result(await client.invite(args.agent))
            return 0
        if args.room_action == "chair":
            print_result(await client.chair(args.agent))
            return 0
        if args.room_action == "pause":
            print_result(await client.pause())
            return 0
        if args.room_action == "resume":
            print_result(await client.resume())
            return 0
        if args.room_action == "mute":
            print_result(await client.mute(args.agent))
            return 0
        if args.room_action == "unmute":
            print_result(await client.unmute(args.agent))
            return 0
        if args.room_action == "relay-tail":
            payload = await client.relay_messages(limit=args.limit)
            for message in payload.get("messages", []):
                print(f"[{message.get('ts')}] {message.get('speaker')}: {message.get('text')}")
            return 0
        if args.room_action == "relay-say":
            print_result(await client.relay_say(args.message, speak=not args.log_only))
            return 0
        if args.room_action == "cursor-pending":
            payload = await client.cursor_pending()
            pending = payload.get("pending", [])
            if not pending:
                print("No pending messages for Cursor.")
                return 0
            for message in pending:
                print(f"[{message.get('ts')}] {message.get('speaker')}: {message.get('text')}")
            return 0
        if args.room_action == "cursor-ack":
            result = await client.cursor_ack()
            print(f"Acknowledged {result.get('acknowledged', 0)} message(s)")
            return 0
    except httpx.ConnectError:
        print(
            "Could not reach the room control API. "
            "Start interactive mode first: python -m ai_meeting_room.main interactive",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        print(f"Room control error ({exc.response.status_code}): {detail}", file=sys.stderr)
        return 1

    print(f"Unknown room action: {args.room_action}", file=sys.stderr)
    return 1


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="AI Meeting Room POC")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="Check configuration and adapters")
    sub.add_parser("run", help="Join all four AI participants to the LiveKit room")
    sub.add_parser("demo", help="Run speak demo: OmniRoute + TTS into LiveKit room")
    sub.add_parser("interactive", help="Listen to your mic and respond via OmniRoute + TTS")
    sub.add_parser("reasoning-api", help="Start Custom LLM server for ElevenLabs agents")

    room = sub.add_parser("room", help="Host controls for a running interactive meeting")
    room_sub = room.add_subparsers(dest="room_action", required=True)
    room_sub.add_parser("status", help="Show who is in the call")
    room_sub.add_parser("pause", help="Pause agent responses")
    room_sub.add_parser("resume", help="Resume agent responses")
    kick = room_sub.add_parser("kick", help="Remove an agent from the call")
    kick.add_argument("agent", help="Agent key or name (fred, missy, architect, project_alpha)")
    invite = room_sub.add_parser("invite", help="Bring an agent into the call")
    invite.add_argument("agent", help="Agent key or name")
    chair = room_sub.add_parser("chair", help="Set the meeting chair")
    chair.add_argument("agent", help="Agent key or name")
    mute = room_sub.add_parser("mute", help="Mute an agent (won't respond)")
    mute.add_argument("agent", help="Agent key or name")
    unmute = room_sub.add_parser("unmute", help="Unmute an agent")
    unmute.add_argument("agent", help="Agent key or name")
    relay_tail = room_sub.add_parser("relay-tail", help="Show relay messages (room ↔ Cursor)")
    relay_tail.add_argument("--limit", type=int, default=30)
    relay_say = room_sub.add_parser("relay-say", help="Send a message into the room via Relay")
    relay_say.add_argument("message", help="Text for Relay to speak or log")
    relay_say.add_argument("--log-only", action="store_true", help="Log to relay without speaking")
    room_sub.add_parser("cursor-pending", help="Show room messages waiting for Cursor")
    room_sub.add_parser("cursor-ack", help="Mark all cursor inbox messages as delivered")

    args = parser.parse_args()
    _configure_logging(args.verbose)

    if args.command == "validate":
        sys.exit(asyncio.run(_cmd_validate()))
    if args.command == "run":
        sys.exit(asyncio.run(_cmd_run()))
    if args.command == "demo":
        sys.exit(asyncio.run(_cmd_demo()))
    if args.command == "interactive":
        sys.exit(asyncio.run(_cmd_interactive()))
    if args.command == "reasoning-api":
        sys.exit(_cmd_reasoning_api())
    if args.command == "room":
        sys.exit(asyncio.run(_cmd_room(args)))


if __name__ == "__main__":
    main()
