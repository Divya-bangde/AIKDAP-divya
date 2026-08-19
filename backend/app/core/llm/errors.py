"""The LLM error taxonomy, and the secret scrubbing every error passes through.

Split out of `gateway.py` in Sprint 9G. The gateway now has to *route*
on error kind — retry this, never retry that, fall back on the other —
so the taxonomy stopped being incidental detail and became the thing
the resilience policy is written against. It lives here so the policy
can be read in one screen, and so `provider_health.py` can classify an
error without importing the gateway (and therefore without importing
LiteLLM, which is contained to `gateway.py` alone and asserted to be).

Nothing in this module imports `litellm`. Mapping a LiteLLM exception
onto one of these classes stays in the gateway, next to the call that
produced it.

## Why the taxonomy is shaped this way

Sprint 9F ended blocked on a real failure: Gemini's free tier allows 20
`generateContent` requests per project per model per day, and once that
is spent every further request returns HTTP 429 — the same status code
as a temporary per-minute rate limit. Retrying a per-minute limit is
correct and usually works within seconds. Retrying a per-day limit
burns time and gets the identical error until midnight Pacific.

Worse, Google's own response actively misleads a naive retry loop. The
live error captured on 2026-08-16 carried::

    "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    "quotaValue": "20"
    "retryDelay": "35s"

A 35-second retry hint attached to a 24-hour quota. Honouring it would
mean an infinite, polite, useless retry loop. So the gateway does not
honour provider-supplied retry hints, and this module draws the line
that matters: `LLMQuotaExhaustedError` and `LLMRateLimitError` are
different failures even though they arrive as the same status code.

## The three policy groups

Every error below belongs to exactly one:

`TERMINAL_ERRORS`
    Our request or our configuration is wrong. A different provider
    would reject it the same way, so there is nothing to retry and
    nothing to fall back to. Fail immediately and say why.

`RETRYABLE_ERRORS`
    Transient and provider-side. Worth a bounded, jittered retry on the
    same model; if the retries are exhausted the chain moves on to the
    fallback.

Everything else — quota exhaustion, an unknown model, an unrecognised
provider failure — is *fallback-eligible but not retryable*: repeating
the call cannot help, but a different provider genuinely might.
"""

import re

#: Substrings that look like credentials in provider error text. Any
#: match is redacted before the text is logged or attached to an
#: exception.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # `key=...`, `api_key: ...`, `Authorization: Bearer ...`
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)(\S+)"),
    re.compile(r"(?i)(authorization\s*[=:]\s*)(\S+)"),
    re.compile(r"(?i)(bearer\s+)(\S+)"),
    # Google API keys have a stable, recognisable prefix.
    re.compile(r"AIza[0-9A-Za-z\-_]{10,}"),
    # Groq and DeepSeek issue OpenAI-style prefixed keys (Sprint 9G).
    # Added when those providers were actually routed, so a fallback
    # provider echoing its own credential back is scrubbed too.
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    # OpenRouter keys (Sprint 9H) are `sk-or-v1-<hex>`. Checked before
    # the bare `sk-...` pattern below only in the sense that regex
    # alternation order doesn't matter here — both match the same
    # text — but the OpenRouter-specific pattern is kept distinct so
    # it can't be removed later under the mistaken belief that the
    # generic one already covers it.
    re.compile(r"sk-or-v1-[0-9a-fA-F]{20,}"),
    re.compile(r"sk-[0-9A-Za-z]{20,}"),
)

_REDACTED = "***redacted***"


def scrub_secrets(text: str) -> str:
    """Remove anything credential-shaped from provider-supplied text.

    Applied to every provider error before it is logged or wrapped in
    an `LLMError`. Belt-and-braces: the gateway does not put the key in
    messages itself, but the text here originates in third-party code.
    """
    scrubbed = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            scrubbed = pattern.sub(rf"\g<1>{_REDACTED}", scrubbed)
        else:
            scrubbed = pattern.sub(_REDACTED, scrubbed)
    return scrubbed


class LLMError(Exception):
    """Base class for every gateway failure.

    Carries only non-sensitive context: the model, and a scrubbed
    message. Never the API key.
    """

    def __init__(self, message: str, *, model: str | None = None) -> None:
        super().__init__(scrub_secrets(message))
        self.model = model


class LLMConfigurationError(LLMError):
    """Raised when the gateway is not usably configured.

    A missing API key is a deployment problem, not a provider problem —
    it fails immediately rather than after a pointless network round
    trip.
    """


class LLMAuthenticationError(LLMError):
    """Raised when the provider rejects the credentials (401/403)."""


class LLMInvalidRequestError(LLMError):
    """Raised when the provider rejects the request itself (400).

    Sprint 9G. Distinct from `LLMAuthenticationError` because the
    remedy is different — a malformed request, an oversized prompt, or
    an unsupported parameter is our bug, not a credential problem — and
    distinct from `LLMProviderError` because it must never be retried:
    the same request will be rejected every time.
    """


class LLMTimeoutError(LLMError):
    """Raised when the provider does not respond within `llm_timeout`."""


class LLMProviderError(LLMError):
    """A provider-side failure that is none of the more specific kinds.

    The catch-all. Not retried — an unclassified failure gives no
    reason to believe a repeat would differ — but it *is* eligible for
    the fallback chain, because a different provider plausibly works
    when this one is behaving in a way we do not recognise.
    """


class LLMRateLimitError(LLMProviderError):
    """Raised for a transient rate limit: requests/tokens per minute.

    Sprint 9G. Retryable: the window that is full will drain, usually
    within seconds. Kept as a subclass of `LLMProviderError` so callers
    written before this distinction existed still catch it.
    """


class LLMQuotaExhaustedError(LLMProviderError):
    """Raised when a hard, long-window quota is spent — typically daily.

    Sprint 9G, and the reason this sprint exists. Arrives as HTTP 429,
    exactly like `LLMRateLimitError`, and is told apart by the quota
    metadata in the provider's body (see `gateway._classify_rate_limit`).

    Never retried. The quota does not recover on any timescale a retry
    loop can wait out, so the only useful response is to mark the
    provider unavailable and route to a fallback immediately.
    """


class LLMServiceUnavailableError(LLMProviderError):
    """Raised when the provider is temporarily down or overloaded (503).

    Sprint 9G. Retryable, and the textbook case for backoff: the
    provider is telling us to come back shortly.
    """


class LLMConnectionError(LLMError):
    """Raised when the provider endpoint cannot be reached at all.

    Distinct from `LLMTimeoutError` (endpoint reached, no answer in
    time) and `LLMModelNotFoundError` (endpoint reached, model not
    recognized) — e.g. Ollama not running, or a wrong base URL.
    """


class LLMModelNotFoundError(LLMError):
    """Raised when the provider is reachable but does not recognize the
    requested model — e.g. an Ollama model that has not been pulled.

    Kept distinct so a caller can report "model X is not installed"
    rather than a generic failure, and so nothing silently substitutes
    a different model to work around it.

    Not retryable (the model will not appear between attempts) but
    fallback-eligible: a *different* configured model is exactly the
    right answer to one that does not exist.
    """


#: Failures that repeating cannot fix and that a different provider
#: cannot fix either. The chain stops here and the caller is told why.
TERMINAL_ERRORS: tuple[type[LLMError], ...] = (
    LLMConfigurationError,
    LLMAuthenticationError,
    LLMInvalidRequestError,
)

#: Failures worth a bounded, jittered retry against the same model
#: before the chain moves on. Deliberately excludes
#: `LLMQuotaExhaustedError`, which is the whole point of the taxonomy.
RETRYABLE_ERRORS: tuple[type[LLMError], ...] = (
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    LLMConnectionError,
)


def is_terminal(error: BaseException) -> bool:
    """Whether `error` ends the whole call, fallbacks included."""
    return isinstance(error, TERMINAL_ERRORS)


def is_retryable(error: BaseException) -> bool:
    """Whether `error` justifies another attempt at the same model.

    Checked against `TERMINAL_ERRORS` first so a subclass can never be
    both: correctness here is what keeps a quota error out of the retry
    loop.
    """
    if is_terminal(error):
        return False
    return isinstance(error, RETRYABLE_ERRORS)
