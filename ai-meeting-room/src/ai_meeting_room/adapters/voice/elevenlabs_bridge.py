"""ElevenLabs ConvAI voice bridge for a LiveKit participant."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
from typing import TYPE_CHECKING

import aiohttp
from livekit import rtc

if TYPE_CHECKING:
    from elevenlabs import AsyncElevenLabs

logger = logging.getLogger(__name__)

USER_INPUT_RATE = 16000
AGENT_OUTPUT_RATE = 24000


def _pcm_bytes(frame: rtc.AudioFrame) -> bytes:
    """Raw signed 16-bit little-endian PCM for ElevenLabs user_audio_chunk."""
    return bytes(frame._data)


def _rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    count = len(pcm) // 2
    samples = struct.unpack(f"<{count}h", pcm[: count * 2])
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


class ElevenLabsVoiceBridge:
    """
    Bridges room audio ↔ ElevenLabs conversational AI WebSocket.

    Uses ElevenLabs primitives for STT, TTS, turn-taking, and interruption handling.
    """

    def __init__(self, elevenlabs_client: AsyncElevenLabs, agent_id: str, *, agent_name: str = "") -> None:
        self._client = elevenlabs_client
        self._agent_id = agent_id
        self._agent_name = agent_name
        self._http: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._audio_source: rtc.AudioSource | None = None
        self._pump_task: asyncio.Task | None = None
        self._human_pump_task: asyncio.Task | None = None
        self._chunks_sent = 0

    async def _signed_url(self) -> str:
        response = await self._client.conversational_ai.conversations.get_signed_url(
            agent_id=self._agent_id,
        )
        return response.signed_url

    async def start(self, room: rtc.Room, *, identity: str) -> rtc.LocalAudioTrack:
        self._http = aiohttp.ClientSession()
        signed = await self._signed_url()
        self._ws = await self._http.ws_connect(signed)
        await self._ws.send_str(json.dumps({"type": "conversation_initiation_client_data"}))

        self._audio_source = rtc.AudioSource(sample_rate=AGENT_OUTPUT_RATE, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track(f"{identity}-voice", self._audio_source)
        await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )

        self._pump_task = asyncio.create_task(self._elevenlabs_to_room())
        return track

    async def pump_human_track(self, track: rtc.Track, *, participant_identity: str) -> None:
        """Forward one human microphone track directly to ElevenLabs (official bridge pattern)."""
        if self._human_pump_task:
            self._human_pump_task.cancel()
            try:
                await self._human_pump_task
            except asyncio.CancelledError:
                pass

        async def _run() -> None:
            assert self._ws is not None
            logger.info("%s pumping audio from %s", self._agent_name, participant_identity)
            stream = rtc.AudioStream(track, sample_rate=USER_INPUT_RATE, num_channels=1)
            try:
                async for event in stream:
                    pcm = _pcm_bytes(event.frame)
                    self._chunks_sent += 1
                    if self._chunks_sent % 50 == 0:
                        level = _rms(pcm)
                        logger.info(
                            "%s audio from %s: %d chunks sent, rms=%.0f",
                            self._agent_name,
                            participant_identity,
                            self._chunks_sent,
                            level,
                        )
                    payload = base64.b64encode(pcm).decode()
                    await self._ws.send_str(json.dumps({"user_audio_chunk": payload}))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s human audio pump failed", self._agent_name)

        self._human_pump_task = asyncio.create_task(_run())

    async def _elevenlabs_to_room(self) -> None:
        assert self._ws is not None and self._audio_source is not None
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                event = json.loads(msg.data)
                etype = event.get("type")

                if etype == "audio":
                    pcm = base64.b64decode(event["audio_event"]["audio_base_64"])
                    samples = len(pcm) // 2
                    frame = rtc.AudioFrame(pcm, AGENT_OUTPUT_RATE, 1, samples)
                    await self._audio_source.capture_frame(frame)
                elif etype == "interruption":
                    self._audio_source.clear_queue()
                elif etype == "user_transcript":
                    event_data = event.get("user_transcription_event", event)
                    transcript = event_data.get("user_transcript", "")
                    if isinstance(transcript, list):
                        for item in reversed(transcript):
                            if isinstance(item, dict) and item.get("role") == "user":
                                transcript = item.get("message", "") or item.get("content", "")
                                break
                        else:
                            transcript = ""
                    if transcript:
                        logger.info("%s heard: %s", self._agent_name, transcript)
                elif etype == "agent_response":
                    text = event.get("agent_response_event", {}).get("agent_response", "")
                    if text:
                        logger.info("%s spoke: %s", self._agent_name, text)
                elif etype == "ping":
                    event_id = event.get("ping_event", {}).get("event_id")
                    await self._ws.send_str(json.dumps({"type": "pong", "event_id": event_id}))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s ElevenLabs receive loop failed", self._agent_name)

    async def close(self) -> None:
        for task in (self._pump_task, self._human_pump_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._ws:
            await self._ws.close()
        if self._http:
            await self._http.close()
