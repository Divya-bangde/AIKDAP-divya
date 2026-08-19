"""Embedding provider abstraction.

Defines `EmbeddingProvider`, the interface every embedding backend
(OpenAI, NVIDIA NIM, Voyage AI, Jina AI, a local model) implements.

`OllamaBgeM3EmbeddingProvider` (Sprint 9C) is the first real
implementation, using the same centralized `LLMGateway` (Sprint 9A)
that document understanding (Sprint 9B) already drives Ollama through
— no second Ollama HTTP client. `NullEmbeddingProvider` remains as the
structural placeholder Sprint 6 shipped, kept for tests and for any
future deployment that runs with no embedding backend configured.

Adding a further provider (OpenAI, NVIDIA NIM, ...) later means a new
`EmbeddingProvider` subclass and a branch in `get_embedding_provider`
— no changes to `pipeline.py`, `service.py`, or any router.
"""

from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import settings
from app.core.llm import LLMGateway, get_llm_gateway
from app.modules.knowledge_base.enums import EmbeddingProviderName


class EmbeddingProvider(ABC):
    """Abstract interface for turning text into embedding vectors."""

    @property
    @abstractmethod
    def name(self) -> EmbeddingProviderName:
        """Identifier for this provider, stored on each embedded chunk."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Vector dimensionality this provider produces."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per input, in order."""


class NullEmbeddingProvider(EmbeddingProvider):
    """Placeholder provider: performs no real embedding.

    Exists so the pipeline's shape (extract -> chunk -> embed) and the
    `EmbeddingProvider` interface are real and testable today, even
    though no backend is wired in yet.
    """

    @property
    def name(self) -> EmbeddingProviderName:
        return EmbeddingProviderName.NONE

    @property
    def dimensions(self) -> int:
        return 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "No embedding provider is configured. NullEmbeddingProvider is "
            "a structural placeholder; real embedding generation (OpenAI, "
            "NVIDIA NIM, Voyage AI, Jina AI, or a local model) is future work."
        )


class OllamaBgeM3EmbeddingProvider(EmbeddingProvider):
    """Real embedding provider: BGE-M3 through Ollama, via `LLMGateway`.

    `dimensions` is fixed to `settings.embedding_dimension` (1024,
    verified live against this deployment's model before being set as
    the default — see `settings.py`) rather than re-derived per call:
    the pgvector column width is committed at migration time, so a
    provider whose model started returning a different width would
    need a schema change anyway, not a runtime adaptation.
    """

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._gateway = gateway or get_llm_gateway()

    @property
    def name(self) -> EmbeddingProviderName:
        return EmbeddingProviderName.LOCAL

    @property
    def dimensions(self) -> int:
        return settings.embedding_dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts with BGE-M3. `LLMError` propagates
        unchanged so the caller can distinguish an unreachable Ollama
        instance from a genuinely bad response — mirroring
        `QwenDocumentUnderstandingService`'s failure contract."""
        response = await self._gateway.embed(
            texts=texts,
            model=f"ollama/{settings.embedding_model}",
            timeout=settings.embedding_timeout,
        )
        if response.dimension != self.dimensions:
            raise ValueError(
                f"BGE-M3 returned {response.dimension}-dimensional vectors; "
                f"the configured pgvector column is {self.dimensions}-dimensional "
                "(EMBEDDING_DIMENSION). Update the configuration and re-run the "
                "migration rather than storing a mismatched vector."
            )
        return response.vectors


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Dependency provider for the configured embedding backend.

    Returns the real `OllamaBgeM3EmbeddingProvider` — the only backend
    this sprint implements, matching the AIKDAP technology matrix's
    "Local Cognitive: BGE-M3". A future cloud provider (OpenAI, NVIDIA
    NIM, ...) would branch on a settings-driven provider name here,
    mirroring how `assets.storage.get_storage_provider` is structured.
    """
    return OllamaBgeM3EmbeddingProvider()
