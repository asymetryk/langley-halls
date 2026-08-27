"""Application configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    livekit_url: str = Field(default="", alias="LIVEKIT_URL")
    livekit_api_key: str = Field(default="", alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(default="", alias="LIVEKIT_API_SECRET")
    meeting_room_name: str = Field(default="ai-meeting-room", alias="MEETING_ROOM_NAME")

    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_agent_id_fred: str = Field(default="", alias="ELEVENLABS_AGENT_ID_FRED")
    elevenlabs_agent_id_missy: str = Field(default="", alias="ELEVENLABS_AGENT_ID_MISSY")
    elevenlabs_agent_id_architect: str = Field(default="", alias="ELEVENLABS_AGENT_ID_ARCHITECT")
    elevenlabs_agent_id_project_alpha: str = Field(
        default="", alias="ELEVENLABS_AGENT_ID_PROJECT_ALPHA"
    )

    reasoning_provider: str = Field(default="mock", alias="REASONING_PROVIDER")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    reasoning_api_host: str = Field(default="0.0.0.0", alias="REASONING_API_HOST")
    reasoning_api_port: int = Field(default=8090, alias="REASONING_API_PORT")
    reasoning_api_public_url: str = Field(default="", alias="REASONING_API_PUBLIC_URL")

    baserow_api_url: str = Field(default="https://api.baserow.io", alias="BASEROW_API_URL")
    baserow_api_token: str = Field(default="", alias="BASEROW_API_TOKEN")
    baserow_secrets_table_id: int | None = Field(default=None, alias="BASEROW_SECRETS_TABLE_ID")
    baserow_secret_name_field: str = Field(default="Name", alias="BASEROW_SECRET_NAME_FIELD")
    baserow_secret_value_field: str = Field(default="Value", alias="BASEROW_SECRET_VALUE_FIELD")
    elevenlabs_secret_name: str = Field(default="elevenlabs_api_key", alias="ELEVENLABS_SECRET_NAME")

    user_input_rate: int = 16000
    agent_output_rate: int = 24000


@lru_cache
def get_settings() -> Settings:
    return Settings()
