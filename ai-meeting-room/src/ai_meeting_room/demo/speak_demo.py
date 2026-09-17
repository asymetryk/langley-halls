"""Fallback speak demo: OmniRoute text + ElevenLabs TTS into LiveKit (no ConvAI)."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from elevenlabs import AsyncElevenLabs
from livekit import rtc

from ai_meeting_room.adapters.room.livekit_participant import mint_participant_token
from ai_meeting_room.adapters.secrets import resolve_elevenlabs_api_key
from ai_meeting_room.agents.definitions import ALL_AGENTS
from ai_meeting_room.config import Settings

logger = logging.getLogger(__name__)

OUTPUT_RATE = 24000


async def _omniroute_line(
    settings: Settings,
    *,
    system: str,
    user: str,
    max_tokens: int = 120,
) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.omniroute_base_url.rstrip('/')}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.omniroute_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.omniroute_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


async def _speak_pcm(client: AsyncElevenLabs, *, voice_id: str, text: str) -> bytes:
    chunks: list[bytes] = []
    stream = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_turbo_v2_5",
        output_format="pcm_24000",
    )
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


async def _play_pcm(source: rtc.AudioSource, pcm: bytes) -> None:
    frame_size = OUTPUT_RATE // 10  # 100ms
    sample_bytes = frame_size * 2
    for offset in range(0, len(pcm) - sample_bytes + 1, sample_bytes):
        chunk = pcm[offset : offset + sample_bytes]
        frame = rtc.AudioFrame(chunk, OUTPUT_RATE, 1, frame_size)
        await source.capture_frame(frame)
        await asyncio.sleep(0.08)


async def run_speak_demo(settings: Settings) -> None:
    api_key = await resolve_elevenlabs_api_key(settings)
    if not settings.omniroute_api_key:
        raise RuntimeError("OMNIROUTE_API_KEY required")

    el = AsyncElevenLabs(api_key=api_key)
    rooms: list[tuple[str, rtc.Room, rtc.AudioSource]] = []
    transcript: list[str] = []

    try:
        for agent in ALL_AGENTS:
            room = rtc.Room()
            token = mint_participant_token(
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
                room_name=settings.meeting_room_name,
                identity=agent.identity,
                name=agent.display_name,
            )
            await room.connect(settings.livekit_url, token)
            source = rtc.AudioSource(sample_rate=OUTPUT_RATE, num_channels=1)
            track = rtc.LocalAudioTrack.create_audio_track(f"{agent.identity}-voice", source)
            await room.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
            rooms.append((agent.display_name, room, source))
            logger.info("%s joined room", agent.display_name)

        await asyncio.sleep(2)

        for agent in ALL_AGENTS:
            name = agent.display_name
            source = next(s for n, _, s in rooms if n == name)
            context = " ".join(transcript[-2:]) if transcript else ""
            user = (
                "Start a project planning meeting. Introduce yourself in two sentences and "
                "give your top priority."
                if not context
                else f"Others said: {context} Respond in two sentences as {name}."
            )
            text = await _omniroute_line(settings, system=agent.system_prompt, user=user)
            transcript.append(f"{name}: {text}")
            logger.info("LINE %s", transcript[-1])
            pcm = await _speak_pcm(el, voice_id=agent.voice_id, text=text)
            await _play_pcm(source, pcm)
            await asyncio.sleep(1.5)

        logger.info("Speak demo complete — agents will stay in room for 5 minutes")
        await asyncio.sleep(300)
    finally:
        for _, room, _ in rooms:
            await room.disconnect()
