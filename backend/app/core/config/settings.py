"""Application configuration loaded from environment variables.

Exposes a single cached `settings` instance backed by Pydantic Settings v2.
Only foundation-level configuration (app metadata, server, CORS, logging)
is defined here; settings for database, auth, and AI modules are added
alongside their respective milestones.
"""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application metadata
    app_name: str = "AIKDAP"
    app_version: str = "1.0.0"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # API
    api_v1_prefix: str = "/api/v1"

    # Security / JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Database
    database_url: str
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # CORS
    #
    # `NoDecode` opts this field out of pydantic-settings' automatic
    # JSON-decoding of complex-typed env values, which would otherwise
    # raise `SettingsError` on a plain comma-separated string before our
    # validator below ever runs. The validator then accepts either a
    # JSON array (`["https://a", "https://b"]`) or a comma-separated
    # string (`https://a,https://b`).
    backend_cors_origins: Annotated[list[str], NoDecode] = []

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Asset storage
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 100

    # Celery / background tasks
    celery_broker_url: str
    celery_result_backend: str

    # Document chunking (knowledge base pipeline)
    chunk_size: int = 1000
    chunk_overlap: int = 100

    # ------------------------------------------------------------------
    # LLM gateway (Sprint 9A)
    #
    # Model identifiers use LiteLLM's `provider/model` notation, which is
    # what routes a call to the right backend (`gemini/...`,
    # `ollama/...`, `groq/...`). Keeping them in configuration means
    # switching or upgrading a model is an environment change, not a
    # code change.
    #
    # `gemini_api_key` is a `SecretStr`: printing or logging the
    # settings object renders it as `**********`, so the key cannot leak
    # through a stray log line or a traceback. Read it explicitly with
    # `.get_secret_value()` at the single point of use.
    # ------------------------------------------------------------------
    gemini_api_key: SecretStr | None = None

    #: Credentials for the fallback providers, routed by `LLMGateway`
    #: since Sprint 9G. `SecretStr` for the same reason as
    #: `gemini_api_key`: printing settings renders them masked, and the
    #: value is read only at the single point of use.
    groq_api_key: SecretStr | None = None
    #: Kept configured but not part of the active chain (Sprint 9H):
    #: this deployment's DeepSeek account has zero balance
    #: ("Insufficient Balance", observed live 2026-08-16). The field
    #: and its credential plumbing are left in place rather than
    #: deleted — DeepSeek remains a usable provider if ever
    #: reconfigured and funded — but neither `FALLBACK_LLM` nor
    #: `SECONDARY_FALLBACK_LLM` names it by default any more.
    deepseek_api_key: SecretStr | None = None
    #: OpenRouter (Sprint 9H): the third fallback, replacing DeepSeek.
    openrouter_api_key: SecretStr | None = None

    #: Model used when a caller does not name one — the primary in the
    #: fallback chain.
    default_llm: str = "gemini/gemini-pro-latest"
    #: Tried when the primary fails with something a different provider
    #: could plausibly survive. Empty disables fallback.
    fallback_llm: str | None = None
    #: Tried when the first fallback also fails (Sprint 9G). Empty
    #: disables it. A provider whose API key is missing is skipped
    #: cleanly rather than attempted and failed.
    #:
    #: The model lives inside this value (`openrouter/<vendor id>`)
    #: rather than in a separate `OPENROUTER_MODEL` setting, the same
    #: way Groq's fallback model lives inside `FALLBACK_LLM` rather
    #: than a `GROQ_MODEL` field — one source of truth per provider
    #: slot, consistent with the convention Sprint 9G already
    #: established.
    secondary_fallback_llm: str | None = None

    #: Per-role models. `synthesis_model` is what the research
    #: workflow's grounded synthesis step asks the gateway for.
    planner_model: str = "gemini/gemini-pro-latest"
    synthesis_model: str = "gemini/gemini-pro-latest"

    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=2048, gt=0)
    llm_timeout: float = Field(default=60.0, gt=0)

    # ------------------------------------------------------------------
    # Provider resilience (Sprint 9G)
    #
    # One retry policy, applied in the gateway and nowhere else. Nodes,
    # services and routers must not add their own — layered retries
    # multiply, so three levels of "just three attempts" is 27 calls
    # against a provider that already said no.
    #
    # `llm_max_retries` counts RETRIES, not attempts: 2 means up to 3
    # calls. Only transient failures are retried (per-minute rate
    # limits, 503s, timeouts, connection errors); a spent daily quota
    # never is, however many retries are configured.
    #
    # Delays are exponential with equal jitter, capped by
    # `llm_retry_max_delay`: roughly 0.5-1s, then 1-2s, then 2-4s at
    # the defaults. Equal rather than full jitter so a retry cannot
    # collapse to an immediate repeat, which would defeat the point.
    # ------------------------------------------------------------------
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_retry_base_delay: float = Field(default=1.0, ge=0.0)
    llm_retry_max_delay: float = Field(default=8.0, ge=0.0)

    # How long a recorded provider failure keeps the gateway from
    # retrying that provider. Every one is bounded so the breaker
    # self-heals without operator action.
    #
    # The quota cooldown is the load-bearing one. Gemini's free tier
    # resets at midnight Pacific, which this process cannot compute
    # reliably, so instead of guessing the wall-clock boundary the
    # entry simply ages out after an hour: at worst one wasted request
    # per hour re-confirms the quota is still spent. The alternative —
    # no cooldown — would disable the provider until a restart.
    llm_quota_cooldown_seconds: float = Field(default=3600.0, gt=0)
    llm_rate_limit_cooldown_seconds: float = Field(default=60.0, gt=0)
    llm_unavailable_cooldown_seconds: float = Field(default=60.0, gt=0)
    llm_configuration_error_cooldown_seconds: float = Field(default=300.0, gt=0)

    # ------------------------------------------------------------------
    # Redis-backed provider health (Sprint 9H)
    #
    # Sprint 9G's breaker lived in one process's memory, so a quota
    # exhaustion the worker discovered mid-research-run was invisible to
    # the API's `/health` until the API made its own failing call.
    # Backing it with Redis — already-required infrastructure, the same
    # broker Celery uses — makes the state visible to both processes
    # immediately, at the cost of one small Redis round trip per gateway
    # attempt.
    #
    # `llm_health_redis_timeout` is deliberately tiny. The breaker is a
    # synchronous client call inside an async method (see
    # `provider_health.RedisProviderHealthRegistry`), so a slow or dead
    # Redis must fail fast rather than stall the event loop — a bounded
    # 200ms of blocking is an acceptable trade against the alternative
    # (a full async client + connection-pool lifecycle for a value this
    # small), and it is far shorter than any LLM call it sits beside.
    #
    # `llm_health_state_ttl_seconds` is the hygiene TTL for states that
    # have no cooldown of their own (`healthy`, `configured`) — so a
    # Redis key is never permanent even for a provider nobody has
    # touched in days. It does not gate retry behaviour; only the
    # per-status cooldowns above do that.
    # ------------------------------------------------------------------
    llm_health_redis_timeout: float = Field(default=0.2, gt=0)
    llm_health_state_ttl_seconds: float = Field(default=86_400.0, gt=0)

    # ------------------------------------------------------------------
    # Stale research-run reconciliation (Sprint 9J)
    #
    # `ResearchExecutionService.execute()` sets `status=RUNNING` before
    # doing any real work and only reaches `_complete()`/`_fail()` if
    # its own Python process survives to run them. A worker crash, OOM
    # kill, or container restart mid-run skips both — the row is left
    # at `RUNNING` forever, with nothing in the architecture that would
    # ever revisit it (confirmed: a stale run from an earlier sprint's
    # interrupted manual test is still sitting at `RUNNING` days later).
    #
    # `research_run_stale_after_seconds` is the conservative ceiling
    # below which a `RUNNING` run must be left alone. Sized from the
    # worst case the current retry/timeout configuration can produce in
    # one execution attempt, not from typical observed durations (which
    # are seconds, not minutes): up to 3 providers in the fallback
    # chain, each retried up to `llm_max_retries` times at up to
    # `llm_timeout` seconds per attempt, plus backoff between retries,
    # is roughly 3 x 3 x 60s, ~9 minutes, in the pathological case where
    # every single call on every provider times out fully before
    # falling through — retrieval and reranking add at most a few more
    # seconds on top of that. 20 minutes leaves a wide safety margin
    # above that ceiling while still being short enough that a
    # genuinely stuck run does not sit unreconciled for days. It does
    # not gate retry behaviour — only reconciliation reads it.
    # ------------------------------------------------------------------
    research_run_stale_after_seconds: float = Field(default=1_200.0, gt=0)

    #: Whether research synthesis answers with a real model
    #: (`GroundedSynthesizer`) or extracts from the evidence without one
    #: (`ExtractiveSynthesizer`). There is deliberately no automatic
    #: downgrade between them: if this is on and the model cannot be
    #: reached, the run fails with that reason rather than quietly
    #: answering by a different mechanism.
    synthesis_grounded: bool = True
    #: Character budget for the evidence placed in the synthesis prompt.
    #: Evidence beyond it is excluded — and therefore cannot be cited,
    #: since the model never sees it. Sized well below the model's
    #: context window so the system prompt and question always fit.
    synthesis_max_evidence_characters: int = Field(default=12_000, gt=0)

    @property
    def has_gemini_credentials(self) -> bool:
        """Whether a non-empty Gemini API key is configured.

        Lets callers check for credentials without ever reading the
        secret itself.
        """
        return bool(self.gemini_api_key and self.gemini_api_key.get_secret_value().strip())

    @property
    def has_groq_credentials(self) -> bool:
        """Whether a non-empty Groq API key is configured."""
        return bool(self.groq_api_key and self.groq_api_key.get_secret_value().strip())

    @property
    def has_deepseek_credentials(self) -> bool:
        """Whether a non-empty DeepSeek API key is configured."""
        return bool(self.deepseek_api_key and self.deepseek_api_key.get_secret_value().strip())

    @property
    def has_openrouter_credentials(self) -> bool:
        """Whether a non-empty OpenRouter API key is configured."""
        return bool(
            self.openrouter_api_key and self.openrouter_api_key.get_secret_value().strip()
        )

    # ------------------------------------------------------------------
    # Local document intelligence — Ollama + Qwen (Sprint 9B)
    #
    # `ollama_base_url` defaults to `host.docker.internal`, which is
    # what actually resolves from inside the backend/worker containers
    # on this Docker Desktop (Windows) setup — verified live, not
    # assumed, before picking this default. On native Linux Docker
    # Engine this hostname does not resolve by default and the compose
    # file would need `extra_hosts: ["host.docker.internal:host-gateway"]`;
    # left as an operator note rather than added speculatively, since
    # this deployment doesn't need it.
    #
    # `qwen_model` is the literal Ollama model tag — verified present
    # via `ollama list` (`qwen3.5:4b`, 3.4 GB). No other model is ever
    # silently substituted; an unavailable model is a reported error
    # (see `app.core.llm.gateway.LLMModelNotFoundError`), not a
    # fallback trigger.
    #
    # `qwen_think` defaults to disabled: Qwen 3.5 is a hybrid
    # "thinking" model, and live testing against this host showed it
    # can spend its entire completion budget on internal reasoning
    # before emitting any visible text (431 completion tokens for a
    # one-word reply, 0 of them the reply itself). Disabling thinking
    # dropped that same call to 2 tokens / ~10s and produced accurate,
    # correctly-grounded structured output for the real test document
    # in ~25s. Configurable, not hardcoded, in case a future document
    # genuinely benefits from the deeper (slower) reasoning mode.
    #
    # `qwen_timeout` is deliberately much larger than `llm_timeout`
    # (tuned for cloud latency): CPU-only local inference of a 4B model
    # is far slower than a cloud API call, especially on a cold model
    # load (~40s observed) plus generation.
    # ------------------------------------------------------------------
    ollama_base_url: str = "http://host.docker.internal:11434"
    qwen_model: str = "qwen3.5:4b"
    qwen_think: bool = False
    qwen_max_tokens: int = Field(default=1024, gt=0)
    qwen_timeout: float = Field(default=180.0, gt=0)

    #: Character budget for a single Qwen call. Longer extracted text is
    #: split with the existing `chunk_text()` utility and processed as
    #: multiple calls, then merged deterministically — see
    #: `app.modules.assets.processing.document_understanding`.
    qwen_max_input_characters: int = Field(default=6000, gt=0)

    # ------------------------------------------------------------------
    # Local embeddings — BGE-M3 through Ollama + pgvector (Sprint 9C)
    #
    # `embedding_model` reuses the `EMBEDDING_MODEL` env var that
    # already existed in `.env` (previously an orphaned setting: no
    # `Settings` field read it, and it named a cloud OpenAI model
    # `text-embedding-3-small` that nothing in this codebase calls).
    # Repointed at the local model this sprint actually implements
    # rather than introducing a second config key for the same concept.
    #
    # `embedding_dimension` is not a guess: verified live against this
    # host's Ollama instance (`litellm.aembedding(model="ollama/bge-m3",
    # ...)`) before being set — BGE-M3 returned exactly 1024 floats.
    # Declared as configuration (not hardcoded in the pgvector column
    # definition) because the column type must match whatever this
    # value is, and Alembic reads it at migration time.
    # ------------------------------------------------------------------
    embedding_model: str = "bge-m3"
    embedding_dimension: int = Field(default=1024, gt=0)
    # ------------------------------------------------------------------
    # Two-stage retrieval reranking — BGE-Reranker-v2-m3 (Sprint 9D)
    #
    # RUNTIME: llama.cpp (`llama-server --reranking`), not Ollama.
    # Ollama cannot serve this model — verified live on this host: no
    # rerank endpoint exists at all (`/api/rerank`, `/v1/rerank`,
    # `/rerank`, `/api/rank`, `/v1/reranking` -> 404), it advertises the
    # model's capability as `completion` only, and both `/api/embed` and
    # `/api/generate` crash the llama-server subprocess (exit
    # 0xc0000409). BGE-M3 and Qwen worked at the same moment, so the
    # incompatibility is specific to the cross-encoder.
    #
    # Because `reranker_base_url`/`reranker_endpoint_path` were
    # configuration rather than hardcoded, moving to a runtime that can
    # serve the model needed no code change: llama.cpp already speaks
    # the standard rerank contract this provider implements
    # (`{model, query, documents}` -> `{results: [{index,
    # relevance_score}]}`). The model itself is unchanged — the same
    # GGUF, BAAI/bge-reranker-v2-m3 Q8_0. No other model is ever
    # substituted; if the endpoint is unreachable the search degrades to
    # retrieval-only and says so via `reranking_status`, never silently.
    #
    # `reranker_candidate_k` > `reranker_top_k` on purpose: stage 1
    # over-retrieves so stage 2 has something to reorder. Retrieving
    # only `top_k` before reranking would make the second stage
    # pointless.
    # ------------------------------------------------------------------
    reranker_enabled: bool = True
    reranker_model: str = "bge-reranker-v2-m3"
    #: Where llama-server is listening. Empty falls back to
    #: `ollama_base_url`, which cannot serve this model and will report
    #: `reranking_status=unavailable` — a safe, loud default rather than
    #: a working one, so a deployment that forgets to set this degrades
    #: visibly instead of appearing to rerank.
    reranker_base_url: str = ""
    #: llama.cpp's reranking route. It also answers on `/v1/rerank` and
    #: `/rerank`; this one is the documented native path.
    reranker_endpoint_path: str = "/reranking"
    #: llama-server's liveness route (Sprint 9G). `GET`ting it is free —
    #: it loads no context and scores nothing — which is exactly why
    #: `/health` probes this instead of sending a real rerank request.
    reranker_health_path: str = "/health"
    #: Health probes must not inherit the 60s inference timeout: an
    #: unreachable reranker would then stall the health endpoint for a
    #: minute, turning a diagnostic into an outage of its own.
    reranker_health_timeout: float = Field(default=3.0, gt=0)
    reranker_timeout: float = Field(default=60.0, gt=0)
    reranker_candidate_k: int = Field(default=20, gt=0)
    reranker_top_k: int = Field(default=5, gt=0)
    #: Cross-encoders have a fixed context window (8192 tokens for this
    #: model). Candidates are truncated to this many characters before
    #: scoring so one oversized chunk cannot fail the whole batch.
    reranker_max_document_characters: int = Field(default=4000, gt=0)

    #: Minimum `rerank_score` for a chunk to be used as evidence
    #: (Sprint 9F). A reranker asked for the top 5 always returns 5,
    #: however irrelevant, so ordering alone cannot keep an unrelated
    #: question from reaching the synthesis model with confident-looking
    #: evidence attached.
    #:
    #: This is a raw BGE-Reranker-v2-m3 logit, not a probability, and is
    #: NOT comparable to a similarity score. It was measured, not
    #: chosen: see `docs/relevance-calibration.md` for the 70-pair
    #: fixture behind it (precision 0.818, recall 0.818 at this value).
    #: There is no meaningful default for a different corpus or a
    #: different reranker — recalibrate rather than reusing this number.
    #: Lower admits more evidence; raise it to filter harder.
    reranker_relevance_threshold: float = -2.0

    @property
    def resolved_reranker_base_url(self) -> str:
        """The reranker endpoint's base URL.

        Falls back to Ollama's only so an unconfigured deployment fails
        loudly (404 -> `reranking_status=unavailable`) instead of
        silently pointing at nothing.
        """
        return (self.reranker_base_url or self.ollama_base_url).rstrip("/")
    #: Embeddings are a single forward pass with no "thinking" overhead
    #: (unlike Qwen's chat completions), so this is far smaller than
    #: `qwen_timeout`.
    embedding_timeout: float = Field(default=60.0, gt=0)

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Parse CORS origins from a JSON array or a comma-separated string."""
        if isinstance(value, list):
            return value
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return []

        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"backend_cors_origins is not valid JSON: {stripped!r}"
                ) from exc
            if not isinstance(parsed, list):
                raise ValueError("backend_cors_origins JSON value must be an array")
            return [str(origin).strip() for origin in parsed if str(origin).strip()]

        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """Whether the app is running in the production environment."""
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    Using `lru_cache` ensures the environment is parsed once and reused,
    while still allowing tests to override via `get_settings.cache_clear()`.
    """
    return Settings()


settings: Settings = get_settings()
