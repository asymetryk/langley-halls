"""OpenAI-compatible Custom LLM endpoint for ElevenLabs ConvAI."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from ai_meeting_room.adapters.reasoning import ChatMessage, ReasoningContext, build_reasoning_adapter
from ai_meeting_room.agents.definitions import ALL_AGENTS, agent_by_key
from ai_meeting_room.config import get_settings
from ai_meeting_room.memory.store import AgentMemory

logger = logging.getLogger(__name__)


def create_reasoning_app(memories: dict[str, AgentMemory] | None = None) -> FastAPI:
    settings = get_settings()
    adapter = build_reasoning_adapter(
        settings.reasoning_provider,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )
    memory_store = memories or {agent.key: AgentMemory(agent.display_name) for agent in ALL_AGENTS}

    app = FastAPI(title="AI Meeting Room Reasoning API", version="0.1.0")

    def _resolve_agent(model: str, agent_header: str | None) -> tuple[str, str, str]:
        key = (agent_header or model or "fred").replace("meeting-", "").strip().lower()
        agent = agent_by_key(key)
        if not agent:
            agent = ALL_AGENTS[0]
        return agent.key, agent.display_name, agent.system_prompt

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": settings.reasoning_provider}

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    ) -> StreamingResponse:
        body: dict[str, Any] = await request.json()
        model = str(body.get("model", "fred"))
        agent_key, agent_name, system_prompt = _resolve_agent(model, x_agent_id)

        raw_messages = body.get("messages", [])
        messages: list[ChatMessage] = []
        for item in raw_messages:
            role = item.get("role", "user")
            content = item.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            if role == "system":
                continue
            messages.append(ChatMessage(role=role, content=str(content)))

        memory = memory_store.get(agent_key)
        context = ReasoningContext(
            agent_id=agent_key,
            agent_name=agent_name,
            system_prompt=system_prompt,
            messages=messages,
            memory_summary=memory.summary() if memory else "",
        )

        if messages:
            last = messages[-1]
            if memory and last.role == "user":
                memory.remember("room", last.content)

        async def sse_stream():
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = 0
            full_text: list[str] = []

            async for delta in adapter.stream_completion(context):
                full_text.append(delta)
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": f"meeting-{agent_key}",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            if memory:
                memory.remember(agent_name, "".join(full_text).strip())

            final = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": f"meeting-{agent_key}",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    return app
