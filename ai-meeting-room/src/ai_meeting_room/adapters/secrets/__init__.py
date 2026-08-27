"""Secrets adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ai_meeting_room.config import Settings


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
    """Read secrets from a Baserow table (Name / Value columns)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_secret(self, name: str) -> str | None:
        if not self._settings.baserow_api_token or not self._settings.baserow_secrets_table_id:
            return None

        import json
        from urllib.parse import quote

        import httpx

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
        url = (
            f"{self._settings.baserow_api_url.rstrip('/')}/api/database/rows/table/{table_id}/"
            f"?user_field_names=true&size=1&filters={quote(json.dumps(filters))}"
        )
        headers = {"Authorization": f"Token {self._settings.baserow_api_token}"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            rows = response.json().get("results", [])

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


def build_secrets_adapter(settings: Settings) -> SecretsAdapter:
    return ChainedSecretsAdapter(
        BaserowSecretsAdapter(settings),
        EnvSecretsAdapter(),
    )
