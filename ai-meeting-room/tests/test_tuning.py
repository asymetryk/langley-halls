"""Tests for interactive turn-taking heuristics."""

from ai_meeting_room.agents.tuning import pick_responder

ACTIVE = {"missy", "architect", "project_alpha"}


def test_named_agent_always_responds() -> None:
    assert pick_responder("Missy what do you think?", active_agents=ACTIVE) == "missy"
    assert pick_responder("hey architect is this feasible", active_agents=ACTIVE) == "architect"


def test_excluded_agent_ignored() -> None:
    assert pick_responder("Fred what do you think?", active_agents=ACTIVE) is None


def test_filler_ignored() -> None:
    assert pick_responder("yeah okay", active_agents=ACTIVE) is None
    assert pick_responder("um", active_agents=ACTIVE) is None


def test_statement_without_addressee_ignored() -> None:
    assert pick_responder("so we should probably think about that", active_agents=ACTIVE) is None


def test_question_routes_to_chair() -> None:
    assert pick_responder("what should we do next?", default_chair="project_alpha", active_agents=ACTIVE) == "project_alpha"
    assert pick_responder("can you help me with this", default_chair="project_alpha", active_agents=ACTIVE) == "project_alpha"


def test_room_wide_question_routes_to_chair() -> None:
    assert pick_responder("does everyone agree with that?", default_chair="project_alpha", active_agents=ACTIVE) == "project_alpha"
