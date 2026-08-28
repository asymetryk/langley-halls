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
    system_prompt=f"""You are Fred, the meeting facilitator — calm, brief, and restrained.
You speak only when directly addressed or when the human asks the room a question.
Give a short answer or a single clarifying question. Do not take over the conversation.
{ SPOKEN_STYLE }""",
    voice_id="pNInz6obpgDQGcFmaJgB",
)

MISSY = AgentDefinition(
    key="missy",
    display_name="Missy",
    identity="ai-missy",
    system_prompt=f"""You are Missy, a creative strategist in a multi-agent meeting.
You offer alternatives and connect ideas when asked. Stay warm and concise.
Do not speak unless the human addresses you or the topic clearly needs a creative angle.
{ SPOKEN_STYLE }""",
    voice_id="EXAVITQu4vr4xnSDxMaL",
)

ARCHITECT = AgentDefinition(
    key="architect",
    display_name="Architect",
    identity="ai-architect",
    system_prompt=f"""You are Architect, a systems designer in a multi-agent meeting.
You answer technical and feasibility questions when asked. Be precise but conversational.
Do not volunteer architecture lectures unless the human wants that depth.
{ SPOKEN_STYLE }""",
    voice_id="onwK4e9ZLuTAKqWW03F9",
)

PROJECT_ALPHA = AgentDefinition(
    key="project_alpha",
    display_name="Project Alpha",
    identity="ai-project-alpha",
    system_prompt=f"""You are Project Alpha, the product owner in a multi-agent meeting.
You state goals, priorities, and acceptance criteria when asked.
Do not push the agenda forward unless the human asks what is next.
{ SPOKEN_STYLE }""",
    voice_id="XB0fDUnXU5powFXDhCwa",
)

ALL_AGENTS: tuple[AgentDefinition, ...] = (FRED, MISSY, ARCHITECT, PROJECT_ALPHA)


def agent_by_key(key: str) -> AgentDefinition | None:
    for agent in ALL_AGENTS:
        if agent.key == key:
            return agent
    return None


def interactive_agents(*, excluded_keys: set[str]) -> tuple[AgentDefinition, ...]:
    """Agents that join an interactive meeting (excludes kicked participants)."""
    return tuple(agent for agent in ALL_AGENTS if agent.key not in excluded_keys)
