"""Configuration package exposing the application settings singleton."""

from app.core.config.settings import Settings, get_settings, settings

__all__ = ["Settings", "get_settings", "settings"]
