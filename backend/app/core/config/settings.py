"""Application configuration loaded from environment variables.

Exposes a single cached `settings` instance backed by Pydantic Settings v2.
Only foundation-level configuration (app metadata, server, CORS, logging)
is defined here; settings for database, auth, and AI modules are added
alongside their respective milestones.
"""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application metadata
    app_name: str = "AIKDAP"
    app_version: str = "1.0.0"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # API
    api_v1_prefix: str = "/api/v1"

    # Security / JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Database
    database_url: str
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # CORS
    #
    # `NoDecode` opts this field out of pydantic-settings' automatic
    # JSON-decoding of complex-typed env values, which would otherwise
    # raise `SettingsError` on a plain comma-separated string before our
    # validator below ever runs. The validator then accepts either a
    # JSON array (`["https://a", "https://b"]`) or a comma-separated
    # string (`https://a,https://b`).
    backend_cors_origins: Annotated[list[str], NoDecode] = []

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Asset storage
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 100

    # Celery / background tasks
    celery_broker_url: str
    celery_result_backend: str

    # Document chunking (knowledge base pipeline)
    chunk_size: int = 1000
    chunk_overlap: int = 100

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Parse CORS origins from a JSON array or a comma-separated string."""
        if isinstance(value, list):
            return value
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return []

        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"backend_cors_origins is not valid JSON: {stripped!r}"
                ) from exc
            if not isinstance(parsed, list):
                raise ValueError("backend_cors_origins JSON value must be an array")
            return [str(origin).strip() for origin in parsed if str(origin).strip()]

        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """Whether the app is running in the production environment."""
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    Using `lru_cache` ensures the environment is parsed once and reused,
    while still allowing tests to override via `get_settings.cache_clear()`.
    """
    return Settings()


settings: Settings = get_settings()
