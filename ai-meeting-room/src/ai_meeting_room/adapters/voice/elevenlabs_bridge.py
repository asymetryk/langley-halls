"""ElevenLabs ConvAI voice bridge for a LiveKit participant."""

from __future__ import annotations

import asyncio
import base64
import contextlib
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
    """Bridges room audio ↔ ElevenLabs conversational AI WebSocket."""

    def __init__(self, elevenlabs_client: AsyncElevenLabs, agent_id: str, *, agent_name: str = "") -> None:
        self._client = elevenlabs_client
        self._agent_id = agent_id
        self._agent_name = agent_name
        self._http: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._audio_source: rtc.AudioSource | None = None
        self._room: rtc.Room | None = None
        self._identity: str = ""
        self._published_track: rtc.LocalAudioTrack | None = None
        self._pump_task: asyncio.Task | None = None
        self._human_pump_task: asyncio.Task | None = None
        self._receive_task: asyncio.Task | None = None
        self._human_track: rtc.Track | None = None
        self._human_identity: str = ""
        self._chunks_sent = 0
        self._last_spoken = asyncio.Queue(maxsize=8)
        self._lock = asyncio.Lock()

    async def _signed_url(self) -> str:
        response = await self._client.conversational_ai.conversations.get_signed_url(
            agent_id=self._agent_id,
        )
        return response.signed_url

    async def _open_ws(self) -> None:
        if self._http is None:
            self._http = aiohttp.ClientSession()
        if self._ws and not self._ws.closed:
            return
        signed = await self._signed_url()
        self._ws = await self._http.ws_connect(signed)
        await self._ws.send_str(json.dumps({"type": "conversation_initiation_client_data"}))
        if self._receive_task:
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task
        self._receive_task = asyncio.create_task(self._elevenlabs_to_room())

    async def start(self, room: rtc.Room, *, identity: str) -> rtc.LocalAudioTrack:
        self._room = room
        self._identity = identity
        if self._audio_source is None:
            self._audio_source = rtc.AudioSource(sample_rate=AGENT_OUTPUT_RATE, num_channels=1)
            self._published_track = rtc.LocalAudioTrack.create_audio_track(f"{identity}-voice", self._audio_source)
            await room.local_participant.publish_track(
                self._published_track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
        await self._open_ws()
        return self._published_track

    async def reconnect(self) -> None:
        async with self._lock:
            if self._ws and not self._ws.closed:
                await self._ws.close()
            self._ws = None
            await self._open_ws()
            if self._human_track:
                await self.pump_human_track(self._human_track, participant_identity=self._human_identity)

    async def send_user_message(self, text: str) -> None:
        async with self._lock:
            if not self._ws or self._ws.closed:
                await self._open_ws()
            assert self._ws is not None
            await self._ws.send_str(json.dumps({"type": "user_message", "text": text}))
            logger.info("%s prompted: %s", self._agent_name, text[:120])

    async def wait_for_speech(self, timeout: float = 45.0) -> str:
        return await asyncio.wait_for(self._last_spoken.get(), timeout=timeout)

    async def pump_human_track(self, track: rtc.Track, *, participant_identity: str) -> None:
        self._human_track = track
        self._human_identity = participant_identity
        if self._human_pump_task:
            self._human_pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._human_pump_task

        async def _run() -> None:
            logger.info("%s pumping audio from %s", self._agent_name, participant_identity)
            stream = rtc.AudioStream(track, sample_rate=USER_INPUT_RATE, num_channels=1)
            try:
                async for event in stream:
                    if not self._ws or self._ws.closed:
                        await self.reconnect()
                    pcm = _pcm_bytes(event.frame)
                    self._chunks_sent += 1
                    payload = base64.b64encode(pcm).decode()
                    try:
                        assert self._ws is not None
                        await self._ws.send_str(json.dumps({"user_audio_chunk": payload}))
                    except (aiohttp.ClientConnectionError, ConnectionResetError):
                        logger.warning("%s WS dropped while pumping; reconnecting", self._agent_name)
                        await self.reconnect()
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
                        with contextlib.suppress(asyncio.QueueFull):
                            self._last_spoken.put_nowait(text)
                elif etype == "ping":
                    event_id = event.get("ping_event", {}).get("event_id")
                    await self._ws.send_str(json.dumps({"type": "pong", "event_id": event_id}))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s ElevenLabs receive loop failed", self._agent_name)

    async def close(self) -> None:
        for task in (self._pump_task, self._human_pump_task, self._receive_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._http:
            await self._http.close()
