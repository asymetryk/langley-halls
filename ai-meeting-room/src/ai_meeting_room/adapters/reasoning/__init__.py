"""Provider-agnostic reasoning adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ReasoningContext:
    agent_id: str
    agent_name: str
    system_prompt: str
    messages: list[ChatMessage] = field(default_factory=list)
    memory_summary: str = ""


class ReasoningAdapter(ABC):
    @abstractmethod
    async def stream_completion(self, context: ReasoningContext) -> AsyncIterator[str]:
        """Yield text deltas for the assistant reply."""


class MockReasoningAdapter(ReasoningAdapter):
    """Deterministic replies for local demo without external LLM keys."""

    async def stream_completion(self, context: ReasoningContext) -> AsyncIterator[str]:
        last_user = next(
            (m.content for m in reversed(context.messages) if m.role == "user"),
            "the meeting topic",
        )
        reply = (
            f"This is {context.agent_name}. I heard: {last_user[:120]}. "
            f"As {context.agent_name}, I'll keep our discussion moving."
        )
        for word in reply.split():
            yield word + " "


class OpenAIReasoningAdapter(ReasoningAdapter):
    """OpenAI-compatible chat completions (Codex, GPT, etc.)."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def stream_completion(self, context: ReasoningContext) -> AsyncIterator[str]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key)
        messages = [{"role": "system", "content": context.system_prompt}]
        if context.memory_summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"Meeting memory:\n{context.memory_summary}",
                }
            )
        messages.extend({"role": m.role, "content": m.content} for m in context.messages)

        stream = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            temperature=0.7,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


def build_reasoning_adapter(provider: str, *, api_key: str = "", model: str = "") -> ReasoningAdapter:
    normalized = provider.lower().strip()
    if normalized == "openai":
        if not api_key:
            raise ValueError("OPENAI_API_KEY required for reasoning provider 'openai'")
        return OpenAIReasoningAdapter(api_key=api_key, model=model or "gpt-4o-mini")
    if normalized in {"mock", "demo"}:
        return MockReasoningAdapter()
    raise ValueError(f"Unknown reasoning provider: {provider}")
