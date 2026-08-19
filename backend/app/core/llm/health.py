"""LLM health, in two flavours: free and expensive.

`describe_providers()` is the free one, and the one `GET /health`
uses. It reports what the gateway has already learned from real
traffic — see `provider_health.py` — plus whether each provider is
credentialed at all. It sends nothing, so opening the health page
costs no inference and no quota. That is a hard Sprint 9G requirement
(Phase 12), and it is why the endpoint reports `configured` rather than
`healthy` for a provider nobody has called yet: a key on disk is not
evidence that anything works.

`check_llm_health()` is the expensive one: an actual generation against
an actual model. Reserved for operators and tests deciding to spend a
request on certainty. It is never wired into an HTTP route.

Both return only safe metadata. No API key, no prompt content, and no
provider payload appears in either result.
"""

import time
from dataclasses import asdict, dataclass

from app.core.config import settings
from app.core.llm.gateway import (
    LLMConfigurationError,
    LLMError,
    LLMGateway,
    get_llm_gateway,
    provider_of,
)
from app.core.llm.provider_health import (
    ProviderHealth,
    ProviderStatus,
    get_provider_health_registry,
    is_provider_configured,
)
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

#: Cheap, deterministic prompt. Short enough that a health check costs
#: almost nothing, and specific enough that a wrong or truncated
#: response is obvious.
HEALTH_CHECK_PROMPT = "Reply with the single word: OK"

HEALTH_CHECK_SYSTEM_PROMPT = (
    "You are a connectivity probe. Reply with exactly one word and nothing else."
)


@dataclass(frozen=True)
class LLMHealth:
    """Outcome of one reachability probe. Contains no secrets."""

    provider: str
    model: str
    success: bool
    latency_ms: int
    error_type: str | None = None
    error_message: str | None = None
    #: A short excerpt of the reply, so an operator can tell a real
    #: model response from an empty or malformed one.
    sample: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Render as a plain dict for logging or serialization."""
        return asdict(self)


async def check_llm_health(
    *, model: str | None = None, gateway: LLMGateway | None = None
) -> LLMHealth:
    """Probe the configured model and report the outcome.

    Never raises: an unreachable or misconfigured model is a result to
    report, not an exception to propagate — the caller is asking
    whether it works, and an exception would be a worse answer than
    `success=False`.
    """
    client = gateway or get_llm_gateway()
    target = model or client.default_model
    provider = provider_of(target)

    # Fail fast and clearly when no key is configured, rather than
    # spending a network round trip to be told the same thing.
    if provider == "gemini" and not settings.has_gemini_credentials:
        logger.warning(
            "llm_health_check_unconfigured",
            provider=provider,
            model=target,
            reason="GEMINI_API_KEY is not set",
        )
        return LLMHealth(
            provider=provider,
            model=target,
            success=False,
            latency_ms=0,
            error_type=LLMConfigurationError.__name__,
            error_message="GEMINI_API_KEY is not configured.",
        )

    start = time.monotonic()
    try:
        response = await client.generate(
            prompt=HEALTH_CHECK_PROMPT,
            system_prompt=HEALTH_CHECK_SYSTEM_PROMPT,
            model=target,
            # A probe measures the model it was asked about. Falling
            # back would report a different provider's health under
            # this one's name; retrying would inflate the latency it
            # exists to measure; and honouring the breaker would make
            # an explicit "check this now" silently return nothing.
            allow_fallback=False,
            max_retries=0,
            respect_provider_health=False,
            # Not the same tiny cap the health check name implies: some
            # models (confirmed live against gemini-flash-latest, a
            # Gemini 3.x thinking-enabled alias) spend part of
            # `max_tokens` on an internal reasoning budget before any
            # visible text — observed consuming 61 tokens of reasoning
            # for a one-word reply, `finish_reason=length`,
            # `completion_tokens_details.text_tokens=0`. 150 leaves
            # enough headroom after that budget for the reply itself;
            # a cap as small as 64 reproduces the failure. A real,
            # reachable model was otherwise misreported as down.
            max_tokens=150,
            temperature=0.0,
        )
    except LLMError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.error(
            "llm_health_check_failed",
            provider=provider,
            model=target,
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return LLMHealth(
            provider=provider,
            model=target,
            success=False,
            latency_ms=latency_ms,
            error_type=type(exc).__name__,
            # Already scrubbed by `LLMError`.
            error_message=str(exc),
        )

    logger.info(
        "llm_health_check_succeeded",
        provider=response.provider,
        model=response.model,
        latency_ms=response.latency_ms,
        total_tokens=response.total_tokens,
    )
    return LLMHealth(
        provider=response.provider,
        model=response.model,
        success=True,
        latency_ms=response.latency_ms,
        sample=response.content.strip()[:120],
    )


# ---------------------------------------------------------------------------
# The free view: what the gateway already knows (Sprint 9G)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderRole:
    """One configured model and the job it does in the fallback chain."""

    #: "primary", "fallback", or "secondary_fallback".
    role: str
    model: str
    provider: str
    health: ProviderHealth

    def as_dict(self) -> dict[str, object]:
        """Flatten for the health response. Contains no credentials."""
        return {"role": self.role, "model": self.model, **self.health.as_dict()}


def configured_chain() -> list[tuple[str, str]]:
    """The `(role, model)` pairs this deployment would try, in order.

    Reads the same settings the gateway builds its chain from, so the
    health endpoint cannot describe a chain the gateway would not
    actually walk. Unset fallbacks are simply absent.
    """
    chain = [("primary", settings.default_llm)]
    for role, configured in (
        ("fallback", settings.fallback_llm),
        ("secondary_fallback", settings.secondary_fallback_llm),
    ):
        model = (configured or "").strip()
        if model:
            chain.append((role, model))
    return chain


def describe_providers() -> list[ProviderRole]:
    """Report every configured provider's state without calling any.

    Purely a read of the in-process registry plus the credential
    settings. No network, no inference, no quota — which is what makes
    it safe to put behind an endpoint anyone can poll.

    A provider with no credentials is reported `not_configured` rather
    than omitted: "the fallback you think you have is not actually set
    up" is exactly the kind of thing an operator needs to see before an
    outage, not during one.
    """
    registry = get_provider_health_registry()
    roles: list[ProviderRole] = []
    for role, model in configured_chain():
        provider = provider_of(model)
        health = registry.status(model)
        if not is_provider_configured(provider):
            health = ProviderHealth(
                provider=provider, status=ProviderStatus.NOT_CONFIGURED, model=model
            )
        roles.append(
            ProviderRole(role=role, model=model, provider=provider, health=health)
        )
    return roles


def has_usable_provider() -> bool:
    """Whether any configured provider could serve a request right now.

    "Could" is doing real work here: a provider counts as usable when
    it is credentialed and not currently blocked by the breaker. It
    does not have to be proven `healthy`, because an untried provider
    is a perfectly reasonable thing to attempt — refusing to call it
    until it proves itself would need a probe, and the probe is exactly
    the cost this design avoids.
    """
    return any(
        role.health.status
        not in (ProviderStatus.NOT_CONFIGURED, ProviderStatus.CONFIGURATION_ERROR)
        and not role.health.blocked
        for role in describe_providers()
    )
