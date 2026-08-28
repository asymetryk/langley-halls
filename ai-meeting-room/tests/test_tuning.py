"""Tests for interactive turn-taking heuristics."""

from ai_meeting_room.agents.tuning import ConversationState, pick_responder

ACTIVE = {"missy", "architect", "project_alpha"}


def test_named_agent_always_responds() -> None:
    convo = ConversationState()
    assert pick_responder("Missy what do you think?", active_agents=ACTIVE, conversation=convo) == "missy"
    assert pick_responder("hey architect is this feasible", active_agents=ACTIVE, conversation=convo) == "architect"


def test_excluded_agent_ignored() -> None:
    assert pick_responder("Fred what do you think?", active_agents=ACTIVE) is None


def test_filler_ignored() -> None:
    assert pick_responder("yeah okay", active_agents=ACTIVE) is None
    assert pick_responder("um", active_agents=ACTIVE) is None


def test_statement_without_addressee_ignored() -> None:
    assert pick_responder("so we should probably think about that", active_agents=ACTIVE) is None


def test_unnamed_question_ignored() -> None:
    assert (
        pick_responder("what should we do next?", default_chair="project_alpha", active_agents=ACTIVE)
        is None
    )
    assert (
        pick_responder("can you help me with this", default_chair="project_alpha", active_agents=ACTIVE)
        is None
    )


def test_room_wide_question_routes_to_chair() -> None:
    assert (
        pick_responder("does everyone agree with that?", default_chair="project_alpha", active_agents=ACTIVE)
        == "project_alpha"
    )


def test_active_thread_routes_followup_without_name() -> None:
    convo = ConversationState()
    assert pick_responder("Missy, thoughts on the logo?", active_agents=ACTIVE, conversation=convo) == "missy"
    assert (
        pick_responder("I like the blue version better", active_agents=ACTIVE, conversation=convo) == "missy"
    )


def test_switch_addressee_mid_room() -> None:
    convo = ConversationState()
    pick_responder("Missy hello", active_agents=ACTIVE, conversation=convo)
    assert pick_responder("Architect is that feasible?", active_agents=ACTIVE, conversation=convo) == "architect"


def test_thanks_closes_thread() -> None:
    convo = ConversationState()
    pick_responder("Missy what do you think?", active_agents=ACTIVE, conversation=convo)
    assert pick_responder("thanks that's all", active_agents=ACTIVE, conversation=convo) is None
    assert pick_responder("maybe we should ship it", active_agents=ACTIVE, conversation=convo) is None
