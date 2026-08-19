"""Sprint 9G: `GET /health` and the component probes behind it.

Two things are being defended here, and they pull in opposite
directions:

1. **The report must be truthful.** A provider is never reported
   `healthy` because a key exists, and a dead reranker is never
   reported healthy because retrieval still works without it.
2. **The report must be free.** No inference, no reranking, no quota.
   The tests assert this directly rather than trusting the
   implementation, because "the health check quietly burns the daily
   quota" is the kind of regression that is invisible until the day it
   matters.

Offline throughout. Redis, Celery and the reranker are replaced with
doubles; Postgres is the real test database, since a `SELECT 1` against
a live pool is the thing the check actually claims to do.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.llm import gateway as gateway_module
from app.core.llm.errors import LLMQuotaExhaustedError, LLMServiceUnavailableError
from app.core.llm.provider_health import get_provider_health_registry
from app.modules.health.schemas import ComponentStatus, OverallStatus
from app.modules.health.service import HealthService
from app.modules.knowledge_base.reranking import (
    RerankerHealthStatus,
    check_reranker_health,
)

GEMINI = "gemini/gemini-flash-latest"
GROQ = "groq/openai/gpt-oss-120b"
FAKE_KEY = "AIzaSyTESTKEY_MUST_NEVER_BE_LOGGED_0123456789"


@pytest.fixture
def configured(monkeypatch):
    """A primary and one fallback, both credentialed."""
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr(FAKE_KEY))
    monkeypatch.setattr(settings, "groq_api_key", SecretStr("gsk_" + "x" * 32))
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "default_llm", GEMINI)
    monkeypatch.setattr(settings, "fallback_llm", GROQ)
    monkeypatch.setattr(settings, "secondary_fallback_llm", "")


@pytest.fixture
def healthy_infrastructure(monkeypatch):
    """Make Redis, Celery and the reranker all report healthy."""
    from app.modules.health import service as service_module

    async def reranker_ok(**_kwargs):
        return SimpleNamespace(
            status=RerankerHealthStatus.HEALTHY,
            model=settings.reranker_model,
            endpoint="http://reranker/health",
            latency_ms=3,
            detail=None,
        )

    monkeypatch.setattr(service_module, "check_reranker_health", reranker_ok)
    monkeypatch.setattr(
        HealthService,
        "_check_redis",
        AsyncMock(return_value=_component(ComponentStatus.HEALTHY)),
    )
    monkeypatch.setattr(
        HealthService,
        "_check_worker",
        AsyncMock(return_value=_component(ComponentStatus.HEALTHY)),
    )


def _component(status: ComponentStatus):
    from app.modules.health.schemas import ComponentHealth

    return ComponentHealth(status=status)


# ---------------------------------------------------------------------------
# The endpoint must not cost anything (Phase 12, 32)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_never_calls_a_model(
    session, configured, healthy_infrastructure, monkeypatch
):
    """The single most important property of this endpoint.

    Anyone can poll `/health`. If it generated, a monitor on a 30s
    interval would exhaust a 20-request daily quota before breakfast.
    """
    call = AsyncMock()
    monkeypatch.setattr(gateway_module, "acompletion", call)

    await HealthService(session).check()

    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_never_reranks(session, configured, monkeypatch):
    """Phase 13: a liveness GET, not a scoring request.

    Reranking on every poll would spend GPU time to learn something a
    liveness route already answers.
    """
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    await check_reranker_health(transport=httpx.MockTransport(record))

    assert [request.method for request in requests] == ["GET"]
    assert requests[0].url.path == settings.reranker_health_path


# ---------------------------------------------------------------------------
# Provider states (Phase 23)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_key_alone_is_reported_configured_not_healthy(
    session, configured, healthy_infrastructure
):
    """"We have a credential" is not "it works"."""
    report = await HealthService(session).check()

    assert report.services["gemini"].status == ComponentStatus.CONFIGURED
    assert report.services["groq"].status == ComponentStatus.CONFIGURED


@pytest.mark.asyncio
async def test_a_real_success_is_reported_healthy(
    session, configured, healthy_infrastructure
):
    get_provider_health_registry().record_success(GEMINI)

    report = await HealthService(session).check()

    assert report.services["gemini"].status == ComponentStatus.HEALTHY
    assert report.status == OverallStatus.HEALTHY


@pytest.mark.asyncio
async def test_quota_exhaustion_is_visible_and_degrades_the_platform(
    session, configured, healthy_infrastructure
):
    """The Sprint 9F blocker, now legible without reading logs."""
    get_provider_health_registry().record_failure(
        GEMINI, error=LLMQuotaExhaustedError("daily quota spent")
    )

    report = await HealthService(session).check()

    assert report.services["gemini"].status == ComponentStatus.QUOTA_EXHAUSTED
    assert report.services["gemini"].meta["blocked"] is True
    # Not `unhealthy`: Groq can still answer, and retrieval is
    # untouched either way.
    assert report.status == OverallStatus.DEGRADED


@pytest.mark.asyncio
async def test_an_unavailable_provider_is_reported_unavailable(
    session, configured, healthy_infrastructure
):
    get_provider_health_registry().record_failure(
        GROQ, error=LLMServiceUnavailableError("503")
    )

    report = await HealthService(session).check()

    assert report.services["groq"].status == ComponentStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_an_unconfigured_fallback_is_shown_not_hidden(
    session, monkeypatch, healthy_infrastructure
):
    """Phase 30: an optional provider with no key must be visible...

    ...and must not, on its own, drag the platform's status down. "The
    fallback you think you have is not set up" is something to learn
    before an outage, not during one.
    """
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr(FAKE_KEY))
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "default_llm", GEMINI)
    monkeypatch.setattr(settings, "fallback_llm", GROQ)
    monkeypatch.setattr(settings, "secondary_fallback_llm", "")

    report = await HealthService(session).check()

    assert report.services["groq"].status == ComponentStatus.NOT_CONFIGURED
    assert report.services["groq"].detail is not None
    assert report.status == OverallStatus.HEALTHY


@pytest.mark.asyncio
async def test_no_usable_provider_degrades_but_does_not_kill_the_platform(
    session, configured, healthy_infrastructure
):
    """Scenario E at the health level.

    Nothing can synthesize — but projects, assets, the knowledge base
    and search are all still serving, so calling this `unhealthy` would
    misdirect whoever is holding the pager.
    """
    registry = get_provider_health_registry()
    registry.record_failure(GEMINI, error=LLMQuotaExhaustedError("spent"))
    registry.record_failure(GROQ, error=LLMQuotaExhaustedError("spent"))

    report = await HealthService(session).check()

    assert report.status == OverallStatus.DEGRADED


# ---------------------------------------------------------------------------
# Reranker (Phases 13, 14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reranker_health_reports_the_exact_model():
    """Sprint 9D's constraint, made checkable.

    "reranker: healthy" would be equally true of a substituted model.
    Naming it is what makes the report meaningful.
    """
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"status": "ok"}))

    health = await check_reranker_health(transport=transport)

    assert health.status is RerankerHealthStatus.HEALTHY
    assert health.model == settings.reranker_model
    assert "bge-reranker-v2-m3" in health.model


@pytest.mark.asyncio
async def test_a_dead_reranker_is_never_reported_healthy():
    """Phase 14. Retrieval degrades gracefully; the report must not."""

    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    health = await check_reranker_health(transport=httpx.MockTransport(refuse))

    assert health.status is RerankerHealthStatus.UNAVAILABLE
    assert health.detail is not None


@pytest.mark.asyncio
async def test_a_loading_reranker_is_distinguished_from_a_dead_one():
    """Waiting and restarting are different remedies."""
    transport = httpx.MockTransport(lambda _r: httpx.Response(503))

    health = await check_reranker_health(transport=transport)

    assert health.status is RerankerHealthStatus.LOADING


@pytest.mark.asyncio
async def test_a_disabled_reranker_is_not_a_fault(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", False)

    health = await check_reranker_health()

    assert health.status is RerankerHealthStatus.DISABLED


@pytest.mark.asyncio
async def test_a_dead_reranker_degrades_the_report(
    session, configured, monkeypatch
):
    """Scenario G: visible in `/health`, not only in a log line."""
    from app.modules.health import service as service_module

    async def reranker_down(**_kwargs):
        return SimpleNamespace(
            status=RerankerHealthStatus.UNAVAILABLE,
            model=settings.reranker_model,
            endpoint="http://reranker/health",
            latency_ms=1,
            detail="Could not reach the reranker: ConnectError.",
        )

    monkeypatch.setattr(service_module, "check_reranker_health", reranker_down)
    monkeypatch.setattr(
        HealthService,
        "_check_redis",
        AsyncMock(return_value=_component(ComponentStatus.HEALTHY)),
    )
    monkeypatch.setattr(
        HealthService,
        "_check_worker",
        AsyncMock(return_value=_component(ComponentStatus.HEALTHY)),
    )

    report = await HealthService(session).check()

    assert report.services["reranker"].status == ComponentStatus.UNAVAILABLE
    assert report.services["reranker"].meta["model"] == settings.reranker_model
    assert report.status == OverallStatus.DEGRADED


# ---------------------------------------------------------------------------
# Core components and secrecy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_is_actually_queried(session, configured, healthy_infrastructure):
    """The check runs `SELECT 1` on the real pool, not a config read."""
    report = await HealthService(session).check()

    assert report.services["postgres"].status == ComponentStatus.HEALTHY


@pytest.mark.asyncio
async def test_losing_a_critical_component_is_unhealthy(
    session, configured, healthy_infrastructure, monkeypatch
):
    """Redis is not optional; the report says so."""
    monkeypatch.setattr(
        HealthService,
        "_check_redis",
        AsyncMock(return_value=_component(ComponentStatus.UNAVAILABLE)),
    )

    report = await HealthService(session).check()

    assert report.status == OverallStatus.UNHEALTHY


@pytest.mark.asyncio
async def test_the_report_contains_no_credentials(
    session, configured, healthy_infrastructure
):
    """Phase 31. The endpoint is unauthenticated, so this is load-bearing."""
    get_provider_health_registry().record_failure(
        GEMINI,
        error=LLMQuotaExhaustedError(f"provider said api_key={FAKE_KEY}"),
    )

    report = await HealthService(session).check()
    rendered = report.model_dump_json()

    assert FAKE_KEY not in rendered
    assert "gsk_" not in rendered


# ---------------------------------------------------------------------------
# Worker-ping caching (Sprint 9I): root cause was an undirected
# `control.ping()` always blocking for its full timeout (~2s, measured
# live) instead of returning as soon as the worker answered. The fix
# caches the worker names from one authoritative broadcast and uses a
# fast, destination-limited ping while that cache is fresh, falling
# back to a full broadcast whenever it is empty, expired, or wrong —
# never reporting `healthy` on a guess.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def clean_worker_cache():
    """The cache is process-local module state, so tests must not leak
    into each other through it."""
    from app.modules.health import service as service_module

    service_module._worker_identity_cache.clear()
    yield
    service_module._worker_identity_cache.clear()


def _fake_ping(replies_by_call):
    """A `celery_app.control.ping` double that records each call's
    kwargs and returns the next canned reply."""
    calls = []

    def ping(*, timeout, destination=None):
        calls.append({"timeout": timeout, "destination": destination})
        return replies_by_call.pop(0)

    return ping, calls


@pytest.mark.asyncio
async def test_a_cold_check_does_a_full_broadcast_and_populates_the_cache(
    session, clean_worker_cache, monkeypatch
):
    from app.modules.health import service as service_module
    from app.workers.celery_app import celery_app

    ping, calls = _fake_ping([[{"celery@abc": {"ok": "pong"}}]])
    monkeypatch.setattr(celery_app.control, "ping", ping)

    result = await HealthService(session)._check_worker()

    assert result.status == ComponentStatus.HEALTHY
    assert result.meta["names"] == ["celery@abc"]
    # No cache yet: the call must be an undirected broadcast, not a guess.
    assert calls == [{"timeout": service_module.WORKER_PING_TIMEOUT_SECONDS, "destination": None}]
    assert service_module._worker_identity_cache.get() == ["celery@abc"]


@pytest.mark.asyncio
async def test_a_warm_check_uses_a_fast_destination_limited_ping(
    session, clean_worker_cache, monkeypatch
):
    from app.modules.health import service as service_module
    from app.workers.celery_app import celery_app

    service_module._worker_identity_cache.set(["celery@abc"])
    ping, calls = _fake_ping([[{"celery@abc": {"ok": "pong"}}]])
    monkeypatch.setattr(celery_app.control, "ping", ping)

    result = await HealthService(session)._check_worker()

    assert result.status == ComponentStatus.HEALTHY
    # Exactly one call: the fast, targeted ping, not the full broadcast.
    assert calls == [
        {
            "timeout": service_module.WORKER_PING_FAST_TIMEOUT_SECONDS,
            "destination": ["celery@abc"],
        }
    ]


@pytest.mark.asyncio
async def test_a_stale_cache_falls_back_to_a_full_broadcast_and_recovers(
    session, clean_worker_cache, monkeypatch
):
    """The worker was renamed/restarted since the cache was populated:
    the fast ping to the old name gets no reply, so this must fall
    back to an authoritative broadcast rather than report `unavailable`
    off a guess."""
    from app.modules.health import service as service_module
    from app.workers.celery_app import celery_app

    service_module._worker_identity_cache.set(["celery@old"])
    ping, calls = _fake_ping(
        [
            [],  # fast ping to the stale name: nobody answers
            [{"celery@new": {"ok": "pong"}}],  # full broadcast: real worker found
        ]
    )
    monkeypatch.setattr(celery_app.control, "ping", ping)

    result = await HealthService(session)._check_worker()

    assert result.status == ComponentStatus.HEALTHY
    assert result.meta["names"] == ["celery@new"]
    assert len(calls) == 2
    assert calls[0]["destination"] == ["celery@old"]
    assert calls[1]["destination"] is None
    # The cache now reflects reality, not the stale guess.
    assert service_module._worker_identity_cache.get() == ["celery@new"]


@pytest.mark.asyncio
async def test_a_genuinely_dead_worker_is_still_reported_unavailable(
    session, clean_worker_cache, monkeypatch
):
    """Cache-miss recovery must not paper over a real outage: if the
    full broadcast also gets no reply, this is `unavailable`, not
    `healthy`."""
    from app.modules.health import service as service_module
    from app.workers.celery_app import celery_app

    service_module._worker_identity_cache.set(["celery@old"])
    ping, calls = _fake_ping([[], []])
    monkeypatch.setattr(celery_app.control, "ping", ping)

    result = await HealthService(session)._check_worker()

    assert result.status == ComponentStatus.UNAVAILABLE
    assert result.meta == {"workers": 0}
    assert len(calls) == 2
    assert service_module._worker_identity_cache.get() == []


@pytest.mark.asyncio
async def test_a_broken_broker_is_unknown_not_unavailable(
    session, clean_worker_cache, monkeypatch
):
    """A ping that raises (broker unreachable) is a different fact than
    a ping that got no reply — the report must not conflate them."""
    from app.workers.celery_app import celery_app

    def broken_ping(*, timeout, destination=None):
        raise ConnectionError("broker unreachable (simulated)")

    monkeypatch.setattr(celery_app.control, "ping", broken_ping)

    result = await HealthService(session)._check_worker()

    assert result.status == ComponentStatus.UNKNOWN
