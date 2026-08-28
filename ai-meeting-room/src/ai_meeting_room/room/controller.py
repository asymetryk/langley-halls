"""Host-side room controls (kick, invite, chair, pause)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from livekit import rtc

from ai_meeting_room.adapters.room.livekit_participant import mint_participant_token
from ai_meeting_room.agents.definitions import ALL_AGENTS, agent_by_key
from ai_meeting_room.agents.host_commands import all_agent_keys
from ai_meeting_room.demo.speak_demo import OUTPUT_RATE
from ai_meeting_room.memory.store import AgentMemory

if TYPE_CHECKING:
    from ai_meeting_room.demo.interactive_meeting import InteractiveMeeting

logger = logging.getLogger(__name__)


class RoomController:
    """Mutable host controls for a running interactive meeting."""

    def __init__(self, meeting: InteractiveMeeting) -> None:
        self._meeting = meeting

    def status(self) -> dict[str, Any]:
        meeting = self._meeting
        in_call = [
            {"key": key, "name": agent.display_name}
            for key, (_room, _source, agent) in meeting._rooms.items()
        ]
        excluded = sorted(meeting._excluded)
        chair = meeting._chair_key()
        chair_name = agent_by_key(chair).display_name if agent_by_key(chair) else chair
        return {
            "room": meeting._settings.meeting_room_name,
            "paused": meeting._paused,
            "chair": chair,
            "chair_name": chair_name,
            "in_call": in_call,
            "excluded": excluded,
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
        meeting._excluded.add(agent_key)
        meeting._active_agents = tuple(a for a in meeting._active_agents if a.key != agent_key)
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
        if agent_key not in meeting._memories:
            meeting._memories[agent_key] = AgentMemory(agent.display_name)
        meeting._active_agents = tuple(
            a for a in ALL_AGENTS if a.key in meeting._active_keys
        )
        logger.info("Host invited %s into the call", agent.display_name)
        return {"ok": True, "message": f"Invited {agent.display_name} into the call"}

    async def set_chair(self, agent_key: str) -> dict[str, Any]:
        agent_key = agent_key.strip().lower()
        if agent_key not in all_agent_keys():
            raise ValueError(f"Unknown agent: {agent_key}")
        meeting = self._meeting
        if agent_key not in meeting._rooms:
            raise ValueError(f"{agent_key} is not in the call — invite them first")
        meeting._chair_key_override = agent_key
        name = agent_by_key(agent_key).display_name
        logger.info("Host set chair to %s", name)
        return {"ok": True, "message": f"Chair is now {name}"}

    def pause(self) -> dict[str, Any]:
        self._meeting._paused = True
        logger.info("Host paused agent responses")
        return {"ok": True, "message": "Room paused — agents will not respond"}

    def resume(self) -> dict[str, Any]:
        self._meeting._paused = False
        logger.info("Host resumed agent responses")
        return {"ok": True, "message": "Room resumed — agents are listening again"}
