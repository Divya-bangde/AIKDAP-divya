"""Embedding provider abstraction.

Defines `EmbeddingProvider`, the interface every embedding backend
(OpenAI, NVIDIA NIM, Voyage AI, Jina AI, a local model) implements.
`NullEmbeddingProvider` is the only implementation this sprint — a
structural placeholder that raises if `embed()` is ever actually
called. The processing pipeline never calls it; chunks are created
with `embedding_status=PENDING` and left there for a future sprint's
embedding worker.

The point of this file existing now, doing nothing, is that when a
real provider is added later, it only needs a new `EmbeddingProvider`
subclass and a branch in `get_embedding_provider` — no changes to
`pipeline.py`, `service.py`, or any router.
"""

from abc import ABC, abstractmethod
from functools import lru_cache

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


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Dependency provider for the configured embedding backend.

    Always returns `NullEmbeddingProvider` today. A real provider
    would be selected here (e.g. branching on a settings-driven
    provider name), mirroring how `assets.storage.get_storage_provider`
    is structured to swap backends later.
    """
    return NullEmbeddingProvider()
