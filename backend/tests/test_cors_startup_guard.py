"""Sprint 11.2 (SEC-1): production must never boot with the CORS
wildcard fallback active.

`CORSMiddleware`'s `allow_origins=settings.backend_cors_origins or
["*"]` fallback is fine in development, but combined with
`allow_credentials=True` in production it would let any origin make an
authenticated cross-origin request (Starlette reflects the request's
real `Origin` header whenever credentials are allowed, rather than
sending a literal `*`). `validate_cors_configuration` is the guard that
refuses to let that combination boot silently.
"""

import pytest

from app.core.config import Settings
from app.main import validate_cors_configuration


def _settings(**overrides) -> Settings:
    base = {
        "secret_key": "test-secret",
        "database_url": "postgresql+psycopg://x:x@localhost/x",
        "celery_broker_url": "redis://localhost:6379/0",
        "celery_result_backend": "redis://localhost:6379/0",
    }
    base.update(overrides)
    return Settings(**base)


def test_production_with_no_cors_origins_refuses_to_start():
    config = _settings(app_env="production", backend_cors_origins=[])

    with pytest.raises(RuntimeError, match="BACKEND_CORS_ORIGINS"):
        validate_cors_configuration(config)


def test_production_with_explicit_origins_starts_normally():
    config = _settings(
        app_env="production",
        backend_cors_origins=["https://aikdap-divya-e4y7.vercel.app"],
    )

    validate_cors_configuration(config)  # must not raise


def test_development_with_no_cors_origins_is_unaffected():
    """The wildcard fallback stays available for local dev convenience."""
    config = _settings(app_env="development", backend_cors_origins=[])

    validate_cors_configuration(config)  # must not raise


def test_staging_with_no_cors_origins_is_unaffected():
    """The guard is production-specific, not `not development`."""
    config = _settings(app_env="staging", backend_cors_origins=[])

    validate_cors_configuration(config)  # must not raise
