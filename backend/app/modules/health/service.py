"""Assembles the operational picture behind `GET /health` (Sprint 9G,
worker-ping fix in Sprint 9I).

One rule shapes everything here: **a health check must be cheaper than
the thing it reports on.** A check that costs real money, real GPU
time, or a slot in a daily quota stops being a diagnostic and becomes a
second source of load — and the one time you most want to poll it is
the one time you can least afford to.

So each component is checked with the cheapest evidence that is still
honest:

===========  ==========================================================
postgres     `SELECT 1` on the request's own session.
redis        `PING` on the broker connection.
worker       A Celery control ping. One broadcast, short deadline.
reranker     `GET /health` on llama-server. Loads nothing, scores
             nothing.
LLM          **Nothing at all.** Read from the provider health
             registry, which the gateway populates from traffic it was
             already sending. Phase 12's requirement, and the reason
             opening this page can never consume Gemini quota.
===========  ==========================================================

The LLM row is the interesting one, and the honesty it buys is worth
being explicit about: a provider nobody has called yet is reported
`configured`, not `healthy`. We know a key exists. We do not know that
it works, and saying so would be a guess dressed up as a measurement.

Every check is also independently failure-proof. A component check that
raises returns `unknown` for that component instead of failing the
whole report — a health endpoint that goes down when a dependency does
is the least useful thing in the system.
"""

import asyncio
import time
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from celery import Celery

from app.core.config import settings
from app.core.llm.health import ProviderRole, describe_providers, has_usable_provider
from app.core.llm.provider_health import ProviderStatus
from app.core.logging.logger import get_logger
from app.modules.health.schemas import (
    ComponentHealth,
    ComponentStatus,
    HealthResponse,
    OverallStatus,
)
from app.modules.knowledge_base.reranking import (
    RerankerHealthStatus,
    check_reranker_health,
)

logger = get_logger(__name__)

#: Components the API genuinely cannot serve without. Losing one of
#: these is `unhealthy`; losing anything else is `degraded`.
#:
#: The worker is not on this list even though research runs need it:
#: projects, assets, the knowledge base and search all keep working
#: without it, so a dead worker is a real but partial loss.
CRITICAL_COMPONENTS: frozenset[str] = frozenset({"postgres", "redis"})

#: How long the Celery control ping waits. Short on purpose — this
#: runs inside an HTTP request, and a worker that needs more than two
#: seconds to answer a broadcast is not healthy in any useful sense.
#:
#: Sprint 9I root cause: `celery_app.control.ping()` is an *undirected*
#: broadcast — it has no way to know in advance how many workers exist,
#: so it always blocks for the full timeout collecting replies, even
#: when the (single) worker answers in a few milliseconds. Measured
#: live: `control.ping(timeout=2.0)` -> ~2082ms every time;
#: `control.ping(timeout=2.0, destination=[<known name>])` -> ~3ms.
#: The worker was never slow; the broadcast's collection window was.
#: This constant remains the bound for the *cold-cache* path below,
#: where the worker set is genuinely unknown and a generous window is
#: correct. It is not "unnecessarily large" for that case — see
#: `_WorkerIdentityCache`.
WORKER_PING_TIMEOUT_SECONDS = 2.0

#: Timeout for the fast, destination-limited ping used once at least
#: one worker name is already known. Small on purpose: a healthy
#: worker that already answered once replies again in single-digit
#: milliseconds, and this path exists specifically to avoid paying the
#: full broadcast window on every request. If a destination-limited
#: ping times out here, `_check_worker` falls back to a full,
#: `WORKER_PING_TIMEOUT_SECONDS`-bounded broadcast rather than ever
#: reporting "healthy" on a guess.
WORKER_PING_FAST_TIMEOUT_SECONDS = 0.5

#: How long a discovered worker identity is trusted before the next
#: `/health` call re-confirms it with a full broadcast. Long enough
#: that a steady stream of health polls (monitoring, a seminar demo)
#: mostly takes the fast path; short enough that a restarted, renamed,
#: or scaled worker fleet is rediscovered promptly rather than being
#: silently stale for the lifetime of the process.
WORKER_IDENTITY_CACHE_TTL_SECONDS = 30.0

#: Provider states that make the *primary* model unusable but leave the
#: platform working if a fallback can pick up.
_UNUSABLE_PROVIDER_STATES: frozenset[ProviderStatus] = frozenset(
    {
        ProviderStatus.QUOTA_EXHAUSTED,
        ProviderStatus.RATE_LIMITED,
        ProviderStatus.UNAVAILABLE,
        ProviderStatus.NOT_CONFIGURED,
        ProviderStatus.CONFIGURATION_ERROR,
    }
)

#: Provider state -> component state. A straight rename rather than a
#: reinterpretation: the registry has already decided what it saw, and
#: this layer's job is to present it, not to second-guess it.
_PROVIDER_STATUS_MAP: dict[ProviderStatus, ComponentStatus] = {
    ProviderStatus.HEALTHY: ComponentStatus.HEALTHY,
    ProviderStatus.CONFIGURED: ComponentStatus.CONFIGURED,
    ProviderStatus.QUOTA_EXHAUSTED: ComponentStatus.QUOTA_EXHAUSTED,
    ProviderStatus.RATE_LIMITED: ComponentStatus.RATE_LIMITED,
    ProviderStatus.UNAVAILABLE: ComponentStatus.UNAVAILABLE,
    ProviderStatus.CONFIGURATION_ERROR: ComponentStatus.CONFIGURATION_ERROR,
    ProviderStatus.NOT_CONFIGURED: ComponentStatus.NOT_CONFIGURED,
    ProviderStatus.UNKNOWN: ComponentStatus.UNKNOWN,
}

_RERANKER_STATUS_MAP: dict[RerankerHealthStatus, ComponentStatus] = {
    RerankerHealthStatus.HEALTHY: ComponentStatus.HEALTHY,
    RerankerHealthStatus.LOADING: ComponentStatus.LOADING,
    RerankerHealthStatus.UNAVAILABLE: ComponentStatus.UNAVAILABLE,
    RerankerHealthStatus.DISABLED: ComponentStatus.DISABLED,
}


class _WorkerIdentityCache:
    """Process-local memory of which Celery worker names last answered.

    Deliberately not Redis-backed and not shared across API processes:
    the only thing this cache buys is skipping an undirected broadcast,
    and the cost of guessing wrong is bounded by falling back to that
    same broadcast, never by reporting stale "healthy" state (see
    `HealthService._check_worker`). A per-process cache is enough to
    get that benefit; adding shared storage for it would be exactly the
    kind of complexity Sprint 9I's Phase 5 says not to reach for
    without measurements demanding it.
    """

    def __init__(self) -> None:
        self._names: list[str] = []
        self._cached_at: float = 0.0

    def get(self) -> list[str]:
        if self._names and (time.monotonic() - self._cached_at) < WORKER_IDENTITY_CACHE_TTL_SECONDS:
            return self._names
        return []

    def set(self, names: list[str]) -> None:
        self._names = names
        self._cached_at = time.monotonic()

    def clear(self) -> None:
        self._names = []
        self._cached_at = 0.0


#: One cache per process, matching the lifetime of the Celery
#: connection pool `celery_app.control` already reuses.
_worker_identity_cache = _WorkerIdentityCache()


class HealthService:
    """Builds the health report for one request.

    Takes the session rather than opening its own, so the database
    check exercises the same pool and the same credentials a real
    request would — checking a connection nobody else uses would prove
    the wrong thing.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check(self) -> HealthResponse:
        """Probe every component and summarize.

        Checks run concurrently: they are independent, and three
        sequential network round trips would make the endpoint slower
        than most of what it monitors.
        """
        postgres, redis_health, worker, reranker = await asyncio.gather(
            self._check_postgres(),
            self._check_redis(),
            self._check_worker(),
            self._check_reranker(),
        )

        services: dict[str, ComponentHealth] = {
            "postgres": postgres,
            "redis": redis_health,
            "worker": worker,
            "reranker": reranker,
        }
        # Free: no provider is contacted. See the module docstring.
        for key, role in _keyed_providers(describe_providers()).items():
            services[key] = _provider_component(role)

        return HealthResponse(
            status=self._overall(services),
            app=settings.app_name,
            version=settings.app_version,
            environment=settings.app_env,
            services=services,
        )

    # -- individual checks -------------------------------------------

    async def _check_postgres(self) -> ComponentHealth:
        """Round-trip the smallest possible query."""
        try:
            await self._session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("health_postgres_failed", error_type=type(exc).__name__)
            return ComponentHealth(
                status=ComponentStatus.UNAVAILABLE,
                detail=f"The database is not reachable: {type(exc).__name__}.",
            )
        return ComponentHealth(status=ComponentStatus.HEALTHY)

    async def _check_redis(self) -> ComponentHealth:
        """`PING` the broker Celery and the cache both depend on.

        The client is created and closed per call. A health endpoint is
        not hot enough for a pooled connection to be worth the
        lifecycle management, and a long-lived client here would be one
        more thing that can be stale.
        """
        # Imported locally: `redis.asyncio` pulls in a fair amount at
        # import time, and nothing else in the API process needs it.
        from redis.asyncio import Redis

        client: Redis | None = None
        try:
            client = Redis.from_url(settings.celery_broker_url)
            await asyncio.wait_for(client.ping(), timeout=WORKER_PING_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("health_redis_failed", error_type=type(exc).__name__)
            return ComponentHealth(
                status=ComponentStatus.UNAVAILABLE,
                detail=f"Redis is not reachable: {type(exc).__name__}.",
            )
        finally:
            if client is not None:
                await client.aclose()
        return ComponentHealth(status=ComponentStatus.HEALTHY)

    async def _check_worker(self) -> ComponentHealth:
        """Ask the Celery workers to identify themselves.

        `control.ping` is a blocking broadcast, so it runs in a thread:
        blocking the event loop inside a health check would let a dead
        worker stall every other request on the process.

        Sprint 9I: an *undirected* `control.ping()` always blocks for
        the full timeout, whatever the worker's actual reply latency —
        it has no way to know in advance how many workers to wait for,
        so it just waits out the window (measured: ~2082ms for a
        worker that replies in single-digit milliseconds). A
        *destination-limited* ping, given the worker names from a
        previous successful broadcast, returns as soon as those workers
        answer instead (measured: ~3ms). So: try the fast, targeted
        ping first if we already know who should answer; fall back to
        the full, generously-timed broadcast whenever that cache is
        empty, expired, or wrong. The fallback is what keeps this
        honest — a worker that stops answering is still detected within
        `WORKER_PING_TIMEOUT_SECONDS`, exactly as before.

        Reported as `unavailable` rather than critical — see
        `CRITICAL_COMPONENTS`. Research runs stop without a worker, but
        the rest of the platform does not.
        """
        from app.workers.celery_app import celery_app

        cached_names = _worker_identity_cache.get()
        if cached_names:
            fast_health = await self._ping_worker(
                celery_app,
                timeout=WORKER_PING_FAST_TIMEOUT_SECONDS,
                destination=cached_names,
            )
            if fast_health is not None:
                names = fast_health
                if set(names) == set(cached_names):
                    _worker_identity_cache.set(names)
                    return ComponentHealth(
                        status=ComponentStatus.HEALTHY,
                        meta={"workers": len(names), "names": names},
                    )
            # Cache was stale (partial reply, renamed/scaled worker, or
            # the fast ping timed out): fall through to a full,
            # authoritative broadcast rather than trust a guess.
            _worker_identity_cache.clear()

        full_health = await self._ping_worker(
            celery_app, timeout=WORKER_PING_TIMEOUT_SECONDS, destination=None
        )
        if full_health is None:
            return ComponentHealth(
                status=ComponentStatus.UNKNOWN,
                detail="The worker could not be queried.",
            )

        names = full_health
        if not names:
            return ComponentHealth(
                status=ComponentStatus.UNAVAILABLE,
                detail="No Celery worker answered the ping.",
                meta={"workers": 0},
            )
        _worker_identity_cache.set(names)
        return ComponentHealth(
            status=ComponentStatus.HEALTHY,
            meta={"workers": len(names), "names": names},
        )

    async def _ping_worker(
        self, celery_app: "Celery", *, timeout: float, destination: list[str] | None
    ) -> list[str] | None:
        """Run one `control.ping`, off the event loop, and return the
        worker names that answered — or `None` if the call itself
        raised (broker unreachable, etc.), which the caller reports as
        `unknown` rather than `unavailable`: those are different facts.
        """
        try:
            replies = await asyncio.wait_for(
                asyncio.to_thread(
                    celery_app.control.ping, timeout=timeout, destination=destination
                ),
                timeout=timeout * 2,
            )
        except Exception as exc:
            logger.warning(
                "health_worker_ping_failed",
                error_type=type(exc).__name__,
                destination=bool(destination),
            )
            return None
        return [name for reply in (replies or []) for name in reply]

    async def _check_reranker(self) -> ComponentHealth:
        """Liveness of the host llama-server serving BGE-Reranker-v2-m3.

        Names the model in `meta` deliberately: Sprint 9D's constraint
        is that this exact model is what runs, and a health endpoint
        that said only "reranker: healthy" would be equally true of a
        substituted one.
        """
        try:
            health = await check_reranker_health()
        except Exception as exc:  # pragma: no cover - the probe catches its own
            logger.warning("health_reranker_failed", error_type=type(exc).__name__)
            return ComponentHealth(
                status=ComponentStatus.UNKNOWN,
                detail=f"The reranker probe failed: {type(exc).__name__}.",
            )

        return ComponentHealth(
            status=_RERANKER_STATUS_MAP.get(health.status, ComponentStatus.UNKNOWN),
            detail=health.detail,
            latency_ms=health.latency_ms,
            meta={"model": health.model, "endpoint": health.endpoint},
        )

    # -- summary ------------------------------------------------------

    def _overall(self, services: dict[str, ComponentHealth]) -> OverallStatus:
        """Reduce the component states to one verdict.

        Deliberately conservative about `healthy` and deliberately
        reluctant about `unhealthy`. An operator should be able to read
        `degraded` as "something needs attention, the platform is still
        serving" and `unhealthy` as "it is not serving" — which only
        holds if optional components never push it that far.
        """
        for name in CRITICAL_COMPONENTS:
            if services[name].status != ComponentStatus.HEALTHY:
                return OverallStatus.UNHEALTHY

        if not has_usable_provider():
            # No model can answer, so grounded synthesis cannot run.
            # Still not `unhealthy`: retrieval, projects, assets and
            # the knowledge base are all unaffected, and the platform
            # is genuinely serving those.
            return OverallStatus.DEGRADED

        degraded = {
            ComponentStatus.DEGRADED,
            ComponentStatus.UNAVAILABLE,
            ComponentStatus.QUOTA_EXHAUSTED,
            ComponentStatus.RATE_LIMITED,
            ComponentStatus.CONFIGURATION_ERROR,
            ComponentStatus.LOADING,
            ComponentStatus.UNKNOWN,
        }
        if any(component.status in degraded for component in services.values()):
            return OverallStatus.DEGRADED

        # `configured`, `disabled` and `not_configured` are left out on
        # purpose: an untried provider and a deliberately disabled
        # component are normal states, not problems, and reporting them
        # as degraded would leave a correctly-configured deployment
        # permanently yellow.
        return OverallStatus.HEALTHY


def _keyed_providers(roles: list[ProviderRole]) -> dict[str, ProviderRole]:
    """Name each chain entry for the `services` map.

    The provider name alone (`gemini`, `groq`) is the readable choice
    and is what this deployment produces, since its three chain entries
    are three different providers.

    It stops being unique the moment a chain falls back from one model
    to another on the *same* provider — which is a sensible thing to
    configure, because Gemini's daily quota is per model. Those entries
    are disambiguated by role rather than silently overwriting each
    other, since a `/health` that hid the fallback would be worse than
    one with a slightly longer key.
    """
    providers = [role.provider for role in roles]
    return {
        (role.provider if providers.count(role.provider) == 1 else f"{role.provider}:{role.role}"): role
        for role in roles
    }


def _provider_component(role: ProviderRole) -> ComponentHealth:
    """Render one LLM provider as a health component."""
    health = role.health
    status = _PROVIDER_STATUS_MAP.get(health.status, ComponentStatus.UNKNOWN)

    detail = None
    if health.status in _UNUSABLE_PROVIDER_STATES:
        if health.status is ProviderStatus.NOT_CONFIGURED:
            detail = f"No API key is configured for {role.provider}."
        else:
            detail = health.error_message
    return ComponentHealth(
        status=status,
        detail=detail,
        meta={
            "role": role.role,
            "model": role.model,
            # Present so an operator can tell "we have never called it"
            # from "it worked a second ago" — the same information the
            # `configured` vs `healthy` split encodes, with a number.
            "observed_seconds_ago": (
                round(health.observed_seconds_ago, 1)
                if health.observed_seconds_ago is not None
                else None
            ),
            "blocked": health.blocked,
            "retry_after_seconds": (
                round(health.retry_after_seconds, 1)
                if health.retry_after_seconds is not None
                else None
            ),
            "error_type": health.error_type,
        },
    )
