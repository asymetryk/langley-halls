"""Tests for interactive turn-taking heuristics."""

from ai_meeting_room.agents.tuning import pick_responder


def test_named_agent_always_responds() -> None:
    assert pick_responder("Missy what do you think?") == "missy"
    assert pick_responder("hey architect is this feasible") == "architect"


def test_filler_ignored() -> None:
    assert pick_responder("yeah okay") is None
    assert pick_responder("um") is None


def test_statement_without_addressee_ignored() -> None:
    assert pick_responder("so we should probably think about that") is None


def test_question_routes_to_chair() -> None:
    assert pick_responder("what should we do next?") == "fred"
    assert pick_responder("can you help me with this") == "fred"


def test_room_wide_question_routes_to_chair() -> None:
    assert pick_responder("does everyone agree with that?") == "fred"
