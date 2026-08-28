"""LiveKit room participant adapter."""

from __future__ import annotations

import asyncio
import logging

from livekit import api, rtc

from ai_meeting_room.adapters.voice.elevenlabs_bridge import ElevenLabsVoiceBridge

logger = logging.getLogger(__name__)

AI_IDENTITY_PREFIX = "ai-"


def is_human_participant(identity: str) -> bool:
    """Only forward human microphone audio to ElevenLabs (not other AI agents)."""
    return not identity.startswith(AI_IDENTITY_PREFIX)


class LiveKitParticipant:
    """
    One AI agent as an independent LiveKit room participant.

    Subscribes to human remote audio and forwards directly to ElevenLabs ConvAI.
    """

    def __init__(
        self,
        *,
        identity: str,
        display_name: str,
        livekit_url: str,
        token: str,
        voice_bridge: ElevenLabsVoiceBridge,
    ) -> None:
        self.identity = identity
        self.display_name = display_name
        self._livekit_url = livekit_url
        self._token = token
        self._voice_bridge = voice_bridge
        self._room = rtc.Room()
        self._connected = asyncio.Event()
        self._human_tracks: set[str] = set()

    @property
    def room(self) -> rtc.Room:
        return self._room

    def _on_human_audio_track(self, track: rtc.Track, participant_identity: str) -> None:
        if track.sid in self._human_tracks:
            return
        self._human_tracks.add(track.sid)
        asyncio.create_task(
            self._voice_bridge.pump_human_track(track, participant_identity=participant_identity)
        )
        logger.info("%s now listening to %s", self.display_name, participant_identity)

    async def connect(self) -> None:
        @self._room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if participant.identity == self.identity:
                return
            if not is_human_participant(participant.identity):
                logger.debug(
                    "%s ignoring audio from AI peer %s",
                    self.display_name,
                    participant.identity,
                )
                return
            self._on_human_audio_track(track, participant.identity)

        @self._room.on("participant_connected")
        def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
            if not is_human_participant(participant.identity):
                return
            for pub in participant.track_publications.values():
                if pub.track and pub.kind == rtc.TrackKind.KIND_AUDIO:
                    self._on_human_audio_track(pub.track, participant.identity)

        await self._room.connect(self._livekit_url, self._token)
        await self._voice_bridge.start(self._room, identity=self.identity)

        for participant in self._room.remote_participants.values():
            if not is_human_participant(participant.identity):
                continue
            for pub in participant.track_publications.values():
                if pub.track and pub.kind == rtc.TrackKind.KIND_AUDIO:
                    self._on_human_audio_track(pub.track, participant.identity)

        self._connected.set()
        logger.info("%s joined room as %s", self.display_name, self.identity)

    async def disconnect(self) -> None:
        await self._voice_bridge.close()
        await self._room.disconnect()


def mint_participant_token(
    *,
    api_key: str,
    api_secret: str,
    room_name: str,
    identity: str,
    name: str,
) -> str:
    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
    )
    return token.to_jwt()
