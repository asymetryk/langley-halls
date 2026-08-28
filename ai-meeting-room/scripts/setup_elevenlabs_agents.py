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


def _custom_llm_config(settings: Settings, *, llm_base_url: str) -> dict:
    """Build ElevenLabs custom_llm block pointing at OmniRoute (or any OpenAI-compatible host)."""
    custom_llm: dict = {
        "url": f"{llm_base_url.rstrip('/')}/v1/chat/completions",
        "model_id": settings.omniroute_model,
        "api_type": "chat_completions",
    }
    if settings.omniroute_api_key:
        custom_llm["request_headers"] = {
            "Authorization": f"Bearer {settings.omniroute_api_key}",
        }
    return custom_llm


async def setup_agents(settings: Settings, *, custom_llm_url: str | None = None) -> None:
    api_key = await _api_key(settings)
    if not api_key:
        raise RuntimeError("ElevenLabs API key required")

    llm_base = custom_llm_url or settings.omniroute_base_url
    if not llm_base:
        raise RuntimeError("Set OMNIROUTE_BASE_URL or pass --custom-llm-url")

    client = AsyncElevenLabs(api_key=api_key)
    custom_llm = _custom_llm_config(settings, llm_base_url=llm_base)

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
                        "custom_llm": custom_llm,
                    },
                },
                "tts": {"voice_id": agent.voice_id} if agent.voice_id else {},
                "turn": {"mode": "turn"},
                "conversation": {"max_duration_seconds": 3600},
            },
        }

        env_name = f"ELEVENLABS_AGENT_ID_{agent.key.upper()}"
        existing_id = os.environ.get(env_name, "") or getattr(settings, f"elevenlabs_agent_id_{agent.key}", "")

        if existing_id:
            await client.conversational_ai.agents.update(agent_id=existing_id, **config)
            print(f"Updated {agent.display_name}: {existing_id}")
        else:
            created = await client.conversational_ai.agents.create(**config)
            print(f"Created {agent.display_name}: {created.agent_id}")
            print(f"  Add to .env: {env_name}={created.agent_id}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--custom-llm-url",
        default=None,
        help="Override OMNIROUTE_BASE_URL (default: https://omniroute-api.asymetryk.com)",
    )
    args = parser.parse_args()
    asyncio.run(setup_agents(get_settings(), custom_llm_url=args.custom_llm_url))


if __name__ == "__main__":
    main()
