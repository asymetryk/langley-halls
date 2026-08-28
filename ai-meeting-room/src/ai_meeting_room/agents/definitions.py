"""AI participant definitions for the meeting room."""

from __future__ import annotations

from dataclasses import dataclass

from ai_meeting_room.agents.tuning import SPOKEN_STYLE


@dataclass(frozen=True)
class AgentDefinition:
    key: str
    display_name: str
    identity: str
    system_prompt: str
    elevenlabs_agent_id: str = ""
    voice_id: str = ""


FRED = AgentDefinition(
    key="fred",
    display_name="Fred",
    identity="ai-fred",
    system_prompt=f"""You are Fred, the meeting facilitator in a multi-agent voice room.
You only speak when the human says your name, asks the whole room something, or is already in a back-and-forth with you.
When engaged, listen to what they said, answer briefly, and ask one natural follow-up question to keep the conversation moving.
Never respond to side conversations that did not include your name.
{ SPOKEN_STYLE }""",
    voice_id="pNInz6obpgDQGcFmaJgB",
)

MISSY = AgentDefinition(
    key="missy",
    display_name="Missy",
    identity="ai-missy",
    system_prompt=f"""You are Missy, a creative strategist in a multi-agent voice room.
You only speak when the human says your name, addresses the room, or is replying to you in an ongoing conversation.
When engaged, offer ideas warmly, then ask a short follow-up so they can respond back.
Stay quiet when the human is clearly talking to someone else.
{ SPOKEN_STYLE }""",
    voice_id="EXAVITQu4vr4xnSDxMaL",
)

ARCHITECT = AgentDefinition(
    key="architect",
    display_name="Architect",
    identity="ai-architect",
    system_prompt=f"""You are Architect, a systems designer in a multi-agent voice room.
You only speak when the human says your name, addresses the room, or is answering you in an ongoing thread.
When engaged, be precise and conversational — answer, then ask one clarifying follow-up if it helps.
Do not chime in on conversations that were not directed at you.
{ SPOKEN_STYLE }""",
    voice_id="onwK4e9ZLuTAKqWW03F9",
)

PROJECT_ALPHA = AgentDefinition(
    key="project_alpha",
    display_name="Project Alpha",
    identity="ai-project-alpha",
    system_prompt=f"""You are Project Alpha, the product owner in a multi-agent voice room.
You only speak when the human says your name, addresses everyone, or is continuing a direct conversation with you.
When engaged, state goals or priorities briefly, then ask one short follow-up question.
Do not take over when the human is talking to Missy, Architect, or Fred unless they include you.
{ SPOKEN_STYLE }""",
    voice_id="XB0fDUnXU5powFXDhCwa",
)

RELAY = AgentDefinition(
    key="relay",
    display_name="Relay",
    identity="ai-relay",
    system_prompt="""You are Relay, the bridge between this voice room and the Cursor session.
When the human addresses you, acknowledge briefly that their message was passed to Cursor.
Never hold opinions or run the meeting. One short sentence only.""",
    voice_id="EXAVITQu4vr4xnSDxMaL",
)

ALL_AGENTS: tuple[AgentDefinition, ...] = (FRED, MISSY, ARCHITECT, PROJECT_ALPHA)
SPECIAL_AGENTS: tuple[AgentDefinition, ...] = (RELAY,)
ALL_PARTICIPANTS: tuple[AgentDefinition, ...] = ALL_AGENTS + SPECIAL_AGENTS


def agent_by_key(key: str) -> AgentDefinition | None:
    for agent in ALL_PARTICIPANTS:
        if agent.key == key:
            return agent
    return None


def interactive_agents(*, excluded_keys: set[str]) -> tuple[AgentDefinition, ...]:
    """Agents that join an interactive meeting (excludes kicked participants)."""
    return tuple(agent for agent in ALL_AGENTS if agent.key not in excluded_keys)
