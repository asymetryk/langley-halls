#!/usr/bin/env python3
"""Create or update ElevenLabs ConvAI agents for the meeting room."""

from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv
from elevenlabs import AsyncElevenLabs

from ai_meeting_room.adapters.secrets import build_secrets_adapter
from ai_meeting_room.agents.definitions import ALL_AGENTS
from ai_meeting_room.config import Settings, get_settings


async def _api_key(settings: Settings) -> str:
    secrets = build_secrets_adapter(settings)
    key = await secrets.get_secret(settings.elevenlabs_secret_name)
    return key or settings.elevenlabs_api_key


async def setup_agents(settings: Settings, *, custom_llm_url: str) -> None:
    api_key = await _api_key(settings)
    if not api_key:
        raise RuntimeError("ElevenLabs API key required")

    client = AsyncElevenLabs(api_key=api_key)

    for agent in ALL_AGENTS:
        config = {
            "name": f"Meeting Room — {agent.display_name}",
            "conversation_config": {
                "agent": {
                    "first_message": f"Hi, {agent.display_name} here. I'm ready for the meeting.",
                    "language": "en",
                    "prompt": {
                        "prompt": agent.system_prompt,
                        "llm": "custom-llm",
                        "custom_llm": {
                            "url": f"{custom_llm_url.rstrip('/')}/v1/chat/completions",
                            "model_id": f"meeting-{agent.key}",
                        },
                    },
                },
                "tts": {"voice_id": agent.voice_id} if agent.voice_id else {},
                "turn": {"mode": "turn"},
                "conversation": {"max_duration_seconds": 3600},
            },
        }

        existing_id = os.environ.get(f"ELEVENLABS_AGENT_ID_{agent.key.upper()}", "")
        if existing_id:
            await client.conversational_ai.agents.update(agent_id=existing_id, **config)
            print(f"Updated {agent.display_name}: {existing_id}")
        else:
            created = await client.conversational_ai.agents.create(**config)
            env_name = f"ELEVENLABS_AGENT_ID_{agent.key.upper()}"
            print(f"Created {agent.display_name}: {created.agent_id}")
            print(f"  Add to .env: {env_name}={created.agent_id}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--custom-llm-url",
        required=True,
        help="Public URL of reasoning API (e.g. https://tunnel.example.com)",
    )
    args = parser.parse_args()
    asyncio.run(setup_agents(get_settings(), custom_llm_url=args.custom_llm_url))


if __name__ == "__main__":
    main()
