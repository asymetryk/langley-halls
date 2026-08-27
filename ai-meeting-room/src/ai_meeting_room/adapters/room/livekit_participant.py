"""LiveKit room participant adapter."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from livekit import api, rtc

from ai_meeting_room.adapters.voice.elevenlabs_bridge import ElevenLabsVoiceBridge

logger = logging.getLogger(__name__)


@dataclass
class RoomTrackHandle:
    track: rtc.Track
    participant_identity: str
    stream_iterator: object | None = None


class LiveKitParticipant:
    """
    One AI agent as an independent LiveKit room participant.

    Subscribes to all remote audio (excluding self), mixes it, and forwards
    to the ElevenLabs voice bridge.
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
        self._mixer: rtc.AudioMixer | None = None
        self._tracks: dict[str, RoomTrackHandle] = {}
        self._connected = asyncio.Event()

    @property
    def room(self) -> rtc.Room:
        return self._room

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
            asyncio.create_task(self._add_track(track, participant.identity))

        @self._room.on("track_unsubscribed")
        def on_track_unsubscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            asyncio.create_task(self._remove_track(track.sid))

        await self._room.connect(self._livekit_url, self._token)
        self._mixer = rtc.AudioMixer(sample_rate=16000, num_channels=1)
        await self._voice_bridge.start(self._room, identity=self.identity)
        await self._voice_bridge.pump_mixed_audio(self._mixer)
        self._connected.set()
        logger.info("%s joined room as %s", self.display_name, self.identity)

    async def _add_track(self, track: rtc.Track, participant_identity: str) -> None:
        if track.sid in self._tracks or self._mixer is None:
            return

        stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)

        async def frame_iter():
            async for event in stream:
                yield event.frame

        iterator = frame_iter()
        self._mixer.add_stream(iterator)
        self._tracks[track.sid] = RoomTrackHandle(
            track=track,
            participant_identity=participant_identity,
            stream_iterator=iterator,
        )
        logger.info("%s now listening to %s", self.display_name, participant_identity)

    async def _remove_track(self, track_sid: str) -> None:
        handle = self._tracks.pop(track_sid, None)
        if handle and self._mixer and handle.stream_iterator:
            self._mixer.remove_stream(handle.stream_iterator)

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
