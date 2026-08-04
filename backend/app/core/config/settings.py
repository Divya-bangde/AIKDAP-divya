"""Application configuration loaded from environment variables.

Exposes a single cached `settings` instance backed by Pydantic Settings v2.
Only foundation-level configuration (app metadata, server, CORS, logging)
is defined here; settings for database, auth, and AI modules are added
alongside their respective milestones.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Database
    database_url: str
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # CORS
    backend_cors_origins: list[str] = []

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Allow CORS origins to be provided as a comma-separated string."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

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
