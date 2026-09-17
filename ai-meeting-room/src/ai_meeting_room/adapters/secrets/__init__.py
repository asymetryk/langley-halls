"""Secrets adapters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import httpx

from ai_meeting_room.config import Settings

logger = logging.getLogger(__name__)

ElevenLabsSource = Literal["baserow", "env", "missing"]


class SecretsAdapter(ABC):
    @abstractmethod
    async def get_secret(self, name: str) -> str | None:
        """Return secret value by name, or None if not found."""


class EnvSecretsAdapter(SecretsAdapter):
    """Read secrets from environment variables (uppercased)."""

    async def get_secret(self, name: str) -> str | None:
        import os

        value = os.environ.get(name.upper()) or os.environ.get(name)
        return value or None


class BaserowSecretsAdapter(SecretsAdapter):
    """Read secrets from a Baserow table (Name / Secret columns).

    Only table-row reads are used. Database tokens 401 on /api/applications/;
    do not call that endpoint.
    """

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    def rows_url(self, name: str) -> str:
        import json
        from urllib.parse import quote

        filters = {
            "filter_type": "AND",
            "filters": [
                {
                    "field": self._settings.baserow_secret_name_field,
                    "type": "equal",
                    "value": name,
                }
            ],
        }
        table_id = self._settings.baserow_secrets_table_id
        return (
            f"{self._settings.baserow_api_url.rstrip('/')}/api/database/rows/table/{table_id}/"
            f"?user_field_names=true&size=1&filters={quote(json.dumps(filters))}"
        )

    async def get_secret(self, name: str) -> str | None:
        if not self._settings.baserow_api_token or not self._settings.baserow_secrets_table_id:
            return None

        headers = {"Authorization": f"Token {self._settings.baserow_api_token}"}
        url = self.rows_url(name)
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            rows = response.json().get("results", [])
        finally:
            if own_client:
                await client.aclose()

        if not rows:
            return None

        value = rows[0].get(self._settings.baserow_secret_value_field)
        if value is None:
            return None
        return str(value).strip() or None


class ChainedSecretsAdapter(SecretsAdapter):
    """Try adapters in order; first non-None wins."""

    def __init__(self, *adapters: SecretsAdapter) -> None:
        self._adapters = adapters

    async def get_secret(self, name: str) -> str | None:
        for adapter in self._adapters:
            value = await adapter.get_secret(name)
            if value:
                return value
        return None


def build_secrets_adapter(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> SecretsAdapter:
    return ChainedSecretsAdapter(
        BaserowSecretsAdapter(settings, client=client),
        EnvSecretsAdapter(),
    )


def _exc_class(exc: BaseException) -> str:
    name = type(exc).__name__
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None) or getattr(exc, "code", None)
    if status is not None:
        return f"{name} ({status})"
    return name


@dataclass(frozen=True)
class ElevenLabsKeyLookup:
    key: str
    source: ElevenLabsSource
    baserow_error: str = ""


async def lookup_elevenlabs_api_key(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> ElevenLabsKeyLookup:
    """Baserow (via secrets adapter) then env. Never logs the key value."""
    name = settings.elevenlabs_secret_name
    error = ""
    if settings.baserow_api_token and settings.baserow_secrets_table_id is not None:
        try:
            value = await BaserowSecretsAdapter(settings, client=client).get_secret(name)
            if value:
                return ElevenLabsKeyLookup(key=value.strip(), source="baserow")
        except Exception as exc:
            error = _exc_class(exc)
            logger.warning("Baserow ElevenLabs lookup failed: %s", error)

    env_key = (settings.elevenlabs_api_key or "").strip()
    if not env_key:
        env_key = (await EnvSecretsAdapter().get_secret(name) or "").strip()
    if env_key:
        return ElevenLabsKeyLookup(key=env_key, source="env", baserow_error=error)
    return ElevenLabsKeyLookup(key="", source="missing", baserow_error=error)


async def resolve_elevenlabs_api_key(
    settings: Settings,
    *,
    required: bool = True,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Resolve the ElevenLabs API key: Baserow then env. Does not print the key."""
    found = await lookup_elevenlabs_api_key(settings, client=client)
    if found.key:
        if found.source == "baserow":
            logger.info("Loaded ElevenLabs API key from secrets adapter")
        else:
            logger.info("Using ElevenLabs API key from environment")
        return found.key
    if required:
        raise RuntimeError(
            "ElevenLabs API key not found. Configure Baserow secrets table or ELEVENLABS_API_KEY."
        )
    return ""
