"""Host-side room controls (kick, invite, chair, pause, mute, relay)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from livekit import rtc

from ai_meeting_room.adapters.room.livekit_participant import mint_participant_token
from ai_meeting_room.agents.definitions import ALL_AGENTS, ALL_PARTICIPANTS, RELAY, agent_by_key
from ai_meeting_room.agents.host_commands import all_agent_keys
from ai_meeting_room.demo.speak_demo import OUTPUT_RATE
from ai_meeting_room.memory.store import AgentMemory
from ai_meeting_room.relay.cursor_processor import process_cursor_inbox

if TYPE_CHECKING:
    from ai_meeting_room.demo.interactive_meeting import InteractiveMeeting

logger = logging.getLogger(__name__)


class RoomController:
    """Mutable host controls for a running interactive meeting."""

    def __init__(self, meeting: InteractiveMeeting) -> None:
        self._meeting = meeting

    def _agent_state(self, agent_key: str) -> dict[str, Any]:
        meeting = self._meeting
        agent = agent_by_key(agent_key)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_key}")
        in_call = agent_key in meeting._rooms
        return {
            "key": agent.key,
            "name": agent.display_name,
            "identity": agent.identity,
            "in_call": in_call,
            "excluded": agent_key in meeting._excluded,
            "muted": agent_key in meeting._muted_keys,
            "is_chair": agent_key == meeting._chair_key(),
            "is_relay": agent_key == RELAY.key,
        }

    def roster(self) -> list[dict[str, Any]]:
        return [self._agent_state(agent.key) for agent in ALL_PARTICIPANTS]

    def status(self) -> dict[str, Any]:
        meeting = self._meeting
        chair = meeting._chair_key()
        chair_agent = agent_by_key(chair)
        return {
            "room": meeting._settings.meeting_room_name,
            "paused": meeting._paused,
            "chair": chair,
            "chair_name": chair_agent.display_name if chair_agent else chair,
            "in_call": [a for a in self.roster() if a["in_call"]],
            "roster": self.roster(),
            "excluded": sorted(meeting._excluded),
            "muted": sorted(meeting._muted_keys),
            "relay_enabled": meeting._relay is not None,
            "relay_dir": str(meeting.relay_directory()) if meeting._relay else None,
            "dashboard": f"http://{meeting._settings.room_control_host}:{meeting._settings.room_control_port}/",
        }

    async def kick(self, agent_key: str) -> dict[str, Any]:
        agent_key = agent_key.strip().lower()
        agent = agent_by_key(agent_key)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_key}")
        meeting = self._meeting
        if agent_key not in meeting._rooms:
            return {"ok": True, "message": f"{agent.display_name} is not in the call"}

        room, _source, _agent = meeting._rooms.pop(agent_key)
        await room.disconnect()
        meeting._active_keys.discard(agent_key)
        meeting._muted_keys.discard(agent_key)
        if agent_key != RELAY.key:
            meeting._excluded.add(agent_key)
            meeting._active_agents = tuple(a for a in meeting._active_agents if a.key != agent_key)
        if meeting._relay:
            meeting._relay.append_system(f"{agent.display_name} left the call")
        logger.info("Host kicked %s from the call", agent.display_name)
        return {"ok": True, "message": f"Kicked {agent.display_name} from the call"}

    async def invite(self, agent_key: str) -> dict[str, Any]:
        agent_key = agent_key.strip().lower()
        agent = agent_by_key(agent_key)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_key}")
        meeting = self._meeting
        if agent_key in meeting._rooms:
            return {"ok": True, "message": f"{agent.display_name} is already in the call"}

        room = rtc.Room()
        token = mint_participant_token(
            api_key=meeting._settings.livekit_api_key,
            api_secret=meeting._settings.livekit_api_secret,
            room_name=meeting._settings.meeting_room_name,
            identity=agent.identity,
            name=agent.display_name,
        )
        await room.connect(meeting._settings.livekit_url, token)
        source = rtc.AudioSource(sample_rate=OUTPUT_RATE, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track(f"{agent.identity}-voice", source)
        await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        meeting._rooms[agent_key] = (room, source, agent)
        meeting._active_keys.add(agent_key)
        meeting._excluded.discard(agent_key)
        if agent_key not in meeting._memories and agent_key != RELAY.key:
            meeting._memories[agent_key] = AgentMemory(agent.display_name)
        if agent_key != RELAY.key:
            meeting._active_agents = tuple(
                a for a in ALL_AGENTS if a.key in meeting._active_keys
            )
        if meeting._relay:
            meeting._relay.append_system(f"{agent.display_name} joined the call")
        logger.info("Host invited %s into the call", agent.display_name)
        return {"ok": True, "message": f"Invited {agent.display_name} into the call"}

    async def set_chair(self, agent_key: str) -> dict[str, Any]:
        agent_key = agent_key.strip().lower()
        if agent_key not in all_agent_keys() and agent_key != RELAY.key:
            raise ValueError(f"Unknown agent: {agent_key}")
        if agent_key == RELAY.key:
            raise ValueError("Relay cannot be meeting chair")
        meeting = self._meeting
        if agent_key not in meeting._rooms:
            raise ValueError(f"{agent_key} is not in the call — invite them first")
        meeting._chair_key_override = agent_key
        name = agent_by_key(agent_key).display_name
        logger.info("Host set chair to %s", name)
        return {"ok": True, "message": f"Chair is now {name}"}

    def mute(self, agent_key: str) -> dict[str, Any]:
        agent_key = agent_key.strip().lower()
        agent = agent_by_key(agent_key)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_key}")
        if agent_key not in self._meeting._rooms:
            raise ValueError(f"{agent.display_name} is not in the call")
        self._meeting._muted_keys.add(agent_key)
        logger.info("Host muted %s", agent.display_name)
        return {"ok": True, "message": f"Muted {agent.display_name}"}

    def unmute(self, agent_key: str) -> dict[str, Any]:
        agent_key = agent_key.strip().lower()
        agent = agent_by_key(agent_key)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_key}")
        self._meeting._muted_keys.discard(agent_key)
        logger.info("Host unmuted %s", agent.display_name)
        return {"ok": True, "message": f"Unmuted {agent.display_name}"}

    def pause(self) -> dict[str, Any]:
        self._meeting._paused = True
        logger.info("Host paused agent responses")
        return {"ok": True, "message": "Room paused — agents will not respond"}

    def resume(self) -> dict[str, Any]:
        self._meeting._paused = False
        logger.info("Host resumed agent responses")
        return {"ok": True, "message": "Room resumed — agents are listening again"}

    def relay_messages(self, limit: int = 50) -> dict[str, Any]:
        meeting = self._meeting
        if not meeting._relay:
            return {"messages": [], "directory": None}
        return {
            "messages": meeting._relay.tail(limit),
            "directory": str(meeting.relay_directory()),
        }

    async def relay_say(self, text: str, *, speak: bool = True) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("Message text required")
        meeting = self._meeting
        if not meeting._relay:
            raise ValueError("Relay is not enabled")
        await meeting.deliver_thread_message(text, speak=speak)
        return {"ok": True, "message": "Sent to room via Relay"}

    def cursor_pending(self) -> dict[str, Any]:
        meeting = self._meeting
        if not meeting._cursor_inbox:
            return {"pending": [], "count": 0}
        pending = meeting._cursor_inbox.pending_for_agent()
        return {"pending": pending, "count": len(pending)}

    def cursor_agent_pending(self) -> dict[str, Any]:
        meeting = self._meeting
        if not meeting._cursor_inbox:
            return {"pending": [], "count": 0, "instructions": None}
        pending = meeting._cursor_inbox.pending_for_agent()
        if not pending:
            return {"pending": [], "count": 0, "instructions": None}
        lines = [f"[{m.get('speaker', 'You')}] {m.get('text', '')}" for m in pending]
        return {
            "pending": pending,
            "count": len(pending),
            "instructions": (
                "Execute these meeting-room instructions in this Cloud Agent thread, "
                "then POST /relay/cursor/agent-complete with msg_ids and a short spoken summary."
            ),
            "prompt": "From the AI meeting room:\n" + "\n".join(lines),
        }

    async def cursor_agent_complete(
        self,
        msg_ids: list[str],
        *,
        summary: str,
        speak: bool,
    ) -> dict[str, Any]:
        meeting = self._meeting
        if not meeting._cursor_inbox:
            raise ValueError("Cursor inbox not enabled")
        if not msg_ids:
            raise ValueError("msg_ids required")
        count = meeting._cursor_inbox.mark_agent_executed(msg_ids)
        if summary.strip() and meeting._relay:
            await meeting.deliver_thread_message(summary.strip(), speak=speak)
        return {
            "ok": True,
            "executed": count,
            "message": f"Marked {count} message(s) executed",
        }

    def cursor_ack(self, msg_ids: list[str] | None = None) -> dict[str, Any]:
        meeting = self._meeting
        if not meeting._cursor_inbox:
            return {"ok": True, "acknowledged": 0}
        count = meeting._cursor_inbox.mark_agent_executed(msg_ids)
        return {"ok": True, "acknowledged": count}

    async def cursor_process(self, *, speak: bool = True) -> dict[str, Any]:
        meeting = self._meeting
        if not meeting._cursor_inbox:
            raise ValueError("Cursor inbox not enabled")
        count = await process_cursor_inbox(
            meeting,
            meeting._cursor_inbox,
            meeting._settings,
            speak=speak,
        )
        return {"ok": True, "processed": count, "message": f"Processed {count} inbox message(s)"}
