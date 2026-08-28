"""Interactive meeting: human mic → STT → OmniRoute → ElevenLabs TTS → LiveKit."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from livekit import rtc
from livekit.agents import inference
from livekit.agents.stt import SpeechEventType
from livekit.agents.utils import http_context

from ai_meeting_room.adapters.room.livekit_participant import (
    is_human_participant,
    mint_participant_token,
)
from ai_meeting_room.agents.definitions import ALL_AGENTS, AgentDefinition
from ai_meeting_room.config import Settings
from ai_meeting_room.demo.speak_demo import OUTPUT_RATE, _omniroute_line, _play_pcm, _speak_pcm
from ai_meeting_room.memory.store import AgentMemory
from elevenlabs import AsyncElevenLabs

logger = logging.getLogger(__name__)

_NAME_ALIASES: dict[str, list[str]] = {
    "fred": ["fred"],
    "missy": ["missy"],
    "architect": ["architect"],
    "project_alpha": ["project alpha", "alpha"],
}


def pick_responder(transcript: str) -> str:
    """Choose one agent to reply (chair = Fred by default)."""
    text = transcript.lower()
    for key, aliases in _NAME_ALIASES.items():
        if any(alias in text for alias in aliases):
            return key
    return "fred"


class InteractiveMeeting:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._el = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
        self._rooms: dict[str, tuple[rtc.Room, rtc.AudioSource, AgentDefinition]] = {}
        self._memories = {a.key: AgentMemory(a.display_name) for a in ALL_AGENTS}
        self._responding = asyncio.Lock()
        self._listen_room: rtc.Room | None = None

    async def start(self) -> None:
        for agent in ALL_AGENTS:
            room = rtc.Room()
            token = mint_participant_token(
                api_key=self._settings.livekit_api_key,
                api_secret=self._settings.livekit_api_secret,
                room_name=self._settings.meeting_room_name,
                identity=agent.identity,
                name=agent.display_name,
            )
            await room.connect(self._settings.livekit_url, token)
            source = rtc.AudioSource(sample_rate=OUTPUT_RATE, num_channels=1)
            track = rtc.LocalAudioTrack.create_audio_track(f"{agent.identity}-voice", source)
            await room.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
            self._rooms[agent.key] = (room, source, agent)
            logger.info("%s joined (interactive)", agent.display_name)

        self._listen_room = next(iter(self._rooms.values()))[0]
        asyncio.create_task(self._listen_loop())

    async def _listen_loop(self) -> None:
        assert self._listen_room is not None
        room = self._listen_room
        stt = inference.STT(
            model="deepgram/nova-3",
            language="en",
            api_key=self._settings.livekit_api_key,
            api_secret=self._settings.livekit_api_secret,
        )

        human_track: rtc.Track | None = None
        ready = asyncio.Event()

        def attach_human(track: rtc.Track, participant: rtc.RemoteParticipant) -> None:
            nonlocal human_track
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if not is_human_participant(participant.identity):
                return
            human_track = track
            ready.set()
            logger.info("Listening to human: %s (%s)", participant.name or participant.identity, participant.identity)

        @room.on("track_subscribed")
        def on_track(track: rtc.Track, _pub, participant: rtc.RemoteParticipant) -> None:
            attach_human(track, participant)

        @room.on("participant_connected")
        def on_participant(participant: rtc.RemoteParticipant) -> None:
            if not is_human_participant(participant.identity):
                return
            for pub in participant.track_publications.values():
                if pub.kind != rtc.TrackKind.KIND_AUDIO:
                    continue
                if pub.track:
                    attach_human(pub.track, participant)
                else:
                    pub.set_subscribed(True)

        for participant in room.remote_participants.values():
            if not is_human_participant(participant.identity):
                continue
            for pub in participant.track_publications.values():
                if pub.kind != rtc.TrackKind.KIND_AUDIO:
                    continue
                if pub.track:
                    human_track = pub.track
                    ready.set()
                else:
                    pub.set_subscribed(True)

        try:
            await asyncio.wait_for(ready.wait(), timeout=120)
        except asyncio.TimeoutError:
            logger.error("No human participant joined within 120s")
            return
        assert human_track is not None
        logger.info("Human mic connected — starting speech recognition")
        asyncio.create_task(self._announce_ready())

        stt_stream = stt.stream()

        async with stt_stream:

            async def pump_audio() -> None:
                stream = rtc.AudioStream(human_track, sample_rate=16000, num_channels=1)
                async for event in stream:
                    stt_stream.push_frame(event.frame)

            pump_task = asyncio.create_task(pump_audio())
            try:
                async for speech in stt_stream:
                    if speech.type != SpeechEventType.FINAL_TRANSCRIPT:
                        continue
                    if not speech.alternatives:
                        continue
                    text = speech.alternatives[0].text.strip()
                    if not text or len(text) < 2:
                        continue
                    logger.info("Human said: %s", text)
                    asyncio.create_task(self._handle_utterance(text))
            finally:
                pump_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump_task

    async def _announce_ready(self) -> None:
        """Fred tells the human the room is listening."""
        _room, source, agent = self._rooms["fred"]
        text = (
            "I'm listening now. Go ahead and speak — I'll respond. "
            "Or say Missy, Architect, or Project Alpha to reach someone else."
        )
        pcm = await _speak_pcm(self._el, voice_id=agent.voice_id, text=text)
        await _play_pcm(source, pcm)

    async def _handle_utterance(self, text: str) -> None:
        async with self._responding:
            key = pick_responder(text)
            room, source, agent = self._rooms[key]
            memory = self._memories[key]
            memory.remember("You", text)

            history = "\n".join(f"- {s}: {t}" for s, t in memory.as_messages()[-6:])
            user = f"The human in the room said: {text}\n\nRecent context:\n{history}\n\nReply in 1-3 short spoken sentences."

            reply = await _omniroute_line(
                self._settings,
                system=agent.system_prompt,
                user=user,
            )
            memory.remember(agent.display_name, reply)
            logger.info("%s replies: %s", agent.display_name, reply)

            pcm = await _speak_pcm(self._el, voice_id=agent.voice_id, text=reply)
            await _play_pcm(source, pcm)

    async def run_until_cancelled(self) -> None:
        async with http_context.open():
            await self.start()
            await asyncio.Event().wait()

    async def stop(self) -> None:
        for room, _, _ in self._rooms.values():
            await room.disconnect()
