"""Centralized LLM gateway.

Every model call in AIKDAP goes through `LLMGateway`. Nothing outside
this package imports `litellm` directly — a test asserts it — so the
routing library stays a replaceable implementation detail rather than a
dependency spread across the agents, the research module, and the
workers.

Since Sprint 9G the gateway also owns provider *resilience*: error
classification, bounded retry, the fallback chain, and a small circuit
breaker. That belongs here for the same reason the LiteLLM import does.
Retries added independently in a node, a service and a router would
multiply rather than compose, and three layers of "just three attempts"
is twenty-seven calls to a provider that already said no.

Public surface:

- `LLMGateway` / `get_llm_gateway()` — the client.
- `LLMMessage`, `LLMResponse` — the application-level request/response
  types, deliberately free of any provider or LiteLLM structure.
- `LLMError` and its subclasses — every failure mode, normalized. The
  distinction between `LLMQuotaExhaustedError` (never retry) and
  `LLMRateLimitError` (retry with backoff) is the one that matters.
- `describe_providers()` — what the gateway knows about each provider,
  free of charge; this is what `GET /health` reports.
- `check_llm_health()` — a real reachability probe, which costs a real
  request. Not wired into any route.
"""

from app.core.llm.errors import (
    RETRYABLE_ERRORS,
    TERMINAL_ERRORS,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    is_retryable,
    is_terminal,
    scrub_secrets,
)
from app.core.llm.gateway import (
    LLMAttempt,
    LLMEmbeddingResponse,
    LLMGateway,
    LLMMessage,
    LLMResponse,
    get_llm_gateway,
    provider_of,
)
from app.core.llm.health import (
    LLMHealth,
    ProviderRole,
    check_llm_health,
    configured_chain,
    describe_providers,
    has_usable_provider,
)
from app.core.llm.provider_health import (
    REDIS_KEY_PREFIX,
    ProviderHealth,
    ProviderHealthRegistry,
    ProviderStatus,
    RedisProviderHealthRegistry,
    get_provider_health_registry,
    is_provider_configured,
)

__all__ = [
    "REDIS_KEY_PREFIX",
    "RETRYABLE_ERRORS",
    "TERMINAL_ERRORS",
    "LLMAttempt",
    "LLMAuthenticationError",
    "LLMConfigurationError",
    "LLMConnectionError",
    "LLMEmbeddingResponse",
    "LLMError",
    "LLMGateway",
    "LLMHealth",
    "LLMInvalidRequestError",
    "LLMMessage",
    "LLMModelNotFoundError",
    "LLMProviderError",
    "LLMQuotaExhaustedError",
    "LLMRateLimitError",
    "LLMResponse",
    "LLMServiceUnavailableError",
    "LLMTimeoutError",
    "ProviderHealth",
    "ProviderHealthRegistry",
    "ProviderRole",
    "ProviderStatus",
    "RedisProviderHealthRegistry",
    "check_llm_health",
    "configured_chain",
    "describe_providers",
    "get_llm_gateway",
    "get_provider_health_registry",
    "has_usable_provider",
    "is_provider_configured",
    "is_retryable",
    "is_terminal",
    "provider_of",
    "scrub_secrets",
]
