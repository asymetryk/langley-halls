"""Tests for spoken host commands."""

from ai_meeting_room.agents.host_commands import parse_host_command


def test_kick_fred() -> None:
    cmd = parse_host_command("room kick fred")
    assert cmd is not None
    assert cmd.action == "kick"
    assert cmd.agent_key == "fred"


def test_invite_missy() -> None:
    cmd = parse_host_command("bring missy back")
    assert cmd is not None
    assert cmd.action == "invite"
    assert cmd.agent_key == "missy"


def test_set_chair() -> None:
    cmd = parse_host_command("make architect the chair")
    assert cmd is not None
    assert cmd.action == "chair"
    assert cmd.agent_key == "architect"


def test_pause_and_resume() -> None:
    assert parse_host_command("room pause").action == "pause"
    assert parse_host_command("room resume").action == "resume"


def test_normal_speech_not_host_command() -> None:
    assert parse_host_command("Missy what do you think?") is None
