"""Second-stage reranking: BGE-Reranker-v2-m3 (Sprint 9D).

Stage 2 of two-stage retrieval. Stage 1 (BGE-M3 + pgvector, Sprint 9C)
over-retrieves `candidate_k` chunks by vector similarity; this module
rescores those candidates with a cross-encoder, which reads the query
and a document *together* rather than comparing two independently
computed vectors, and returns the `top_k` best.

## Runtime: llama.cpp, not Ollama (verified live, not assumed)

The model runs under `llama-server --reranking`. Ollama cannot serve
it, even though the model is pulled there:

- no rerank endpoint exists (`/api/rerank`, `/v1/rerank`, `/rerank`,
  `/api/rank`, `/v1/reranking` all return 404);
- `ollama show` reports the model's only capability as `completion`;
- `/api/embed` and `/api/generate` both crash the llama-server
  subprocess (exit `0xc0000409`, stack-based buffer overrun).

BGE-M3 embeddings and Qwen generation were confirmed working against
the same Ollama instance immediately before and after, so this is a
cross-encoder/runtime incompatibility, not a broken Ollama. BGE-M3
still runs on Ollama; only the cross-encoder moved.

Because `HttpRerankerProvider` speaks the *standard* rerank contract
rather than an Ollama-specific one:

    POST {base_url}{path}
    {"model": ..., "query": ..., "documents": [...]}
    -> {"results": [{"index": 0, "relevance_score": 0.93}, ...]}

switching runtimes was a configuration change (`RERANKER_BASE_URL`,
`RERANKER_ENDPOINT_PATH`) and required no change to this module —
llama.cpp implements exactly this shape. The model is unchanged: the
same `BAAI/bge-reranker-v2-m3` GGUF at Q8_0. No other model is ever
substituted. If the endpoint becomes unreachable the caller degrades
to retrieval-only order and reports `reranking_status=unavailable`; it
never fabricates scores and never falls back to a cloud model.

Note on scores: this cross-encoder emits an unbounded logit per
(query, document) pair, so real scores are frequently negative
(observed range roughly -10 to 0 on this corpus). Higher is more
relevant; the values are not probabilities and are not comparable to
cosine similarity.
"""

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class RerankingStatus(str, Enum):
    """Whether stage 2 actually ran, and if not, why.

    Carried through to the API response so a caller can always tell
    reranked results from retrieval-only ones — the Sprint 9D
    requirement that a fallback must never be silent.
    """

    #: The reranker scored the candidates; results are in rerank order.
    COMPLETED = "completed"
    #: Turned off by configuration (`RERANKER_ENABLED=false`) or by the
    #: request (`rerank=false`). Results are in retrieval order.
    DISABLED = "disabled"
    #: The reranker could not be reached, timed out, or returned an
    #: unusable response. Results are in retrieval order.
    UNAVAILABLE = "unavailable"
    #: Nothing to rerank (no candidates matched stage 1).
    NOT_APPLICABLE = "not_applicable"


class RerankerError(Exception):
    """Base class for reranking failures."""


class RerankerUnavailableError(RerankerError):
    """The reranker endpoint could not be reached, or does not exist.

    Distinct from `RerankerResponseError`: this means the runtime
    cannot serve the model at all (the current state of Ollama for
    BGE-Reranker-v2-m3), as opposed to answering with something
    unusable.
    """


class RerankerResponseError(RerankerError):
    """The reranker responded, but the response could not be used."""


@dataclass(frozen=True)
class RerankCandidate:
    """One stage-1 candidate offered to the reranker.

    Carries full identity, not just text: the reranker returns
    positional indices, and everything the caller needs to reassemble a
    result (chunk, asset, project, the original retrieval score) must
    survive stage 2 rather than being re-looked-up afterwards.
    """

    chunk_id: uuid.UUID
    asset_id: uuid.UUID
    project_id: uuid.UUID
    chunk_index: int
    content: str
    #: Stage-1 cosine distance, preserved untouched — the reranker's
    #: score is a different measurement on a different scale and must
    #: never overwrite it.
    retrieval_distance: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RerankedCandidate:
    """A candidate plus its cross-encoder score."""

    candidate: RerankCandidate
    #: Raw relevance score as returned by the model, unnormalized.
    #: BGE-Reranker-v2-m3 emits a single logit per (query, document)
    #: pair; higher means more relevant, and values are not bounded to
    #: [0, 1] and are not comparable to cosine similarity. Recorded
    #: as-is so callers can see what the model actually produced.
    rerank_score: float


class RerankerProvider(ABC):
    """Contract for a second-stage reranker.

    Implementations must preserve candidate identity and must not
    invent scores for candidates the model did not score.
    """

    @property
    @abstractmethod
    def model(self) -> str:
        """The model identifier this provider scores with."""

    @abstractmethod
    async def rerank(
        self, *, query: str, candidates: list[RerankCandidate], top_k: int
    ) -> list[RerankedCandidate]:
        """Score `candidates` against `query`, best first, limited to `top_k`.

        Raises `RerankerUnavailableError` if the runtime cannot serve
        the model, or `RerankerResponseError` if it answers with
        something unusable. Never returns partially-scored output.
        """


class HttpRerankerProvider(RerankerProvider):
    """Reranks via an HTTP endpoint speaking the standard rerank contract.

    Batches the whole candidate list into one request (the contract's
    `documents` array) rather than one call per candidate: a
    cross-encoder scores pairs independently, but a per-candidate
    request would mean N model loads and N round trips.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        endpoint_path: str | None = None,
        timeout: float | None = None,
        max_document_characters: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model or settings.reranker_model
        self._base_url = (base_url or settings.resolved_reranker_base_url).rstrip("/")
        self._endpoint_path = endpoint_path or settings.reranker_endpoint_path
        self._timeout = timeout or settings.reranker_timeout
        self._max_document_characters = (
            max_document_characters or settings.reranker_max_document_characters
        )
        # Injected only by tests, so the real request building, parsing,
        # and error mapping below are exercised against a
        # `MockTransport` rather than stubbed out wholesale.
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    @property
    def endpoint(self) -> str:
        """The full rerank URL this provider posts to."""
        return f"{self._base_url}{self._endpoint_path}"

    async def rerank(
        self, *, query: str, candidates: list[RerankCandidate], top_k: int
    ) -> list[RerankedCandidate]:
        """Score every candidate in one batched request."""
        if not query.strip():
            raise RerankerResponseError("Cannot rerank against an empty query.")
        if not candidates:
            return []

        documents = [
            candidate.content[: self._max_document_characters] for candidate in candidates
        ]
        payload = {"model": self._model, "query": query, "documents": documents}

        # Document text is not logged: chunks are user content, and
        # this mirrors the embedding gateway's logging contract.
        logger.info(
            "reranker_request_started",
            model=self._model,
            endpoint=self.endpoint,
            candidate_count=len(candidates),
            top_k=top_k,
        )

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(self.endpoint, json=payload)
        except httpx.TimeoutException as exc:
            raise RerankerUnavailableError(
                f"The reranker at {self.endpoint} timed out after {self._timeout}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise RerankerUnavailableError(
                f"Could not reach the reranker at {self.endpoint}: {exc}"
            ) from exc

        latency_ms = int((time.monotonic() - start) * 1000)

        if response.status_code == 404:
            # The specific, currently-expected failure on Ollama: the
            # endpoint does not exist. Reported as unavailable (a
            # runtime capability gap), not as a bad response.
            raise RerankerUnavailableError(
                f"The reranker endpoint {self.endpoint} does not exist "
                f"(HTTP 404). This runtime does not implement a rerank API."
            )
        if response.status_code >= 400:
            raise RerankerUnavailableError(
                f"The reranker at {self.endpoint} returned HTTP "
                f"{response.status_code}: {response.text[:300]}"
            )

        scored = self._parse(response, candidates=candidates)
        ranked = sorted(scored, key=lambda item: item.rerank_score, reverse=True)[:top_k]
        logger.info(
            "reranker_request_completed",
            model=self._model,
            candidate_count=len(candidates),
            returned=len(ranked),
            latency_ms=latency_ms,
        )
        return ranked

    def _parse(
        self, response: httpx.Response, *, candidates: list[RerankCandidate]
    ) -> list[RerankedCandidate]:
        """Map the endpoint's positional results back onto candidates.

        Strict about indices: an out-of-range or duplicated index would
        silently misattribute a score to the wrong chunk, which is
        worse than failing.
        """
        try:
            body = response.json()
        except ValueError as exc:
            raise RerankerResponseError("The reranker did not return JSON.") from exc

        raw_results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(raw_results, list):
            raise RerankerResponseError(
                "The reranker response has no 'results' array."
            )

        scored: list[RerankedCandidate] = []
        seen_indices: set[int] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                raise RerankerResponseError("A reranker result entry is not an object.")
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if not isinstance(index, int) or not 0 <= index < len(candidates):
                raise RerankerResponseError(
                    f"The reranker returned an out-of-range index: {index!r}."
                )
            if index in seen_indices:
                raise RerankerResponseError(
                    f"The reranker returned index {index} more than once."
                )
            if not isinstance(score, (int, float)):
                raise RerankerResponseError(
                    f"The reranker returned a non-numeric score: {score!r}."
                )
            seen_indices.add(index)
            scored.append(
                RerankedCandidate(candidate=candidates[index], rerank_score=float(score))
            )

        if not scored:
            raise RerankerResponseError("The reranker returned no scored results.")
        return scored


def get_reranker_provider() -> RerankerProvider:
    """Return the configured reranker.

    Deliberately not `lru_cache`d, unlike `get_embedding_provider`: this
    provider holds no expensive state (an `AsyncClient` is created per
    call), and the failure test toggles configuration at runtime.
    """
    return HttpRerankerProvider()


class RerankerHealthStatus(str, Enum):
    """Whether the reranker runtime is up (Sprint 9G)."""

    #: llama-server answered its liveness route.
    HEALTHY = "healthy"
    #: Reachable but reporting itself not ready — the model is still
    #: loading, or the server is busy. Distinct from `UNAVAILABLE`
    #: because the remedy is to wait, not to start the process.
    LOADING = "loading"
    #: Nothing is listening, or it answered with something unusable.
    UNAVAILABLE = "unavailable"
    #: Reranking is switched off by configuration, so there is nothing
    #: to be unhealthy about.
    DISABLED = "disabled"


@dataclass(frozen=True)
class RerankerHealth:
    """Outcome of one reranker liveness probe. Contains no user content."""

    status: RerankerHealthStatus
    model: str
    endpoint: str
    latency_ms: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """A plain, JSON-safe dict for the health endpoint."""
        return {
            "status": self.status.value,
            "model": self.model,
            "endpoint": self.endpoint,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
        }


async def check_reranker_health(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> RerankerHealth:
    """Probe the reranker runtime without reranking anything.

    Sprint 9G, Phase 13. The point is visibility: the reranker is a
    *host* process (`scripts/reranker.ps1`), outside Docker's
    supervision, so nothing restarts it and nothing notices when it
    dies. Retrieval keeps working when it does — degrading to stage-1
    order, honestly labelled `reranking_status=unavailable` — which is
    correct behaviour and also exactly why the failure can go unnoticed
    for a long time. This is how it becomes visible.

    Deliberately a `GET` on llama-server's liveness route rather than a
    real rerank request. Scoring even one document would load context
    and burn GPU time on every health poll, and it would tell us
    nothing extra: the question here is "is the process alive?", not
    "is the model good?".

    The backend never starts or stops the reranker. Reporting a problem
    and acting on it are different jobs, and an API process that
    launches host executables is a much worse idea than an operator
    reading a status.

    Never raises: an unreachable reranker is the result, not an error.
    """
    model = settings.reranker_model
    base_url = settings.resolved_reranker_base_url
    endpoint = f"{base_url}{settings.reranker_health_path}"

    if not settings.reranker_enabled:
        return RerankerHealth(
            status=RerankerHealthStatus.DISABLED,
            model=model,
            endpoint=endpoint,
            detail="RERANKER_ENABLED is false; stage 2 is switched off.",
        )

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=settings.reranker_health_timeout, transport=transport
        ) as client:
            response = await client.get(endpoint)
    except httpx.HTTPError as exc:
        return RerankerHealth(
            status=RerankerHealthStatus.UNAVAILABLE,
            model=model,
            endpoint=endpoint,
            latency_ms=int((time.monotonic() - start) * 1000),
            detail=f"Could not reach the reranker: {type(exc).__name__}.",
        )

    latency_ms = int((time.monotonic() - start) * 1000)

    if response.status_code == 503:
        # llama-server's documented "model still loading" answer.
        return RerankerHealth(
            status=RerankerHealthStatus.LOADING,
            model=model,
            endpoint=endpoint,
            latency_ms=latency_ms,
            detail="The reranker is up but not ready to serve yet.",
        )
    if response.status_code != 200:
        return RerankerHealth(
            status=RerankerHealthStatus.UNAVAILABLE,
            model=model,
            endpoint=endpoint,
            latency_ms=latency_ms,
            detail=f"The reranker returned HTTP {response.status_code}.",
        )

    return RerankerHealth(
        status=RerankerHealthStatus.HEALTHY,
        model=model,
        endpoint=endpoint,
        latency_ms=latency_ms,
    )
