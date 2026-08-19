"""What the gateway has learned about each provider (Sprint 9G).

A deliberately small circuit breaker. It exists to answer two questions:

1. *Should the next call even try this provider?* Once Gemini has
   reported its daily quota spent, every further request that day costs
   a round trip to be told the same thing. Skipping straight to the
   fallback is both faster and cheaper.
2. *What is the operator seeing?* `GET /health` reports provider state
   from here, so it can say "gemini: quota_exhausted" without spending
   an inference request to find out. That is the Phase 12 requirement:
   opening the health page must never consume quota.

## Passive, not probing

Nothing in this module calls a provider. State is a by-product of real
traffic — the gateway records the outcome of calls it was already
making. A provider nobody has called yet is reported as `configured`
(we have a key, we have not tried it) rather than `healthy`, because
"a key exists" is not evidence that anything works. Phase 23 makes that
distinction a test.

## Bounded, and self-healing

Every non-healthy state carries a cooldown. When it expires the entry
decays back to `configured` and the provider is tried again. That is
what keeps this from becoming a breaker that latches open forever:
recovery needs no operator action and no separate probe loop.

The daily-quota cooldown is the interesting one. The quota resets at
midnight Pacific, which this process has no reliable way to compute
(the reset is a Google-side boundary, not a local one), so instead of
guessing the wall-clock moment the entry simply expires after
`LLM_QUOTA_COOLDOWN_SECONDS` — one hour by default. The cost of being
wrong is bounded and tiny: at worst one wasted request per hour that
re-confirms the quota is still spent and re-arms the cooldown. The cost
of the alternative — no cooldown at all — would be a provider that
stays disabled until someone restarts the process.

## Keyed by model, not by provider

State is recorded against the full model id (`gemini/gemini-flash-latest`),
not the provider (`gemini`). That is not a detail — Gemini's free-tier
limit is `GenerateRequestsPerDayPerProjectPerModel`, and the live
refusal that motivated this sprint names the model it applies to::

    "quotaDimensions": {"model": "gemini-3.7-flash"}

Keying by provider would mean one exhausted model disabling every other
model that provider serves, and it would break the most natural
mitigation available: configuring a second model on the *same* provider
as the fallback, which has its own separate daily allowance.

The trade is small and in the right direction. A provider-wide outage
(a 503, an unreachable host) is recorded against only the model that
saw it, so a same-provider fallback costs one extra failed call before
it is marked too. Paying one wasted request to avoid wrongly disabling
a working model is the better side of that bargain.

## Shared via Redis, with an in-process fallback (Sprint 9H)

Sprint 9G scoped a shared breaker out and kept state in one process's
memory: the API container and the Celery worker learned independently,
so a quota exhaustion the worker discovered mid-research-run stayed
invisible to the API's `/health` until the API made its own failing
call. `RedisProviderHealthRegistry` closes that gap by storing the
same state in Redis — already-required infrastructure, the same broker
Celery uses — keyed by model, with a TTL equal to each status's
cooldown so a blocked entry expires on its own.

It is deliberately not the *only* implementation. `ProviderHealthRegistry`
(the in-process class below) still exists, unchanged, for two reasons:
tests that want an isolated breaker construct it directly, and
`RedisProviderHealthRegistry` uses one internally as its fallback when
Redis itself is unreachable. A Redis outage must not become a second,
worse outage in the LLM path — see that class's docstring for how the
degradation works.

## Bounded, and self-healing

Every non-healthy state carries a cooldown. When it expires the entry
decays back to `configured` and the provider is tried again. That is
what keeps this from becoming a breaker that latches open forever:
recovery needs no operator action and no separate probe loop.

The daily-quota cooldown is the interesting one. The quota resets at
midnight Pacific, which this process has no reliable way to compute
(the reset is a Google-side boundary, not a local one), so instead of
guessing the wall-clock moment the entry simply expires after
`LLM_QUOTA_COOLDOWN_SECONDS` — one hour by default. The cost of being
wrong is bounded and tiny: at worst one wasted request per hour that
re-confirms the quota is still spent and re-arms the cooldown. The cost
of the alternative — no cooldown at all — would be a provider that
stays disabled until someone restarts the process.

This is also, deliberately, not a claim about Google's actual reset
time: the TTL is a circuit-breaker cooldown, not a calendar.
"""

import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.core.config import settings
from app.core.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

#: Every Redis key this module writes carries this prefix, so a
#: `SCAN MATCH aikdap:llm:health:*` finds exactly this module's state
#: and nothing another feature might store in the same Redis instance.
REDIS_KEY_PREFIX = "aikdap:llm:health:"


class ProviderStatus(str, Enum):
    """How usable a provider looks right now.

    Ordered from most to least usable. The three "we have not observed
    it" states at the bottom are kept distinct on purpose: an operator
    reading `/health` needs to tell "no key" from "key present, never
    exercised" from "we have no idea".
    """

    #: A real call succeeded. The only status that means *working*.
    HEALTHY = "healthy"
    #: Credentials are configured; no call has been made yet, or the
    #: last failure's cooldown has expired. Not a claim that it works.
    CONFIGURED = "configured"
    #: A long-window (typically daily) quota is spent. Blocking.
    QUOTA_EXHAUSTED = "quota_exhausted"
    #: A short-window rate limit was hit. Blocking, briefly.
    RATE_LIMITED = "rate_limited"
    #: Unreachable, timing out, overloaded, or failing in a way we do
    #: not recognise. Blocking, briefly.
    UNAVAILABLE = "unavailable"
    #: Credentials rejected, model not found, or a request the provider
    #: refuses. Reported but NOT blocking — see `BLOCKING_STATUSES`.
    CONFIGURATION_ERROR = "configuration_error"
    #: No credentials. Nothing to try.
    NOT_CONFIGURED = "not_configured"
    #: Provider is unknown to this registry.
    UNKNOWN = "unknown"


#: Statuses that make the gateway skip a provider rather than call it.
#:
#: `CONFIGURATION_ERROR` is deliberately absent. A rejected credential
#: is terminal for the whole call (see `errors.TERMINAL_ERRORS`), so it
#: never reaches the fallback chain anyway; treating it as blocking too
#: would mean a single 401 silently rerouted later traffic to a
#: different provider instead of surfacing the misconfiguration.
BLOCKING_STATUSES: frozenset[ProviderStatus] = frozenset(
    {
        ProviderStatus.QUOTA_EXHAUSTED,
        ProviderStatus.RATE_LIMITED,
        ProviderStatus.UNAVAILABLE,
    }
)


def status_for_error(error: BaseException) -> ProviderStatus:
    """Map a gateway error onto the provider state it implies.

    Ordered most-specific-first, because the rate-limit family is a
    subclass hierarchy: `LLMQuotaExhaustedError` and
    `LLMRateLimitError` are both `LLMProviderError`, and testing the
    base class first would collapse exactly the distinction this sprint
    is built on.
    """
    if isinstance(error, LLMQuotaExhaustedError):
        return ProviderStatus.QUOTA_EXHAUSTED
    if isinstance(error, LLMRateLimitError):
        return ProviderStatus.RATE_LIMITED
    if isinstance(
        error,
        (
            LLMConfigurationError,
            LLMAuthenticationError,
            LLMInvalidRequestError,
            LLMModelNotFoundError,
        ),
    ):
        return ProviderStatus.CONFIGURATION_ERROR
    if isinstance(
        error, (LLMServiceUnavailableError, LLMTimeoutError, LLMConnectionError)
    ):
        return ProviderStatus.UNAVAILABLE
    # Any other `LLMError`, including the unclassified base
    # `LLMProviderError`: something is wrong upstream, treat the
    # provider as briefly unavailable rather than guessing at a cause.
    return ProviderStatus.UNAVAILABLE


@dataclass(frozen=True)
class ProviderHealth:
    """One model's last observed state. Contains no credentials."""

    provider: str
    status: ProviderStatus
    #: The model this state belongs to. The registry's key, because
    #: Gemini's daily quota is per model, not per project.
    model: str | None = None
    #: Seconds since the observation, or `None` if never observed.
    observed_seconds_ago: float | None = None
    error_type: str | None = None
    #: Already scrubbed — it originates in an `LLMError`, whose
    #: constructor runs `scrub_secrets`.
    error_message: str | None = None
    #: Whether the gateway will currently skip this provider.
    blocked: bool = False
    #: Seconds until a blocking status decays back to `configured`.
    retry_after_seconds: float | None = None

    def as_dict(self) -> dict[str, object]:
        """A plain, JSON-safe dict. Safe to log and to serve."""
        return {
            "provider": self.provider,
            "status": self.status.value,
            "model": self.model,
            "observed_seconds_ago": (
                round(self.observed_seconds_ago, 1)
                if self.observed_seconds_ago is not None
                else None
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "blocked": self.blocked,
            "retry_after_seconds": (
                round(self.retry_after_seconds, 1)
                if self.retry_after_seconds is not None
                else None
            ),
        }


@dataclass
class _Observation:
    """The mutable record behind one model. Internal to the registry."""

    status: ProviderStatus
    at: float
    error_type: str | None = None
    error_message: str | None = None


def _provider_of(model: str) -> str:
    """The provider segment of a LiteLLM model id.

    Duplicated from `gateway.provider_of` rather than imported: this
    module must not import the gateway (the gateway imports it), and
    the alternative — a third module for one `split` — is not worth the
    file.
    """
    return model.split("/", 1)[0] if "/" in model else "default"


class ProviderHealthRegistry:
    """Remembers how each model last behaved.

    Guarded by a lock: the API process serves concurrent requests on one
    event loop, but the Celery worker runs tasks in a pool, and a
    dict-of-dataclass mutated from several threads is not something to
    leave to chance for the sake of saving a mutex nobody will ever
    measure.
    """

    def __init__(self) -> None:
        self._observations: dict[str, _Observation] = {}
        self._lock = threading.Lock()

    # -- recording ---------------------------------------------------

    def record_success(self, model: str) -> None:
        """Note that a real call to `model` succeeded.

        Clears any prior failure outright rather than decaying it: one
        success is direct evidence that the model is serving, which
        beats any amount of remembered failure.
        """
        with self._lock:
            self._observations[model] = _Observation(
                status=ProviderStatus.HEALTHY, at=time.monotonic()
            )

    def record_failure(self, model: str, *, error: BaseException) -> ProviderStatus:
        """Note that a real call to `model` failed, and how."""
        status = status_for_error(error)
        message = str(error) if isinstance(error, LLMError) else None
        with self._lock:
            self._observations[model] = _Observation(
                status=status,
                at=time.monotonic(),
                error_type=type(error).__name__,
                error_message=message[:500] if message else None,
            )
        if status in BLOCKING_STATUSES:
            logger.warning(
                "llm_provider_marked_unavailable",
                provider=_provider_of(model),
                model=model,
                status=status.value,
                error_type=type(error).__name__,
                cooldown_seconds=_cooldown_for(status),
            )
        return status

    # -- reading -----------------------------------------------------

    def status(self, model: str) -> ProviderHealth:
        """Report `model`'s current state, applying cooldown decay.

        Never raises and never calls out: this is the function `/health`
        depends on, and it must be free.
        """
        provider = _provider_of(model)
        baseline = _baseline_status(provider)
        with self._lock:
            observation = self._observations.get(model)

        if observation is None:
            return ProviderHealth(provider=provider, status=baseline, model=model)

        age = time.monotonic() - observation.at
        return _resolve_health(
            provider=provider,
            model=model,
            status=observation.status,
            age=age,
            error_type=observation.error_type,
            error_message=observation.error_message,
            baseline=baseline,
        )

    def is_blocked(self, model: str) -> bool:
        """Whether the gateway should skip `model` for now."""
        return self.status(model).blocked

    def snapshot(self, models: list[str]) -> dict[str, ProviderHealth]:
        """State for several models at once, for the health endpoint."""
        return {model: self.status(model) for model in models}

    def reset(self) -> None:
        """Forget everything. For tests, and for nothing else.

        Without this, one test's recorded failure would leak into the
        next through the module-level singleton and make the suite
        order-dependent.
        """
        with self._lock:
            self._observations.clear()


def _baseline_status(provider: str) -> ProviderStatus:
    """What to report when there is no (or no longer any) observation."""
    return ProviderStatus.CONFIGURED if is_provider_configured(provider) else ProviderStatus.NOT_CONFIGURED


def _resolve_health(
    *,
    provider: str,
    model: str,
    status: ProviderStatus,
    age: float,
    error_type: str | None,
    error_message: str | None,
    baseline: ProviderStatus,
) -> ProviderHealth:
    """Turn one observation plus its age into a `ProviderHealth`.

    The shared core of both backends' `status()`: given "what was last
    observed" and "how long ago", decide whether the cooldown has
    expired and whether the provider is currently blocked. Local and
    Redis differ only in *where* the observation and its age come from
    (a monotonic clock in one process vs. a wall-clock timestamp read
    back from Redis) — once they have those two things, the decision
    is identical, and duplicating it per backend would be exactly the
    kind of drift risk that turns "the same rule in two places" into
    two different rules over time.
    """
    cooldown = _cooldown_for(status)
    if cooldown is not None and age >= cooldown:
        # The observation has aged out. Report the configuration
        # baseline rather than a stale verdict — but keep the error
        # metadata so an operator can still see what happened.
        return ProviderHealth(
            provider=provider,
            status=baseline,
            model=model,
            observed_seconds_ago=age,
            error_type=error_type,
            error_message=error_message,
        )

    blocked = status in BLOCKING_STATUSES
    return ProviderHealth(
        provider=provider,
        status=status,
        model=model,
        observed_seconds_ago=age,
        error_type=error_type,
        error_message=error_message,
        blocked=blocked,
        retry_after_seconds=(max(0.0, cooldown - age) if blocked and cooldown is not None else None),
    )


class RedisProviderHealthRegistry:
    """Provider health shared across processes, backed by Redis.

    The API container and the Celery worker are separate processes with
    separate memory. Sprint 9G's `ProviderHealthRegistry` therefore gave
    each its own view of the world — correct for the process that
    observed a failure, blind for the other. This class fixes that by
    writing every observation to Redis (already-required infrastructure:
    the same broker `CELERY_BROKER_URL` points at) so both processes
    read the same state.

    ## Redis, synchronously, on purpose

    Every other Redis touch in this codebase (`app.modules.health`'s
    connectivity check) uses `redis.asyncio` inside an `async def`, which
    is the more idiomatic choice in a FastAPI app. This class uses the
    plain synchronous `redis` client instead, called directly from
    otherwise-synchronous methods (`record_success`, `status`, ...),
    because those methods are invoked from deep inside
    `LLMGateway._call_with_retries` — itself `async`, but calling them
    as ordinary (non-awaited) function calls, exactly as the Sprint 9G
    in-process registry always was. Converting the whole call chain to
    `async def` would touch every caller across the gateway, `/health`,
    and every test that constructs a registry — a large, mechanical
    change for a value this small.

    The trade this makes: each breaker check is a brief *blocking* call
    on the event loop, bounded by `LLM_HEALTH_REDIS_TIMEOUT` (200ms by
    default — deliberately tiny, so a dead Redis fails fast rather than
    stalling). That is a real cost, paid on every gateway attempt, and
    it is accepted rather than hidden: a synchronous round trip to a
    Redis instance on the same Docker network, typically ~1ms, is small
    next to the LLM call it sits beside (hundreds of milliseconds to
    several seconds), and bounding the failure mode with a short timeout
    keeps the worst case small too. Promoting this to a fully async
    client with a proper connection pool is the natural next step if
    the blocking cost is ever measured to matter; Phase 38's numbers in
    the sprint report are the baseline to compare against.

    ## Degradation, not a second outage

    Every Redis operation is wrapped in a `try/except`. On any failure —
    connection refused, timeout, a malformed cached value — the call
    logs a warning (never the connection URL or a credential) and falls
    through to an in-process `ProviderHealthRegistry` that this class
    keeps for exactly that purpose. Writes go to both unconditionally
    (Redis when reachable, local always), so the local fallback is warm
    the instant Redis becomes unavailable rather than starting empty.
    Reads prefer Redis and only consult local on a Redis error — an
    empty (but reachable) Redis is a legitimate "nothing observed yet",
    not a reason to fall back.
    """

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        local: "ProviderHealthRegistry | None" = None,
        client: Any = None,
    ) -> None:
        self._redis_url = redis_url or settings.celery_broker_url
        # A private local registry, not the process-wide singleton:
        # this is purely the degradation path for this instance, and
        # sharing it with anything else would blur exactly the
        # Redis-vs-local distinction this class exists to keep clean.
        self._local = local or ProviderHealthRegistry()
        # Injectable for tests (a fake or a `fakeredis` client); built
        # lazily from `redis_url` otherwise so import-time never
        # requires a live Redis connection.
        self._client = client
        self._warned_unavailable = False

    def _get_client(self) -> Any:
        if self._client is None:
            import redis as redis_sync

            self._client = redis_sync.Redis.from_url(
                self._redis_url,
                socket_connect_timeout=settings.llm_health_redis_timeout,
                socket_timeout=settings.llm_health_redis_timeout,
                decode_responses=True,
            )
        return self._client

    @staticmethod
    def _key(model: str) -> str:
        return f"{REDIS_KEY_PREFIX}{model}"

    def _log_degraded(self, operation: str, exc: Exception) -> None:
        # Logged at WARNING every time rather than deduplicated: Redis
        # being down is rare and operationally significant enough that
        # under-reporting it is the worse failure mode, and the volume
        # is naturally bounded by how often the gateway is actually
        # called. Never includes the connection URL (which can carry a
        # password) or any part of the cached value.
        logger.warning(
            "llm_provider_health_redis_degraded",
            operation=operation,
            error_type=type(exc).__name__,
        )

    # -- recording ---------------------------------------------------

    def record_success(self, model: str) -> None:
        """Note that a real call to `model` succeeded, everywhere."""
        self._local.record_success(model)
        self._write(model, status=ProviderStatus.HEALTHY, error_type=None, error_message=None)

    def record_failure(self, model: str, *, error: BaseException) -> ProviderStatus:
        """Note that a real call to `model` failed, and how, everywhere."""
        status = self._local.record_failure(model, error=error)
        message = str(error) if isinstance(error, LLMError) else None
        self._write(
            model,
            status=status,
            error_type=type(error).__name__,
            error_message=message[:500] if message else None,
        )
        return status

    def _write(
        self,
        model: str,
        *,
        status: ProviderStatus,
        error_type: str | None,
        error_message: str | None,
    ) -> None:
        """Persist one observation to Redis. Never raises.

        Stores only operational state — status, provider, model, a wall
        clock, and an already-scrubbed error summary. Never a prompt,
        an answer, a citation, or a credential: `error_message` is
        sourced from `LLMError`, whose constructor already ran
        `scrub_secrets`, the same guarantee every log line in this
        package relies on.
        """
        payload = {
            "status": status.value,
            "provider": _provider_of(model),
            "model": model,
            "updated_at": time.time(),
            "error_type": error_type,
            "error_message": error_message,
        }
        cooldown = _cooldown_for(status)
        ttl_seconds = (
            int(cooldown) + 1 if cooldown is not None else int(settings.llm_health_state_ttl_seconds)
        )
        try:
            self._get_client().setex(self._key(model), ttl_seconds, json.dumps(payload))
        except Exception as exc:  # noqa: BLE001 - Redis must never break a gateway call
            self._log_degraded("write", exc)

    # -- reading -----------------------------------------------------

    def status(self, model: str) -> ProviderHealth:
        """Report `model`'s current state, reading Redis first.

        Never raises and never calls a provider: this is the function
        `/health` depends on, and it must be free and safe to poll.
        """
        provider = _provider_of(model)
        baseline = _baseline_status(provider)

        try:
            raw = self._get_client().get(self._key(model))
        except Exception as exc:  # noqa: BLE001
            self._log_degraded("read", exc)
            return self._local.status(model)

        if raw is None:
            # Reachable Redis, no entry: a genuine "never observed or
            # cooldown already expired", not a reason to fall back.
            return ProviderHealth(provider=provider, status=baseline, model=model)

        try:
            data = json.loads(raw)
            status = ProviderStatus(data["status"])
        except (TypeError, ValueError, KeyError) as exc:
            # A value this module didn't write (or wrote in a since
            # -changed shape) must never crash the caller — treat it
            # as absent rather than raising.
            self._log_degraded("parse", exc)
            return ProviderHealth(provider=provider, status=baseline, model=model)

        age = max(0.0, time.time() - float(data.get("updated_at", time.time())))
        return _resolve_health(
            provider=provider,
            model=model,
            status=status,
            age=age,
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
            baseline=baseline,
        )

    def is_blocked(self, model: str) -> bool:
        """Whether the gateway should skip `model` for now."""
        return self.status(model).blocked

    def snapshot(self, models: list[str]) -> dict[str, ProviderHealth]:
        """State for several models at once, for the health endpoint."""
        return {model: self.status(model) for model in models}

    def reset(self) -> None:
        """Forget everything, in Redis and locally. For tests.

        Without this, one test's recorded failure would leak into the
        next through the shared Redis instance and make the suite
        order-dependent — the same reason the in-process registry has
        a `reset()`, just needing to reach further.
        """
        self._local.reset()
        try:
            client = self._get_client()
            keys = list(client.scan_iter(match=f"{REDIS_KEY_PREFIX}*"))
            if keys:
                client.delete(*keys)
        except Exception as exc:  # noqa: BLE001
            self._log_degraded("reset", exc)


def _cooldown_for(status: ProviderStatus) -> float | None:
    """How long a status blocks (or lingers) before it decays.

    Read from settings on every call rather than captured at import, so
    the values are configurable and so tests can shorten them without
    rebuilding the registry.
    """
    if status is ProviderStatus.QUOTA_EXHAUSTED:
        return settings.llm_quota_cooldown_seconds
    if status is ProviderStatus.RATE_LIMITED:
        return settings.llm_rate_limit_cooldown_seconds
    if status is ProviderStatus.UNAVAILABLE:
        return settings.llm_unavailable_cooldown_seconds
    if status is ProviderStatus.CONFIGURATION_ERROR:
        return settings.llm_configuration_error_cooldown_seconds
    # `HEALTHY` never expires into something worse on its own. A
    # provider that stops working will say so on the next real call,
    # and inventing a "probably stale by now" state would be a guess
    # dressed up as a measurement.
    return None


def is_provider_configured(provider: str) -> bool:
    """Whether `provider` has whatever credentials it needs to be tried.

    The one place provider names map onto credential settings, so the
    gateway's fallback filter and the health endpoint cannot drift
    apart. Providers needing no key (locally hosted models) are always
    configured; anything unrecognised is assumed configured and left to
    LiteLLM's own environment conventions, which is the same
    assumption the gateway's credential lookup makes.
    """
    if provider == "gemini":
        return settings.has_gemini_credentials
    if provider == "groq":
        return settings.has_groq_credentials
    if provider == "deepseek":
        return settings.has_deepseek_credentials
    if provider == "openrouter":
        return settings.has_openrouter_credentials
    return True


_registry: "ProviderHealthRegistry | RedisProviderHealthRegistry | None" = None


def get_provider_health_registry() -> "ProviderHealthRegistry | RedisProviderHealthRegistry":
    """Return the shared registry for this process (Sprint 9H: Redis-backed).

    A singleton for the same reason `get_llm_gateway()` is one: the
    state has to be shared between request handlers, Celery tasks, and
    the health endpoint, all of which live in the same process — and,
    since this sprint, across processes too, because the value is
    `RedisProviderHealthRegistry` rather than the plain in-process
    class. Tests that want true isolation construct `ProviderHealthRegistry()`
    directly instead of going through this function.
    """
    global _registry
    if _registry is None:
        _registry = RedisProviderHealthRegistry()
    return _registry
