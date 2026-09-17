"""Interactive meeting: human mic → STT → OmniRoute → ElevenLabs TTS → LiveKit."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path

from livekit import rtc
from livekit.agents import inference
from livekit.agents.stt import SpeechEventType
from livekit.agents.utils import http_context

from ai_meeting_room.adapters.room.livekit_participant import (
    is_human_participant,
    mint_participant_token,
)
from ai_meeting_room.agents.definitions import RELAY, AgentDefinition, interactive_agents
from ai_meeting_room.agents.host_commands import HostCommand, parse_host_command
from ai_meeting_room.agents.tuning import (
    ConversationState,
    agent_asked_question,
    conversation_prompt_note,
    pick_responder,
)
from ai_meeting_room.adapters.secrets import resolve_elevenlabs_api_key
from ai_meeting_room.config import Settings
from ai_meeting_room.demo.speak_demo import OUTPUT_RATE, _omniroute_line, _play_pcm, _speak_pcm
from ai_meeting_room.memory.store import AgentMemory
from ai_meeting_room.relay.bridge import RelayBridge
from ai_meeting_room.relay.cursor_processor import backfill_inbox_from_log, process_cursor_inbox
from ai_meeting_room.relay.cursor_watcher import CursorInbox, ForwardMode
from ai_meeting_room.relay.participant import is_cursor_or_relay_bound
from ai_meeting_room.relay.store import RelayStore
from ai_meeting_room.room.controller import RoomController
from ai_meeting_room.stt.normalize import default_stt_keyterms, normalize_transcript
from ai_meeting_room.server.room_control import create_room_control_app
from elevenlabs import AsyncElevenLabs
from uvicorn import Config, Server

logger = logging.getLogger(__name__)


class InteractiveMeeting:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._el: AsyncElevenLabs | None = None
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
        self._muted_keys: set[str] = set()
        self._chair_key_override: str | None = None
        self._cooldown_until = 0.0
        self._debounce_buffer: list[str] = []
        self._debounce_task: asyncio.Task[None] | None = None
        self._relay: RelayBridge | None = None
        self._relay_task: asyncio.Task[None] | None = None
        self._cursor_inbox: CursorInbox | None = None
        self._cursor_watch_task: asyncio.Task[None] | None = None
        self._cursor_process_task: asyncio.Task[None] | None = None
        self._conversation = ConversationState(idle_timeout_sec=settings.conversation_idle_sec)

    def _elevenlabs(self) -> AsyncElevenLabs:
        if self._el is None:
            raise RuntimeError("ElevenLabs client not ready; meeting has not started")
        return self._el

    def relay_directory(self) -> Path:
        relay_path = Path(self._settings.relay_dir)
        if not relay_path.is_absolute():
            relay_path = Path.cwd() / relay_path
        return relay_path

    async def start(self) -> None:
        api_key = await resolve_elevenlabs_api_key(self._settings)
        self._el = AsyncElevenLabs(api_key=api_key)
        if self._excluded:
            logger.info("Excluded from call: %s", ", ".join(sorted(self._excluded)))

        for agent in self._active_agents:
            await self._join_agent(agent)

        if self._settings.relay_enabled:
            await self._start_relay()

        self._listen_room = next(iter(self._rooms.values()))[0]
        asyncio.create_task(self._listen_loop())

    async def _join_agent(self, agent: AgentDefinition) -> None:
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

    async def _start_relay(self) -> None:
        store = RelayStore(self.relay_directory())
        self._relay = RelayBridge(
            store,
            speak=self._speak_as_relay,
            is_muted=lambda: RELAY.key in self._muted_keys,
        )
        await self._join_agent(RELAY)
        # Relay logs silently; start muted so it doesn't interrupt the host.
        self._muted_keys.add(RELAY.key)
        self._relay.append_system("Relay connected to Cursor thread (muted by default)")
        self._cursor_inbox = CursorInbox(self.relay_directory())
        log_path = self.relay_directory() / "messages.jsonl"
        mode: ForwardMode = (
            "all" if self._settings.relay_forward_mode.lower() == "all" else "relay"
        )
        backfilled = backfill_inbox_from_log(self._cursor_inbox, log_path, mode=mode)
        if backfilled:
            logger.info("Backfilled %s message(s) into Cursor inbox", backfilled)
        self._relay_task = asyncio.create_task(self._relay_inbox_loop())
        self._cursor_watch_task = asyncio.create_task(self._cursor_watch_loop())
        if self._settings.cursor_auto_reply_in_room:
            self._cursor_process_task = asyncio.create_task(self._cursor_process_loop())
            logger.info("Cursor auto-reply in room enabled (OmniRoute stub — not real agent)")
        else:
            logger.info("Cursor inbox queues for real Cloud Agent thread (no auto-reply)")
        logger.info("Relay bridge active at %s", store.directory)

    async def _speak_as_relay(self, text: str) -> None:
        if RELAY.key in self._muted_keys:
            logger.info("Relay muted — not speaking: %s", text[:80])
            return
        await self.speak_as(RELAY.key, text)

    async def speak_as(self, agent_key: str, text: str) -> None:
        if agent_key in self._muted_keys:
            logger.info("%s muted — not speaking: %s", agent_key, text[:80])
            return
        if agent_key not in self._rooms:
            raise ValueError(f"{agent_key} is not in the call")
        _room, source, agent = self._rooms[agent_key]
        pcm = await _speak_pcm(self._elevenlabs(), voice_id=agent.voice_id, text=text)
        await _play_pcm(source, pcm)

    async def deliver_thread_message(self, text: str, *, speak: bool) -> None:
        if not self._relay:
            raise ValueError("Relay is not enabled")
        await self._relay.deliver_from_thread(text, speak=speak)

    async def _cursor_watch_loop(self) -> None:
        assert self._cursor_inbox is not None
        log_path = self.relay_directory() / "messages.jsonl"
        mode: ForwardMode = (
            "all" if self._settings.relay_forward_mode.lower() == "all" else "relay"
        )
        while True:
            try:
                queued = self._cursor_inbox.watch_messages_log(log_path, mode=mode)
                if queued:
                    logger.info("Queued %s message(s) for Cursor inbox", queued)
                    pending = self._cursor_inbox.pending_for_agent()
                    newest = pending[-1]["id"] if pending else None
                    self._cursor_inbox.write_agent_wake(
                        pending_count=len(pending),
                        newest_id=newest,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cursor watch loop error")
            await asyncio.sleep(self._settings.relay_cursor_poll_sec)

    async def _cursor_process_loop(self) -> None:
        """Auto-reply to Cursor inbox via OmniRoute + Relay."""
        assert self._cursor_inbox is not None
        while True:
            try:
                pending = self._cursor_inbox.pending()
                if pending:
                    await process_cursor_inbox(
                        self,
                        self._cursor_inbox,
                        self._settings,
                        speak=True,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cursor process loop error")
            await asyncio.sleep(max(2.0, self._settings.relay_cursor_poll_sec))

    async def _relay_inbox_loop(self) -> None:
        assert self._relay is not None
        while True:
            try:
                for message in self._relay.pop_inbound():
                    await self._relay.deliver_from_thread(message.text, speak=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Relay inbox loop error")
            await asyncio.sleep(0.75)

    async def _listen_loop(self) -> None:
        assert self._listen_room is not None
        room = self._listen_room
        stt = inference.STT(
            model="deepgram/nova-3",
            language="en",
            api_key=self._settings.livekit_api_key,
            api_secret=self._settings.livekit_api_secret,
            extra_kwargs={"keyterm": default_stt_keyterms()},
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
                    raw = text
                    text = normalize_transcript(text)
                    if text != raw:
                        logger.info("STT normalized: %r → %r", raw, text)
                    logger.info("Human said: %s", text)
                    if self._relay:
                        self._relay.log_human(text)
                    self._queue_utterance(text)
            finally:
                pump_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump_task

    def _queue_utterance(self, text: str) -> None:
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
        for key in self._rooms:
            if key != RELAY.key:
                return key
        return next(iter(self._rooms))

    def _responding_keys(self) -> set[str]:
        return self._active_keys - self._muted_keys

    async def _announce_ready(self) -> None:
        chair_key = self._chair_key()
        names = ", ".join(a.display_name for a in self._active_agents)
        relay_note = " Relay is in the room but muted — unmute from the dashboard to hear it." if self._relay else ""
        text = (
            f"Room is live. Say someone's name to start a conversation — {names}. "
            f"I won't jump in unless you address me or we're already talking.{relay_note}"
        )
        await self.speak_as(chair_key, text)
        self._cooldown_until = time.monotonic() + self._settings.interactive_cooldown_sec

    async def _handle_utterance(self, text: str) -> None:
        host_cmd = parse_host_command(text)
        if host_cmd:
            await self._execute_host_command(host_cmd)
            return

        if self._relay and is_cursor_or_relay_bound(text):
            # Cursor/Relay-addressed lines never go to pick_responder / chair.
            # Same inbox path as the old muted-Relay log: thread_out, no agent speaks.
            await self._relay.handle_human(text)
            logger.info("Cursor/Relay bound — logged without speaking: %s", text[:80])
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
            active_agents=self._responding_keys(),
            conversation=self._conversation,
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
            convo_note = conversation_prompt_note(
                agent_key=key,
                conversation=self._conversation,
                transcript=text,
            )
            user = (
                f'The human said: "{text}"\n\n'
                f"Conversation context: {convo_note}\n\n"
                f"Recent history with this agent:\n{history}\n\n"
                "Give a brief spoken reply."
            )

            reply = await _omniroute_line(
                self._settings,
                system=agent.system_prompt,
                user=user,
                max_tokens=self._settings.interactive_max_reply_tokens,
            )
            memory.remember(agent.display_name, reply)
            logger.info("%s replies: %s", agent.display_name, reply)
            if self._relay:
                self._relay.log_agent(agent.display_name, reply)

            pcm = await _speak_pcm(self._elevenlabs(), voice_id=agent.voice_id, text=reply)
            await _play_pcm(source, pcm)
            self._conversation.touch(key, awaiting_reply=agent_asked_question(reply))
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
        await self.speak_as(chair_key, message)
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
            "Host dashboard: http://%s:%s/",
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
                if self._relay_task:
                    self._relay_task.cancel()
                if self._cursor_watch_task:
                    self._cursor_watch_task.cancel()
                if self._cursor_process_task:
                    self._cursor_process_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await control_task
                    if self._relay_task:
                        await self._relay_task
                    if self._cursor_watch_task:
                        await self._cursor_watch_task
                    if self._cursor_process_task:
                        await self._cursor_process_task

    async def stop(self) -> None:
        for room, _, _ in self._rooms.values():
            await room.disconnect()
