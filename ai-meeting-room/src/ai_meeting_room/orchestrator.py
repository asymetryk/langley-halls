"""Meeting room orchestrator — spawns four AI participants."""

from __future__ import annotations

import asyncio
import logging

from elevenlabs import AsyncElevenLabs

from ai_meeting_room.adapters.room.livekit_participant import LiveKitParticipant, mint_participant_token
from ai_meeting_room.adapters.secrets import build_secrets_adapter
from ai_meeting_room.adapters.voice.elevenlabs_bridge import ElevenLabsVoiceBridge
from ai_meeting_room.agents.definitions import ALL_AGENTS, AgentDefinition
from ai_meeting_room.config import Settings
from ai_meeting_room.memory.store import AgentMemory

logger = logging.getLogger(__name__)


def _resolve_elevenlabs_agent_id(agent: AgentDefinition, settings: Settings) -> str:
    mapping = {
        "fred": settings.elevenlabs_agent_id_fred,
        "missy": settings.elevenlabs_agent_id_missy,
        "architect": settings.elevenlabs_agent_id_architect,
        "project_alpha": settings.elevenlabs_agent_id_project_alpha,
    }
    return mapping.get(agent.key, "")


class MeetingOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._participants: list[LiveKitParticipant] = []
        self._memories: dict[str, AgentMemory] = {
            agent.key: AgentMemory(agent.display_name) for agent in ALL_AGENTS
        }

    @property
    def participants(self) -> list[LiveKitParticipant]:
        return self._participants

    @property
    def memories(self) -> dict[str, AgentMemory]:
        return self._memories

    async def _resolve_api_key(self) -> str:
        secrets = build_secrets_adapter(self._settings)
        key = await secrets.get_secret(self._settings.elevenlabs_secret_name)
        if key:
            logger.info("Loaded ElevenLabs API key from secrets adapter")
            return key
        if self._settings.elevenlabs_api_key:
            logger.info("Using ElevenLabs API key from environment")
            return self._settings.elevenlabs_api_key
        raise RuntimeError(
            "ElevenLabs API key not found. Configure Baserow secrets table or ELEVENLABS_API_KEY."
        )

    async def start(self) -> None:
        if not all(
            [
                self._settings.livekit_url,
                self._settings.livekit_api_key,
                self._settings.livekit_api_secret,
            ]
        ):
            raise RuntimeError("LiveKit credentials required: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")

        api_key = await self._resolve_api_key()
        el_client = AsyncElevenLabs(api_key=api_key)

        for agent in ALL_AGENTS:
            agent_id = _resolve_elevenlabs_agent_id(agent, self._settings)
            if not agent_id:
                raise RuntimeError(
                    f"Missing ElevenLabs agent ID for {agent.display_name}. "
                    f"Set ELEVENLABS_AGENT_ID_{agent.key.upper()} or run setup-agents."
                )

            token = mint_participant_token(
                api_key=self._settings.livekit_api_key,
                api_secret=self._settings.livekit_api_secret,
                room_name=self._settings.meeting_room_name,
                identity=agent.identity,
                name=agent.display_name,
            )
            bridge = ElevenLabsVoiceBridge(el_client, agent_id, agent_name=agent.display_name)
            participant = LiveKitParticipant(
                identity=agent.identity,
                display_name=agent.display_name,
                livekit_url=self._settings.livekit_url,
                token=token,
                voice_bridge=bridge,
            )
            self._participants.append(participant)

        await asyncio.gather(*(p.connect() for p in self._participants))
        logger.info(
            "All %d AI participants joined room '%s'",
            len(self._participants),
            self._settings.meeting_room_name,
        )

    async def run_until_cancelled(self) -> None:
        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()

    async def stop(self) -> None:
        await asyncio.gather(*(p.disconnect() for p in self._participants), return_exceptions=True)
        self._participants.clear()
