"""Interactive meeting: human mic → STT → OmniRoute → ElevenLabs TTS → LiveKit."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from livekit import rtc
from livekit.agents import inference
from livekit.agents.stt import SpeechEventType
from livekit.agents.utils import http_context

from ai_meeting_room.adapters.room.livekit_participant import (
    is_human_participant,
    mint_participant_token,
)
from ai_meeting_room.agents.definitions import AgentDefinition, interactive_agents
from ai_meeting_room.agents.host_commands import HostCommand, parse_host_command
from ai_meeting_room.agents.tuning import pick_responder
from ai_meeting_room.config import Settings
from ai_meeting_room.demo.speak_demo import OUTPUT_RATE, _omniroute_line, _play_pcm, _speak_pcm
from ai_meeting_room.memory.store import AgentMemory
from ai_meeting_room.room.controller import RoomController
from ai_meeting_room.server.room_control import create_room_control_app
from elevenlabs import AsyncElevenLabs
from uvicorn import Config, Server

logger = logging.getLogger(__name__)


class InteractiveMeeting:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._el = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
        self._excluded = settings.interactive_excluded_keys()
        self._active_agents = interactive_agents(excluded_keys=self._excluded)
        if not self._active_agents:
            raise RuntimeError("No agents available for interactive meeting")
        self._active_keys = {agent.key for agent in self._active_agents}
        self._rooms: dict[str, tuple[rtc.Room, rtc.AudioSource, AgentDefinition]] = {}
        self._memories = {a.key: AgentMemory(a.display_name) for a in self._active_agents}
        self._listen_room: rtc.Room | None = None
        self._responding = False
        self._paused = False
        self._chair_key_override: str | None = None
        self._cooldown_until = 0.0
        self._debounce_buffer: list[str] = []
        self._debounce_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._excluded:
            logger.info("Excluded from call: %s", ", ".join(sorted(self._excluded)))

        for agent in self._active_agents:
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
            logger.info(
                "Listening to human: %s (%s)",
                participant.name or participant.identity,
                participant.identity,
            )

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
                    self._queue_utterance(text)
            finally:
                pump_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump_task

    def _queue_utterance(self, text: str) -> None:
        """Debounce rapid STT finals into one utterance."""
        self._debounce_buffer.append(text)
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._flush_debounce())

    async def _flush_debounce(self) -> None:
        try:
            await asyncio.sleep(self._settings.interactive_debounce_sec)
        except asyncio.CancelledError:
            return
        if not self._debounce_buffer:
            return
        merged = " ".join(self._debounce_buffer).strip()
        self._debounce_buffer.clear()
        await self._handle_utterance(merged)

    def _chair_key(self) -> str:
        if self._chair_key_override and self._chair_key_override in self._rooms:
            return self._chair_key_override
        chair = self._settings.interactive_default_chair
        if chair in self._rooms:
            return chair
        return next(iter(self._rooms))

    async def _announce_ready(self) -> None:
        """Short room cue from the chair — agents stay quiet until addressed."""
        chair_key = self._chair_key()
        _room, source, agent = self._rooms[chair_key]
        names = ", ".join(a.display_name for a in self._active_agents)
        text = f"Room is live. Say a name to reach someone — {names}."
        pcm = await _speak_pcm(self._el, voice_id=agent.voice_id, text=text)
        await _play_pcm(source, pcm)
        self._cooldown_until = time.monotonic() + self._settings.interactive_cooldown_sec

    async def _handle_utterance(self, text: str) -> None:
        host_cmd = parse_host_command(text)
        if host_cmd:
            await self._execute_host_command(host_cmd)
            return

        if self._paused:
            logger.info("Room paused, ignoring: %s", text)
            return
        if time.monotonic() < self._cooldown_until:
            logger.debug("Cooldown active, ignoring: %s", text)
            return
        if self._responding:
            logger.debug("Already responding, ignoring: %s", text)
            return

        key = pick_responder(
            text,
            default_chair=self._chair_key(),
            active_agents=self._active_keys,
        )
        if key is None:
            logger.info("No response warranted for: %s", text)
            return
        if key not in self._rooms:
            logger.info("Addressee not in call (%s): %s", key, text)
            return

        self._responding = True
        try:
            _room, source, agent = self._rooms[key]
            memory = self._memories[key]
            memory.remember("You", text)

            history = "\n".join(f"- {s}: {t}" for s, t in memory.as_messages()[-6:])
            user = (
                f'The human said: "{text}"\n\n'
                f"Recent context:\n{history}\n\n"
                "Give a brief spoken reply. Do not take over the conversation."
            )

            reply = await _omniroute_line(
                self._settings,
                system=agent.system_prompt,
                user=user,
                max_tokens=self._settings.interactive_max_reply_tokens,
            )
            memory.remember(agent.display_name, reply)
            logger.info("%s replies: %s", agent.display_name, reply)

            pcm = await _speak_pcm(self._el, voice_id=agent.voice_id, text=reply)
            await _play_pcm(source, pcm)
        finally:
            self._responding = False
            self._cooldown_until = time.monotonic() + self._settings.interactive_cooldown_sec

    async def _execute_host_command(self, command: HostCommand) -> None:
        controller = RoomController(self)
        try:
            if command.action == "status":
                payload = controller.status()
                message = self._format_status_message(payload)
            elif command.action == "kick":
                assert command.agent_key
                payload = await controller.kick(command.agent_key)
                message = payload["message"]
            elif command.action == "invite":
                assert command.agent_key
                payload = await controller.invite(command.agent_key)
                message = payload["message"]
            elif command.action == "chair":
                assert command.agent_key
                payload = await controller.set_chair(command.agent_key)
                message = payload["message"]
            elif command.action == "pause":
                payload = controller.pause()
                message = payload["message"]
            elif command.action == "resume":
                payload = controller.resume()
                message = payload["message"]
            else:
                return
        except ValueError as exc:
            message = str(exc)

        logger.info("Host command %s → %s", command.action, message)
        await self._speak_host_ack(message)

    def _format_status_message(self, payload: dict) -> str:
        names = ", ".join(a["name"] for a in payload.get("in_call", [])) or "no one"
        chair = payload.get("chair_name", "unknown")
        paused = "paused" if payload.get("paused") else "live"
        return f"Room is {paused}. Chair is {chair}. In the call: {names}."

    async def _speak_host_ack(self, message: str) -> None:
        chair_key = self._chair_key()
        if chair_key not in self._rooms:
            logger.info("Host ack (no speaker in room): %s", message)
            return
        _room, source, agent = self._rooms[chair_key]
        pcm = await _speak_pcm(self._el, voice_id=agent.voice_id, text=message)
        await _play_pcm(source, pcm)
        self._cooldown_until = time.monotonic() + self._settings.interactive_cooldown_sec

    async def _run_control_server(self) -> None:
        controller = RoomController(self)
        app = create_room_control_app(controller)
        config = Config(
            app,
            host=self._settings.room_control_host,
            port=self._settings.room_control_port,
            log_level="info",
        )
        server = Server(config)
        logger.info(
            "Host control API on http://%s:%s",
            self._settings.room_control_host,
            self._settings.room_control_port,
        )
        await server.serve()

    async def run_until_cancelled(self) -> None:
        async with http_context.open():
            await self.start()
            control_task = asyncio.create_task(self._run_control_server())
            try:
                await asyncio.Event().wait()
            finally:
                control_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await control_task

    async def stop(self) -> None:
        for room, _, _ in self._rooms.values():
            await room.disconnect()
