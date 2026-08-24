"""Sprint 11.3 (SEC-2): API documentation routes must not be reachable
in production.

`/docs`, `/redoc`, and `/openapi.json` expose the full API surface —
every route, every request/response shape. Fine in development;
nothing in this codebase depends on them functionally (confirmed: no
test, no frontend code, calls them), so production disables all three
rather than trading that reconnaissance value for a documentation
convenience nobody uses at runtime.
"""

from app.core.config import Settings
from app.main import docs_urls_for


def _settings(**overrides) -> Settings:
    base = {
        "secret_key": "test-secret",
        "database_url": "postgresql+psycopg://x:x@localhost/x",
        "celery_broker_url": "redis://localhost:6379/0",
        "celery_result_backend": "redis://localhost:6379/0",
    }
    base.update(overrides)
    return Settings(**base)


def test_production_disables_all_three_doc_routes():
    config = _settings(app_env="production")

    urls = docs_urls_for(config)

    assert urls == {"docs_url": None, "redoc_url": None, "openapi_url": None}


def test_development_keeps_doc_routes_reachable():
    config = _settings(app_env="development")

    urls = docs_urls_for(config)

    assert urls == {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


def test_staging_keeps_doc_routes_reachable():
    """The gate is production-specific, not `not development`."""
    config = _settings(app_env="staging")

    urls = docs_urls_for(config)

    assert urls == {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
