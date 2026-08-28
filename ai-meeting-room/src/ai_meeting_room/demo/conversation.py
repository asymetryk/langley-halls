"""Orchestrated demo conversation between AI participants."""

from __future__ import annotations

import asyncio
import logging

from ai_meeting_room.agents.definitions import ALL_AGENTS
from ai_meeting_room.orchestrator import MeetingOrchestrator

logger = logging.getLogger(__name__)

KICKOFF = (
    "We're in a live project planning meeting. In two short sentences, introduce yourself "
    "and state your number one priority for this project."
)


async def run_demo_conversation(orchestrator: MeetingOrchestrator, *, rounds: int = 4) -> None:
    """
    Drive a visible meeting: each agent speaks in turn, hearing what prior agents said.
    Uses text injection (user_message) so it works without microphone input.
    """
    bridges = {p.identity: p._voice_bridge for p in orchestrator.participants}
    names = {a.identity: a.display_name for a in ALL_AGENTS}
    order = [a.identity for a in ALL_AGENTS]

    transcript: list[str] = []

    for i, identity in enumerate(order):
        bridge = bridges[identity]
        name = names[identity]

        if not transcript:
            prompt = KICKOFF
        else:
            context = " ".join(transcript[-3:])
            prompt = (
                f"Others in the room have said: {context} "
                f"Now respond as {name} with your perspective in two short sentences."
            )

        logger.info("=== Prompting %s ===", name)
        await bridge.send_user_message(prompt)
        try:
            reply = await bridge.wait_for_speech(timeout=60.0)
            line = f"{name}: {reply}"
            transcript.append(line)
            logger.info("=== %s ===", line)
        except asyncio.TimeoutError:
            logger.warning("%s did not speak within timeout", name)

        await asyncio.sleep(2.0)

    logger.info("Demo conversation complete (%d lines)", len(transcript))
