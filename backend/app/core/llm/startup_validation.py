"""Startup diagnostics for the configured provider chain (Sprint 9H).

Answers, once, at process start: for each configured model — primary,
fallback, secondary fallback — is there a key, is a model named, and
does that provider's own catalogue still list it?

That last question is the one worth automating. Sprint 9G's fallback
model, `groq/llama-3.3-70b-versatile`, was live-verified working and
then removed from Groq's catalogue hours later — discovered only when
a live research run failed with `LLMModelNotFoundError`. A model-list
call at startup would have caught it before the first user did.

## Metadata only, never generation

Every check here is a `GET` against a provider's own model-listing
endpoint — `/v1/models`, or equivalent — never a completion request.
That is a deliberate, direct parallel to
`app.modules.knowledge_base.reranking.check_reranker_health`, which
probes llama-server's liveness route rather than sending it a real
rerank request: the question is "does this exist and answer", not "is
the output good", and the first question has a free way to ask it.

This is also why these checks live outside `LLMGateway`/LiteLLM. LiteLLM
provides `acompletion`/`aembedding` for generation and embedding; it has
no generic "list this provider's models" call, and there is nothing to
route through the gateway abstraction for a request that never produces
a completion. Talking to each provider's own listing endpoint directly
is the sanctioned mechanism the sprint asked for ("Use provider
model-list endpoints where appropriate"), not a bypass of it — nothing
here is reachable from a synthesis node, a router, or any code path that
touches retrieved evidence or produces an answer. `litellm` is still
imported nowhere but `gateway.py`; this module doesn't import it at all.

## Never fatal

A provider that fails validation — no key, unreachable, model missing —
is logged and left for `/health` and this module's own summary to
surface. Startup never raises for it. The one case that already fails
loudly is unrelated to this module: a missing *primary* credential
still surfaces as `LLMConfigurationError` the moment something actually
calls the gateway, exactly as it did before Sprint 9H. This module adds
visibility; it does not add a new way for the application to refuse to
start.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum

import httpx

from app.core.config import settings
from app.core.llm.gateway import provider_of
from app.core.llm.health import configured_chain
from app.core.llm.provider_health import is_provider_configured
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

#: Bounded and short: this runs during startup, and an unreachable
#: provider must not measurably delay the application coming up.
VALIDATION_TIMEOUT_SECONDS = 5.0


class ModelValidationStatus(str, Enum):
    """What startup validation found for one configured model."""

    #: The provider's own catalogue lists this model.
    AVAILABLE = "available"
    #: No API key configured. Expected for an unused optional fallback.
    NOT_CONFIGURED = "not_configured"
    #: A key is configured, but the provider rejected it (401/403).
    INVALID_CREDENTIALS = "invalid_credentials"
    #: The provider answered, but this model is not in its list —
    #: exactly the Groq incident this module exists to catch early.
    MODEL_NOT_FOUND = "model_not_found"
    #: The provider could not be reached at all within the timeout.
    UNREACHABLE = "unreachable"
    #: This provider has no known model-list endpoint wired up here.
    #: Not a failure — Ollama and any future local provider land here.
    UNKNOWN_PROVIDER = "unknown_provider"


@dataclass(frozen=True)
class ModelValidationResult:
    """The outcome for one `(role, model)` pair. Contains no credentials."""

    role: str
    model: str
    provider: str
    status: ModelValidationStatus
    detail: str | None = None

    @property
    def ok(self) -> bool:
        """Whether this entry is currently routable.

        `UNKNOWN_PROVIDER` counts as fine — it means "not checkable",
        not "broken"; a locally-hosted provider with no listing
        endpoint is not a problem. Everything else that isn't
        `AVAILABLE`, `NOT_CONFIGURED` included, is not: there is
        either no key to route with, a rejected credential, an
        unreachable host, or a model the provider no longer serves.

        This is a routability check, not a severity check — it does
        not by itself say whether the *platform* is in trouble.
        `NOT_CONFIGURED` on an optional fallback is completely normal
        and never fails startup (see `run_startup_validation`); the
        same status on the *primary* would be worth an operator's
        attention. That distinction lives in how a caller reads
        `.role` and `.status` together, not in this one flag.
        """
        return self.status in (
            ModelValidationStatus.AVAILABLE,
            ModelValidationStatus.UNKNOWN_PROVIDER,
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "role": self.role,
            "model": self.model,
            "provider": self.provider,
            "status": self.status.value,
            "detail": self.detail,
        }


async def validate_configured_models(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> list[ModelValidationResult]:
    """Check every configured chain entry against its provider's catalogue.

    Runs all checks concurrently — three independent metadata GETs, not
    three sequential ones — and never raises: a provider that cannot be
    validated is a result (`UNREACHABLE`, `INVALID_CREDENTIALS`, ...),
    not an exception that could take startup down with it.

    `transport` is injected only by tests, so the real request building
    and response handling below run against a `MockTransport` instead
    of being stubbed out wholesale — the same pattern
    `HttpRerankerProvider` and `check_reranker_health` already use.
    """
    chain = configured_chain()
    async with httpx.AsyncClient(
        timeout=VALIDATION_TIMEOUT_SECONDS, transport=transport
    ) as client:
        results = await asyncio.gather(
            *(_validate_one(client, role=role, model=model) for role, model in chain)
        )
    return list(results)


async def _validate_one(
    client: httpx.AsyncClient, *, role: str, model: str
) -> ModelValidationResult:
    provider = provider_of(model)
    if not is_provider_configured(provider):
        return ModelValidationResult(
            role=role,
            model=model,
            provider=provider,
            status=ModelValidationStatus.NOT_CONFIGURED,
            detail=f"No API key is configured for {provider}.",
        )

    checker = _CHECKERS.get(provider)
    if checker is None:
        return ModelValidationResult(
            role=role,
            model=model,
            provider=provider,
            status=ModelValidationStatus.UNKNOWN_PROVIDER,
            detail=f"No model-list endpoint is wired up for {provider}.",
        )

    try:
        return await checker(client, role=role, model=model, provider=provider)
    except httpx.TimeoutException:
        return ModelValidationResult(
            role=role,
            model=model,
            provider=provider,
            status=ModelValidationStatus.UNREACHABLE,
            detail=f"{provider} did not respond within {VALIDATION_TIMEOUT_SECONDS}s.",
        )
    except httpx.HTTPError as exc:
        return ModelValidationResult(
            role=role,
            model=model,
            provider=provider,
            status=ModelValidationStatus.UNREACHABLE,
            detail=f"Could not reach {provider}: {type(exc).__name__}.",
        )


def _strip_provider_prefix(model: str, provider: str) -> str:
    """`openrouter/nvidia/nemotron-3-super-120b-a12b:free` -> the vendor id.

    LiteLLM's `provider/model` notation adds one segment that the
    provider's own catalogue does not know about; this removes exactly
    that segment (and no more — OpenRouter's own ids are themselves
    slash-separated, e.g. `nvidia/nemotron-...`).
    """
    prefix = f"{provider}/"
    return model[len(prefix) :] if model.startswith(prefix) else model


async def _check_gemini(
    client: httpx.AsyncClient, *, role: str, model: str, provider: str
) -> ModelValidationResult:
    """`GET generativelanguage.googleapis.com/v1beta/models`.

    The key travels as `x-goog-api-key`, a header, never a query
    string — so it cannot end up in a proxy access log or a browser
    history the way `?key=...` could.
    """
    response = await client.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": settings.gemini_api_key.get_secret_value()},  # type: ignore[union-attr]
    )
    if response.status_code in (401, 403):
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.INVALID_CREDENTIALS,
            detail="Gemini rejected the configured API key.",
        )
    if response.status_code != 200:
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.UNREACHABLE,
            detail=f"Gemini's model list returned HTTP {response.status_code}.",
        )

    vendor_id = _strip_provider_prefix(model, provider)
    names = {
        entry.get("name", "").removeprefix("models/")
        for entry in response.json().get("models", [])
    }
    if vendor_id not in names:
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.MODEL_NOT_FOUND,
            detail=f"'{vendor_id}' is not in Gemini's current model list.",
        )
    return ModelValidationResult(
        role=role, model=model, provider=provider, status=ModelValidationStatus.AVAILABLE
    )


async def _check_groq(
    client: httpx.AsyncClient, *, role: str, model: str, provider: str
) -> ModelValidationResult:
    """`GET api.groq.com/openai/v1/models`.

    The exact call that would have caught Sprint 9G's incident: Groq
    silently dropped `llama-3.3-70b-versatile` from this list between
    one live verification and the next research run hours later.
    """
    response = await client.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"},  # type: ignore[union-attr]
    )
    if response.status_code in (401, 403):
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.INVALID_CREDENTIALS,
            detail="Groq rejected the configured API key.",
        )
    if response.status_code != 200:
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.UNREACHABLE,
            detail=f"Groq's model list returned HTTP {response.status_code}.",
        )

    vendor_id = _strip_provider_prefix(model, provider)
    ids = {entry.get("id") for entry in response.json().get("data", [])}
    if vendor_id not in ids:
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.MODEL_NOT_FOUND,
            detail=f"'{vendor_id}' is not in Groq's current model list.",
        )
    return ModelValidationResult(
        role=role, model=model, provider=provider, status=ModelValidationStatus.AVAILABLE
    )


async def _check_openrouter(
    client: httpx.AsyncClient, *, role: str, model: str, provider: str
) -> ModelValidationResult:
    """`GET openrouter.ai/api/v1/models`.

    OpenRouter's catalogue changes at least as often as Groq's — several
    of the free-tier models tried during Sprint 9H's model selection
    (`openai/gpt-oss-20b:free`, `z-ai/glm-5.2:free`) either returned
    empty completions or 429s on the same day they were listed. This
    check only confirms the model is *listed*, which is a weaker
    guarantee than "will serve a request right now" — Sprint 9H's own
    model selection needed a real generation to establish that, and
    startup deliberately does not repeat that cost on every boot.
    """
    response = await client.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}"},  # type: ignore[union-attr]
    )
    if response.status_code in (401, 403):
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.INVALID_CREDENTIALS,
            detail="OpenRouter rejected the configured API key.",
        )
    if response.status_code != 200:
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.UNREACHABLE,
            detail=f"OpenRouter's model list returned HTTP {response.status_code}.",
        )

    vendor_id = _strip_provider_prefix(model, provider)
    ids = {entry.get("id") for entry in response.json().get("data", [])}
    if vendor_id not in ids:
        return ModelValidationResult(
            role=role, model=model, provider=provider,
            status=ModelValidationStatus.MODEL_NOT_FOUND,
            detail=f"'{vendor_id}' is not in OpenRouter's current model list.",
        )
    return ModelValidationResult(
        role=role, model=model, provider=provider, status=ModelValidationStatus.AVAILABLE
    )


#: Provider -> its model-list checker. Ollama (and any future
#: locally-hosted provider) is deliberately absent: it needs no key,
#: `is_provider_configured` always reports it configured, and this
#: dict's absence is exactly what routes it to `UNKNOWN_PROVIDER` —
#: "not checkable", not "broken".
_CHECKERS = {
    "gemini": _check_gemini,
    "groq": _check_groq,
    "openrouter": _check_openrouter,
}


async def run_startup_validation() -> None:
    """Validate the configured chain and log one summary line per entry.

    Called from the FastAPI lifespan, fire-and-forget: it logs, it
    never raises, and it never blocks application readiness beyond its
    own bounded timeout. A problem it finds is visible in these logs
    immediately and in `/health` for as long as it persists — this
    function does not gate startup on either.
    """
    try:
        results = await validate_configured_models()
    except Exception as exc:  # noqa: BLE001 - startup must never crash on this
        logger.error("llm_startup_validation_failed", error_type=type(exc).__name__)
        return

    for result in results:
        log = logger.info if result.ok else logger.warning
        log(
            "llm_startup_validation",
            role=result.role,
            model=result.model,
            provider=result.provider,
            status=result.status.value,
            detail=result.detail,
        )

    problems = [result for result in results if not result.ok]
    logger.info(
        "llm_startup_validation_summary",
        checked=len(results),
        problems=len(problems),
        problem_roles=[result.role for result in problems],
    )
