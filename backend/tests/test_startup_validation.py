"""Sprint 9H Phase 15/26: startup validation of the configured chain.

Offline throughout via `httpx.MockTransport` — no real request reaches
Gemini, Groq, or OpenRouter. The live counterpart (does this deployment's
*actual* configuration validate against the *real* providers right now)
is a separate, one-time check reported with its real numbers, not
something a repeatable test suite should depend on.

The scenario these tests exist to catch is real: Sprint 9G's fallback
model (`groq/llama-3.3-70b-versatile`) was live-verified working and
then silently removed from Groq's catalogue hours later. A model-list
call at startup is the mechanism that would have caught it before a
user did.
"""

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.llm.startup_validation import (
    ModelValidationStatus,
    run_startup_validation,
    validate_configured_models,
)

GEMINI = "gemini/gemini-flash-latest"
GROQ = "groq/openai/gpt-oss-120b"
OPENROUTER = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"

FAKE_GEMINI_KEY = "AIzaSyTESTKEY_MUST_NEVER_BE_LOGGED_0123456789"
FAKE_GROQ_KEY = "gsk_TESTKEYMUSTNEVERBELOGGED0123456789"
FAKE_OPENROUTER_KEY = "sk-or-v1-testkeymustneverbelogged0123456789"


@pytest.fixture
def chain(monkeypatch):
    """Primary + both fallbacks configured, matching the real deployment."""
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr(FAKE_GEMINI_KEY))
    monkeypatch.setattr(settings, "groq_api_key", SecretStr(FAKE_GROQ_KEY))
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(FAKE_OPENROUTER_KEY))
    monkeypatch.setattr(settings, "default_llm", GEMINI)
    monkeypatch.setattr(settings, "fallback_llm", GROQ)
    monkeypatch.setattr(settings, "secondary_fallback_llm", OPENROUTER)


def router(handlers: dict[str, httpx.Response]):
    """Route a mock transport by hostname, mirroring three real APIs
    behind one `httpx.AsyncClient`."""

    def handle(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        for key, response in handlers.items():
            if key in host:
                return response
        raise AssertionError(f"unexpected request to {host}")

    return httpx.MockTransport(handle)


def gemini_models_response(*ids: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": f"models/{i}"} for i in ids]})


def openai_style_models_response(*ids: str) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": i} for i in ids]})


# ---------------------------------------------------------------------------
# Per-provider outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_three_available_when_every_model_is_listed(chain):
    transport = router({
        "generativelanguage": gemini_models_response("gemini-flash-latest", "gemini-pro-latest"),
        "groq.com": openai_style_models_response("openai/gpt-oss-120b"),
        "openrouter.ai": openai_style_models_response("nvidia/nemotron-3-super-120b-a12b:free"),
    })

    results = await validate_configured_models(transport=transport)

    assert {r.role: r.status for r in results} == {
        "primary": ModelValidationStatus.AVAILABLE,
        "fallback": ModelValidationStatus.AVAILABLE,
        "secondary_fallback": ModelValidationStatus.AVAILABLE,
    }
    assert all(r.ok for r in results)


@pytest.mark.asyncio
async def test_a_model_missing_from_the_catalogue_is_caught(chain):
    """The exact regression this module exists to catch: the configured
    model has silently disappeared from the provider's own listing."""
    transport = router({
        "generativelanguage": gemini_models_response("gemini-flash-latest"),
        "groq.com": openai_style_models_response("llama-3.1-8b-instant"),  # not ours
        "openrouter.ai": openai_style_models_response("nvidia/nemotron-3-super-120b-a12b:free"),
    })

    results = await validate_configured_models(transport=transport)
    by_role = {r.role: r for r in results}

    assert by_role["fallback"].status is ModelValidationStatus.MODEL_NOT_FOUND
    assert "openai/gpt-oss-120b" in by_role["fallback"].detail
    assert by_role["fallback"].ok is False
    # The other two entries are unaffected by one provider's problem.
    assert by_role["primary"].ok is True
    assert by_role["secondary_fallback"].ok is True


@pytest.mark.asyncio
async def test_rejected_credentials_are_reported_distinctly(chain):
    transport = router({
        "generativelanguage": httpx.Response(403, json={"error": "PERMISSION_DENIED"}),
        "groq.com": openai_style_models_response("openai/gpt-oss-120b"),
        "openrouter.ai": openai_style_models_response("nvidia/nemotron-3-super-120b-a12b:free"),
    })

    results = await validate_configured_models(transport=transport)
    primary = next(r for r in results if r.role == "primary")

    assert primary.status is ModelValidationStatus.INVALID_CREDENTIALS
    assert primary.ok is False


@pytest.mark.asyncio
async def test_an_unreachable_provider_is_reported_not_raised(chain):
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    results = await validate_configured_models(transport=httpx.MockTransport(refuse))

    assert all(r.status is ModelValidationStatus.UNREACHABLE for r in results)
    assert all(not r.ok for r in results)


@pytest.mark.asyncio
async def test_a_timeout_is_reported_as_unreachable(chain):
    def stall(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("deadline exceeded")

    results = await validate_configured_models(transport=httpx.MockTransport(stall))

    assert all(r.status is ModelValidationStatus.UNREACHABLE for r in results)


# ---------------------------------------------------------------------------
# Phase 16 — optional fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_optional_key_is_not_configured_and_makes_no_request(
    monkeypatch,
):
    """Phase 16: no key, no HTTP call, no failure — a legitimate state."""
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr(FAKE_GEMINI_KEY))
    monkeypatch.setattr(settings, "groq_api_key", SecretStr(FAKE_GROQ_KEY))
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "default_llm", GEMINI)
    monkeypatch.setattr(settings, "fallback_llm", GROQ)
    monkeypatch.setattr(settings, "secondary_fallback_llm", OPENROUTER)

    called_hosts: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        called_hosts.append(request.url.host)
        if "generativelanguage" in request.url.host:
            return gemini_models_response("gemini-flash-latest")
        return openai_style_models_response("openai/gpt-oss-120b")

    results = await validate_configured_models(transport=httpx.MockTransport(record))
    openrouter_result = next(r for r in results if r.role == "secondary_fallback")

    assert openrouter_result.status is ModelValidationStatus.NOT_CONFIGURED
    # Not routable (there is no key to route with) but also not a
    # startup-blocking problem -- `run_startup_validation` never fails
    # the process over it, which is the property Phase 16 actually
    # requires. `.ok` deliberately does not collapse that distinction;
    # see `ModelValidationResult.ok`'s docstring.
    assert openrouter_result.ok is False
    assert not any("openrouter" in host for host in called_hosts)


@pytest.mark.asyncio
async def test_one_broken_optional_fallback_does_not_affect_the_others(chain):
    """Phase 16/26: an invalid fallback model must not hide or corrupt
    a sibling entry's result."""
    transport = router({
        "generativelanguage": gemini_models_response("gemini-flash-latest"),
        "groq.com": openai_style_models_response("openai/gpt-oss-120b"),
        "openrouter.ai": openai_style_models_response("some-other-model"),
    })

    results = await validate_configured_models(transport=transport)
    by_role = {r.role: r.status for r in results}

    assert by_role["primary"] is ModelValidationStatus.AVAILABLE
    assert by_role["fallback"] is ModelValidationStatus.AVAILABLE
    assert by_role["secondary_fallback"] is ModelValidationStatus.MODEL_NOT_FOUND


# ---------------------------------------------------------------------------
# Never fatal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_startup_validation_never_raises_even_on_total_failure(chain, monkeypatch):
    """Phase 15: startup must never crash on this, whatever happens."""
    import app.core.llm.startup_validation as module

    async def explode(**_kwargs):
        raise RuntimeError("everything is on fire")

    monkeypatch.setattr(module, "validate_configured_models", explode)

    await run_startup_validation()  # must not raise


@pytest.mark.asyncio
async def test_run_startup_validation_completes_against_mocked_providers(chain, monkeypatch):
    """The full lifespan call path, offline."""
    import app.core.llm.startup_validation as module

    transport = router({
        "generativelanguage": gemini_models_response("gemini-flash-latest"),
        "groq.com": openai_style_models_response("openai/gpt-oss-120b"),
        "openrouter.ai": openai_style_models_response("nvidia/nemotron-3-super-120b-a12b:free"),
    })

    async def patched(**_kwargs):
        return await module.validate_configured_models(transport=transport)

    monkeypatch.setattr(module, "validate_configured_models", patched)

    await run_startup_validation()  # must not raise, must complete


# ---------------------------------------------------------------------------
# No credential ever reaches an outgoing request in a loggable place
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_key_travels_as_a_header_never_a_query_string(chain):
    """Gemini's key goes in `x-goog-api-key`, not `?key=...` — a query
    string is far more likely to end up in a proxy access log."""
    seen_urls: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if "generativelanguage" in request.url.host:
            return gemini_models_response("gemini-flash-latest")
        return openai_style_models_response("x")

    await validate_configured_models(transport=httpx.MockTransport(record))

    assert not any(FAKE_GEMINI_KEY in url for url in seen_urls)
    assert not any("key=" in url for url in seen_urls)
