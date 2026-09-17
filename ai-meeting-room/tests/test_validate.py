"""Unit tests for interactive validate reporting (no real network)."""

from __future__ import annotations

import asyncio

import httpx

from ai_meeting_room.config import Settings
from ai_meeting_room.validate import (
    PingOutcome,
    SecretResolution,
    apply_ping,
    elevenlabs_presence,
    format_report,
    livekit_presence,
    omniroute_presence,
    ping_elevenlabs,
    ping_omniroute,
    validate_config,
)


SECRET_LIVEKIT_KEY = "lk_test_secret_key_should_never_print"
SECRET_LIVEKIT_SECRET = "lk_test_secret_value_should_never_print"
SECRET_ELEVEN = "el_test_secret_key_should_never_print"
SECRET_OMNI = "or_test_secret_key_should_never_print"
SECRET_BODY = "response-body-token-should-never-print"


def _settings(**overrides: object) -> Settings:
    values = {
        "livekit_url": "",
        "livekit_api_key": "",
        "livekit_api_secret": "",
        "elevenlabs_api_key": "",
        "elevenlabs_agent_id_fred": "",
        "elevenlabs_agent_id_missy": "",
        "elevenlabs_agent_id_architect": "",
        "elevenlabs_agent_id_project_alpha": "",
        "omniroute_base_url": "https://omniroute.example",
        "omniroute_api_key": "",
        "omniroute_model": "codex/gpt-5.6-sol",
        "baserow_api_token": "",
        "baserow_secrets_table_id": None,
        "elevenlabs_secret_name": "elevenlabs_api_key",
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def _complete_settings(**overrides: object) -> Settings:
    values = {
        "livekit_url": "wss://example.livekit.cloud",
        "livekit_api_key": SECRET_LIVEKIT_KEY,
        "livekit_api_secret": SECRET_LIVEKIT_SECRET,
        "elevenlabs_api_key": SECRET_ELEVEN,
        "omniroute_api_key": SECRET_OMNI,
    }
    values.update(overrides)
    return _settings(**values)


async def _env_secrets(settings: Settings) -> SecretResolution:
    source = "env" if settings.elevenlabs_api_key else "missing"
    return SecretResolution(
        elevenlabs_source=source,
        elevenlabs_key=settings.elevenlabs_api_key,
        baserow_configured=False,
        baserow_secret_resolved=False,
    )


async def _ok_ping(*_args: object, **_kwargs: object) -> PingOutcome:
    return PingOutcome(ok=True)


async def _fail_ping(*_args: object, **_kwargs: object) -> PingOutcome:
    return PingOutcome(ok=False, error_class="HTTP 401")


def test_validate_cli_imports_without_livekit_or_elevenlabs() -> None:
    from ai_meeting_room.main import _cmd_validate

    assert _cmd_validate is not None


def test_livekit_presence_fails_when_keys_missing() -> None:
    result = livekit_presence(_settings())
    assert result.status == "fail"
    assert result.required is True
    assert "LIVEKIT_URL" in result.detail
    assert "LIVEKIT_API_KEY" in result.detail
    assert "LIVEKIT_API_SECRET" in result.detail


def test_livekit_presence_passes_when_keys_present() -> None:
    result = livekit_presence(_complete_settings())
    assert result.status == "pass"
    assert SECRET_LIVEKIT_KEY not in result.detail
    assert SECRET_LIVEKIT_SECRET not in result.detail


def test_omniroute_presence_reports_model_and_missing_key() -> None:
    result = omniroute_presence(_settings(omniroute_model="minimax/minimax-m2.5"))
    assert result.status == "fail"
    assert "OMNIROUTE_API_KEY" in result.detail
    assert "model=minimax/minimax-m2.5" in result.detail
    assert SECRET_OMNI not in result.detail


def test_elevenlabs_presence_reports_source_not_value() -> None:
    missing = elevenlabs_presence("missing")
    env = elevenlabs_presence("env")
    baserow = elevenlabs_presence("baserow")
    assert missing.status == "fail"
    assert missing.detail == "source=missing"
    assert env.status == "pass"
    assert env.detail == "source=env"
    assert baserow.detail == "source=baserow"


def test_apply_ping_failure_uses_error_class_only() -> None:
    presence = livekit_presence(_complete_settings())
    failed = apply_ping(presence, PingOutcome(ok=False, error_class="TwirpError (401)"))
    assert failed.status == "fail"
    assert failed.detail.endswith("ping failed: TwirpError (401)")
    assert SECRET_LIVEKIT_KEY not in failed.detail


def test_offline_validate_fails_without_interactive_keys() -> None:
    report = asyncio.run(validate_config(_settings(), offline=True, resolve=_env_secrets))
    assert report.ok is False
    assert report.offline is True
    services = {check.service: check for check in report.checks}
    assert services["LiveKit"].status == "fail"
    assert services["ElevenLabs"].status == "fail"
    assert services["OmniRoute"].status == "fail"
    assert services["Baserow"].status == "skip"
    assert services["ConvAI Fred"].status == "skip"
    assert services["ConvAI Fred"].required is False


def test_offline_validate_passes_with_keys_and_skips_pings() -> None:
    called = {"livekit": 0, "eleven": 0, "omni": 0}

    async def livekit_ping(_settings: Settings) -> PingOutcome:
        called["livekit"] += 1
        return PingOutcome(ok=True)

    async def eleven_ping(_key: str) -> PingOutcome:
        called["eleven"] += 1
        return PingOutcome(ok=True)

    async def omni_ping(_settings: Settings) -> PingOutcome:
        called["omni"] += 1
        return PingOutcome(ok=True)

    report = asyncio.run(
        validate_config(
            _complete_settings(),
            offline=True,
            resolve=_env_secrets,
            livekit_ping=livekit_ping,
            elevenlabs_ping=eleven_ping,
            omniroute_ping=omni_ping,
        )
    )
    assert report.ok is True
    assert called == {"livekit": 0, "eleven": 0, "omni": 0}
    text = format_report(report)
    assert "interactive: pass" in text
    assert SECRET_ELEVEN not in text
    assert SECRET_OMNI not in text
    assert SECRET_LIVEKIT_KEY not in text


def test_online_ping_failure_fails_interactive() -> None:
    report = asyncio.run(
        validate_config(
            _complete_settings(),
            offline=False,
            resolve=_env_secrets,
            livekit_ping=_ok_ping,
            elevenlabs_ping=_fail_ping,
            omniroute_ping=_ok_ping,
        )
    )
    assert report.ok is False
    eleven = next(check for check in report.checks if check.service == "ElevenLabs")
    assert eleven.status == "fail"
    assert eleven.detail == "source=env; ping failed: HTTP 401"
    assert SECRET_ELEVEN not in format_report(report)


def test_online_ping_success_passes() -> None:
    report = asyncio.run(
        validate_config(
            _complete_settings(elevenlabs_agent_id_fred="agent_fred"),
            offline=False,
            resolve=_env_secrets,
            livekit_ping=_ok_ping,
            elevenlabs_ping=_ok_ping,
            omniroute_ping=_ok_ping,
        )
    )
    assert report.ok is True
    services = {check.service: check for check in report.checks}
    assert services["LiveKit"].detail.endswith("ping ok")
    assert services["ElevenLabs"].detail == "source=env; ping ok"
    assert "model=codex/gpt-5.6-sol" in services["OmniRoute"].detail
    assert services["ConvAI Fred"].status == "pass"
    assert services["ConvAI Missy"].status == "skip"


def test_missing_convai_ids_do_not_fail_interactive() -> None:
    report = asyncio.run(
        validate_config(
            _complete_settings(),
            offline=True,
            resolve=_env_secrets,
        )
    )
    assert report.ok is True
    assert all(
        check.status == "skip"
        for check in report.checks
        if check.service.startswith("ConvAI")
    )


def test_baserow_resolved_source_and_status() -> None:
    async def resolve(_settings: Settings) -> SecretResolution:
        return SecretResolution(
            elevenlabs_source="baserow",
            elevenlabs_key=SECRET_ELEVEN,
            baserow_configured=True,
            baserow_secret_resolved=True,
        )

    report = asyncio.run(
        validate_config(
            _complete_settings(elevenlabs_api_key=""),
            offline=True,
            resolve=resolve,
        )
    )
    services = {check.service: check for check in report.checks}
    assert services["ElevenLabs"].detail == "source=baserow"
    assert services["Baserow"].status == "pass"
    assert "resolved" in services["Baserow"].detail
    assert SECRET_ELEVEN not in format_report(report)


def test_format_report_never_includes_secret_material() -> None:
    report = asyncio.run(
        validate_config(
            _complete_settings(),
            offline=True,
            resolve=_env_secrets,
        )
    )
    text = format_report(report)
    for secret in (
        SECRET_LIVEKIT_KEY,
        SECRET_LIVEKIT_SECRET,
        SECRET_ELEVEN,
        SECRET_OMNI,
        "sk_",
        "Bearer ",
    ):
        assert secret not in text
    assert "status: pass" in text
    assert "LiveKit (required for interactive)" in text
    assert "ElevenLabs (required for interactive TTS)" in text
    assert "OmniRoute (required for interactive reasoning)" in text
    assert "Fred: skip" in text
    assert "Missy: skip" in text


def test_ping_elevenlabs_reports_status_not_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/user/subscription")
        assert request.headers["xi-api-key"] == SECRET_ELEVEN
        return httpx.Response(401, text=SECRET_BODY)

    async def run() -> PingOutcome:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await ping_elevenlabs(SECRET_ELEVEN, client=client)

    outcome = asyncio.run(run())
    assert outcome.ok is False
    assert outcome.error_class == "HTTP 401"
    assert SECRET_BODY not in outcome.error_class
    assert SECRET_ELEVEN not in outcome.error_class


def test_ping_omniroute_accepts_models_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/models")
        assert request.headers["authorization"] == f"Bearer {SECRET_OMNI}"
        return httpx.Response(200, json={"data": []})

    async def run() -> PingOutcome:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await ping_omniroute(_complete_settings(), client=client)

    outcome = asyncio.run(run())
    assert outcome.ok is True


def test_ping_omniroute_falls_back_to_health_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(404, text=SECRET_BODY)
        assert request.url.path.endswith("/health")
        return httpx.Response(200, json={"ok": True})

    async def run() -> PingOutcome:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await ping_omniroute(_complete_settings(), client=client)

    outcome = asyncio.run(run())
    assert outcome.ok is True


def test_ping_omniroute_401_does_not_leak_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=SECRET_BODY)

    async def run() -> PingOutcome:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await ping_omniroute(_complete_settings(), client=client)

    outcome = asyncio.run(run())
    assert outcome.ok is False
    assert outcome.error_class == "HTTP 401"
    assert SECRET_BODY not in outcome.error_class
    assert SECRET_OMNI not in outcome.error_class
