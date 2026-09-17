"""Interactive-demo config validation (LiveKit / ElevenLabs / OmniRoute).

Reports status only — never key material, tokens, or response bodies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal
from urllib.parse import urlparse

import httpx

from ai_meeting_room.adapters.secrets import BaserowSecretsAdapter, EnvSecretsAdapter
from ai_meeting_room.config import Settings

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"

Status = Literal["pass", "fail", "skip"]
ElevenLabsSource = Literal["baserow", "env", "missing"]

ELEVENLABS_USER_URL = "https://api.elevenlabs.io/v1/user/subscription"
OMNIROUTE_MODELS_PATH = "/v1/models"
OMNIROUTE_HEALTH_PATH = "/health"
LIVEKIT_LIST_ROOMS_PATH = "/twirp/livekit.RoomService/ListRooms"

CONVAI_AGENTS: tuple[tuple[str, str], ...] = (
    ("Fred", "elevenlabs_agent_id_fred"),
    ("Missy", "elevenlabs_agent_id_missy"),
    ("Architect", "elevenlabs_agent_id_architect"),
    ("Project Alpha", "elevenlabs_agent_id_project_alpha"),
)


@dataclass(frozen=True)
class CheckResult:
    service: str
    status: Status
    detail: str
    required: bool = False


@dataclass(frozen=True)
class PingOutcome:
    ok: bool
    error_class: str = ""


@dataclass
class SecretResolution:
    elevenlabs_source: ElevenLabsSource
    elevenlabs_key: str
    baserow_configured: bool
    baserow_secret_resolved: bool
    baserow_error: str = ""
    elevenlabs_secret_name: str = ""
    baserow_table_id: int | None = None
    baserow_value_field: str = ""


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)
    offline: bool = False

    @property
    def ok(self) -> bool:
        return all(check.status != STATUS_FAIL for check in self.checks if check.required)

    def required_failures(self) -> list[CheckResult]:
        return [check for check in self.checks if check.required and check.status == STATUS_FAIL]


ResolveSecrets = Callable[[Settings], Awaitable[SecretResolution]]
LiveKitPing = Callable[[Settings], Awaitable[PingOutcome]]
ElevenLabsPing = Callable[[str], Awaitable[PingOutcome]]
OmniRoutePing = Callable[[Settings], Awaitable[PingOutcome]]


def _present(value: object) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


def _error_class(exc: BaseException) -> str:
    """Status code / exception type only — never str(exc) or response bodies."""
    name = type(exc).__name__
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    if status is not None:
        return f"{name} ({status})"
    return name


def missing_env_names(*pairs: tuple[str, object]) -> list[str]:
    return [name for name, value in pairs if not _present(value)]


def livekit_presence(settings: Settings) -> CheckResult:
    missing = missing_env_names(
        ("LIVEKIT_URL", settings.livekit_url),
        ("LIVEKIT_API_KEY", settings.livekit_api_key),
        ("LIVEKIT_API_SECRET", settings.livekit_api_secret),
    )
    if missing:
        return CheckResult(
            "LiveKit",
            STATUS_FAIL,
            f"missing {', '.join(missing)}",
            required=True,
        )
    return CheckResult("LiveKit", STATUS_PASS, "credentials present", required=True)


def omniroute_presence(settings: Settings) -> CheckResult:
    missing = missing_env_names(
        ("OMNIROUTE_BASE_URL", settings.omniroute_base_url),
        ("OMNIROUTE_API_KEY", settings.omniroute_api_key),
    )
    model = (settings.omniroute_model or "").strip() or "(unset)"
    if missing:
        return CheckResult(
            "OmniRoute",
            STATUS_FAIL,
            f"missing {', '.join(missing)}; model={model}",
            required=True,
        )
    return CheckResult(
        "OmniRoute",
        STATUS_PASS,
        f"credentials present; model={model}",
        required=True,
    )


def elevenlabs_presence(source: ElevenLabsSource) -> CheckResult:
    if source == "missing":
        return CheckResult("ElevenLabs", STATUS_FAIL, "source=missing", required=True)
    return CheckResult("ElevenLabs", STATUS_PASS, f"source={source}", required=True)


def _baserow_lookup_detail(resolution: SecretResolution) -> str:
    table = resolution.baserow_table_id if resolution.baserow_table_id is not None else "?"
    name = resolution.elevenlabs_secret_name or "(unset)"
    field = resolution.baserow_value_field or "Secret"
    return f"table={table} name={name!r} field={field} (rows only)"


def baserow_status(resolution: SecretResolution) -> CheckResult:
    if not resolution.baserow_configured:
        return CheckResult(
            "Baserow",
            STATUS_SKIP,
            f"not configured (set BASEROW_API_TOKEN; {_baserow_lookup_detail(resolution)})",
        )
    if resolution.baserow_secret_resolved:
        return CheckResult(
            "Baserow",
            STATUS_PASS,
            f"configured; elevenlabs secret name resolved; {_baserow_lookup_detail(resolution)}",
        )
    if resolution.baserow_error:
        return CheckResult(
            "Baserow",
            STATUS_SKIP,
            f"configured; lookup failed: {resolution.baserow_error}; {_baserow_lookup_detail(resolution)}",
        )
    return CheckResult(
        "Baserow",
        STATUS_SKIP,
        f"configured; elevenlabs secret name not resolved; {_baserow_lookup_detail(resolution)}",
    )


def convai_agent_checks(settings: Settings) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for label, field_name in CONVAI_AGENTS:
        value = getattr(settings, field_name, "")
        if _present(value):
            checks.append(CheckResult(f"ConvAI {label}", STATUS_PASS, "set (parked; main run only)"))
        else:
            checks.append(CheckResult(f"ConvAI {label}", STATUS_SKIP, "not set (parked; main run only)"))
    return checks


def apply_ping(presence: CheckResult, outcome: PingOutcome) -> CheckResult:
    if presence.status != STATUS_PASS:
        return presence
    if outcome.ok:
        return CheckResult(
            presence.service,
            STATUS_PASS,
            f"{presence.detail}; ping ok",
            required=presence.required,
        )
    return CheckResult(
        presence.service,
        STATUS_FAIL,
        f"{presence.detail}; ping failed: {outcome.error_class}",
        required=presence.required,
    )


def baserow_configured(settings: Settings) -> bool:
    return _present(settings.baserow_api_token) and settings.baserow_secrets_table_id is not None


async def resolve_secrets(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> SecretResolution:
    configured = baserow_configured(settings)
    key = ""
    source: ElevenLabsSource = "missing"
    resolved = False
    error = ""

    if configured:
        try:
            value = await BaserowSecretsAdapter(settings, client=client).get_secret(
                settings.elevenlabs_secret_name
            )
            if value:
                key = value
                source = "baserow"
                resolved = True
        except Exception as exc:
            error = _error_class(exc)

    if source == "missing":
        env_key = (settings.elevenlabs_api_key or "").strip()
        if not env_key:
            env_key = (await EnvSecretsAdapter().get_secret(settings.elevenlabs_secret_name) or "").strip()
        if env_key:
            key = env_key
            source = "env"

    return SecretResolution(
        elevenlabs_source=source,
        elevenlabs_key=key,
        baserow_configured=configured,
        baserow_secret_resolved=resolved,
        baserow_error=error,
        elevenlabs_secret_name=settings.elevenlabs_secret_name,
        baserow_table_id=settings.baserow_secrets_table_id,
        baserow_value_field=settings.baserow_secret_value_field,
    )


def livekit_http_url(livekit_url: str) -> str:
    parsed = urlparse((livekit_url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme == "wss":
        scheme = "https"
    elif scheme == "ws":
        scheme = "http"
    elif scheme not in {"http", "https"}:
        scheme = "https"
    host = parsed.netloc or parsed.path
    return f"{scheme}://{host}".rstrip("/")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def livekit_list_rooms_jwt(api_key: str, api_secret: str, *, ttl_sec: int = 60) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": api_key,
        "sub": "ai-meeting-room-validate",
        "nbf": now,
        "exp": now + ttl_sec,
        "video": {"roomList": True},
    }
    signing = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    signature = hmac.new(api_secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{_b64url(signature)}"


def _http_ok(status_code: int) -> bool:
    return 200 <= status_code < 300


async def ping_livekit(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> PingOutcome:
    http_url = livekit_http_url(settings.livekit_url)
    token = livekit_list_rooms_jwt(settings.livekit_api_key, settings.livekit_api_secret)
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.post(
            f"{http_url}{LIVEKIT_LIST_ROOMS_PATH}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            content=b"{}",
        )
        if _http_ok(response.status_code):
            return PingOutcome(ok=True)
        return PingOutcome(ok=False, error_class=f"HTTP {response.status_code}")
    except Exception as exc:
        return PingOutcome(ok=False, error_class=_error_class(exc))
    finally:
        if own_client:
            await client.aclose()


async def ping_elevenlabs(
    api_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> PingOutcome:
    headers = {"xi-api-key": api_key}
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.get(ELEVENLABS_USER_URL, headers=headers)
        if _http_ok(response.status_code):
            return PingOutcome(ok=True)
        return PingOutcome(ok=False, error_class=f"HTTP {response.status_code}")
    except Exception as exc:
        return PingOutcome(ok=False, error_class=_error_class(exc))
    finally:
        if own_client:
            await client.aclose()


async def ping_omniroute(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> PingOutcome:
    base = (settings.omniroute_base_url or "").rstrip("/")
    headers = {"Authorization": f"Bearer {settings.omniroute_api_key}"}
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        models = await client.get(f"{base}{OMNIROUTE_MODELS_PATH}", headers=headers)
        if _http_ok(models.status_code):
            return PingOutcome(ok=True)
        if models.status_code == 404:
            health = await client.get(f"{base}{OMNIROUTE_HEALTH_PATH}", headers=headers)
            if _http_ok(health.status_code):
                return PingOutcome(ok=True)
            return PingOutcome(ok=False, error_class=f"HTTP {health.status_code}")
        return PingOutcome(ok=False, error_class=f"HTTP {models.status_code}")
    except Exception as exc:
        return PingOutcome(ok=False, error_class=_error_class(exc))
    finally:
        if own_client:
            await client.aclose()


def format_report(report: ValidationReport) -> str:
    mode = "offline (presence only; network pings skipped)" if report.offline else "online (presence + cheap pings)"
    lines = [
        "AI Meeting Room — validate (interactive)",
        f"Mode: {mode}",
        "-" * 44,
        "",
        "LiveKit (required for interactive)",
        _format_check(_find(report, "LiveKit")),
        "",
        "ElevenLabs (required for interactive TTS)",
        _format_check(_find(report, "ElevenLabs")),
        "",
        "OmniRoute (required for interactive reasoning)",
        _format_check(_find(report, "OmniRoute")),
        "",
        "Baserow (optional secrets table)",
        _format_check(_find(report, "Baserow")),
        "",
        "ConvAI agent IDs (optional / parked — main run only)",
    ]
    for label, _field in CONVAI_AGENTS:
        check = _find(report, f"ConvAI {label}")
        lines.append(f"  {label}: {check.status}  {check.detail}")
    lines.extend(
        [
            "-" * 44,
            f"interactive: {'pass' if report.ok else 'fail'}",
        ]
    )
    return "\n".join(lines)


def _find(report: ValidationReport, service: str) -> CheckResult:
    for check in report.checks:
        if check.service == service:
            return check
    return CheckResult(service, STATUS_SKIP, "not checked")


def _format_check(check: CheckResult) -> str:
    return f"  status: {check.status}  {check.detail}"


async def validate_config(
    settings: Settings,
    *,
    offline: bool = False,
    resolve: ResolveSecrets | None = None,
    livekit_ping: LiveKitPing | None = None,
    elevenlabs_ping: ElevenLabsPing | None = None,
    omniroute_ping: OmniRoutePing | None = None,
) -> ValidationReport:
    """Validate secrets needed for `main interactive`. Never includes secret values."""
    resolution = await (resolve or resolve_secrets)(settings)

    livekit = livekit_presence(settings)
    eleven = elevenlabs_presence(resolution.elevenlabs_source)
    omni = omniroute_presence(settings)

    if not offline:
        if livekit.status == STATUS_PASS:
            livekit = apply_ping(livekit, await (livekit_ping or ping_livekit)(settings))
        if eleven.status == STATUS_PASS:
            eleven = apply_ping(
                eleven,
                await (elevenlabs_ping or ping_elevenlabs)(resolution.elevenlabs_key),
            )
        if omni.status == STATUS_PASS:
            omni = apply_ping(omni, await (omniroute_ping or ping_omniroute)(settings))

    checks = [
        livekit,
        eleven,
        omni,
        baserow_status(resolution),
        *convai_agent_checks(settings),
    ]
    return ValidationReport(checks=checks, offline=offline)
