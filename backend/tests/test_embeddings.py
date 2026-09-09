"""Sprint 9C: BGE-M3 embedding provider and pipeline-integration unit tests.

Offline throughout: `LLMGateway.embed` is replaced with a double, so no
test starts Ollama or depends on a GPU. The real, unmocked connectivity
and pgvector proof lives in the separate live validation recorded in
the sprint report — see `test_semantic_search.py` for the pgvector
query-correctness tests (those run against the real Postgres instance,
same convention `test_research_citations.py` established, because
ranking-by-distance is a property of the database, not something a
mock can verify).
"""

import uuid
from typing import Any

import pytest

from app.core.llm.gateway import LLMConnectionError, LLMEmbeddingResponse
from app.modules.assets.ai_profile import AIProfile
from app.modules.assets.enums import AssetProcessingStatus, AssetSource, AssetStatus, AssetType, EmbeddingStatus
from app.modules.assets.models import Asset
from app.modules.assets.processing.document_understanding import QwenDocumentUnderstandingService
from app.modules.assets.processing.pipeline import AssetProcessingService
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import StorageProvider
from app.modules.knowledge_base.embeddings import EmbeddingProvider, GatewayEmbeddingProvider
from app.modules.knowledge_base.enums import EmbeddingProviderName
from app.modules.knowledge_base.repository import KnowledgeChunkRepository

TEST_TEXT = "The Indian poultry industry faces challenges related to feed costs and disease management."


def _vector(dim: int = 1024, seed: float = 0.01) -> list[float]:
    return [seed] * dim


class GatewayDouble:
    """Records `.embed()` calls and returns a scripted result or raises."""

    def __init__(
        self, *, vectors: list[list[float]] | None = None, raises: Exception | None = None
    ) -> None:
        self._vectors = vectors
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def embed(self, **kwargs: Any) -> LLMEmbeddingResponse:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        vectors = self._vectors if self._vectors is not None else [_vector()]
        return LLMEmbeddingResponse(
            vectors=vectors,
            dimension=len(vectors[0]) if vectors else 0,
            model=kwargs["model"],
            provider="ollama",
            latency_ms=1,
        )


class FakeQwen:
    """A no-op Qwen understanding service, so pipeline tests here don't
    also exercise (or depend on the live behaviour of) Sprint 9B."""

    async def analyze(self, text: str):
        from app.modules.assets.processing.document_understanding import DocumentUnderstandingError

        raise DocumentUnderstandingError("not exercised by these tests")


class FakeStorage(StorageProvider):
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def save(self, *, project_id, filename, content: bytes) -> str:
        path = f"{project_id}/{filename}"
        self._files[path] = content
        return path

    async def read(self, storage_path: str) -> bytes:
        return self._files[storage_path]

    async def delete(self, storage_path: str) -> None:
        self._files.pop(storage_path, None)

    def exists(self, storage_path: str) -> bool:
        return storage_path in self._files


def _make_asset(**overrides: Any) -> Asset:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title="Test Document",
        description=None,
        asset_type=AssetType.DOCUMENT,
        status=AssetStatus.ACTIVE,
        mime_type="text/plain",
        file_name="test.txt",
        file_extension=".txt",
        file_size=len(TEST_TEXT),
        storage_path="unused",
        checksum="unused",
        source=AssetSource.UPLOAD,
        version=1,
        tags=[],
        asset_metadata={},
        ai_profile=AIProfile().model_dump(mode="json"),
        created_by=None,
        processing_status=AssetProcessingStatus.PENDING,
    )
    defaults.update(overrides)
    return Asset(**defaults)


# ---------------------------------------------------------------------------
# TEST 1 — embedding service initializes correctly
# ---------------------------------------------------------------------------


def test_provider_initializes_with_configured_name_and_dimension():
    from app.core.config import settings

    provider = GatewayEmbeddingProvider(gateway=GatewayDouble())  # type: ignore[arg-type]
    assert provider.name == EmbeddingProviderName.LOCAL
    assert provider.dimensions == settings.embedding_dimension == 1024


def test_provider_label_follows_the_configured_provider_prefix(monkeypatch):
    """Switching backends is a config change, and the provenance label
    stored on every chunk must follow it — otherwise a re-embed onto a
    hosted provider would still be recorded as `local`."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "embedding_model", "jina_ai/jina-embeddings-v3")
    provider = GatewayEmbeddingProvider(gateway=GatewayDouble())  # type: ignore[arg-type]

    assert provider.name == EmbeddingProviderName.JINA_AI


def test_provider_rejects_a_model_id_with_no_provider_prefix(monkeypatch):
    """A bare model name is refused at construction rather than embedded
    under a guessed label: the label identifies which vector space a
    stored embedding belongs to, so a wrong one is unrecoverable."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "embedding_model", "bge-m3")

    with pytest.raises(ValueError, match="no recognized provider prefix"):
        GatewayEmbeddingProvider(gateway=GatewayDouble())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TEST 2 — the correct BGE-M3 model is requested
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_requests_the_configured_bge_m3_model():
    from app.core.config import settings

    gateway = GatewayDouble(vectors=[_vector()])
    provider = GatewayEmbeddingProvider(gateway=gateway)  # type: ignore[arg-type]

    await provider.embed([TEST_TEXT])

    assert gateway.calls[0]["model"] == settings.embedding_model
    assert gateway.calls[0]["texts"] == [TEST_TEXT]


# ---------------------------------------------------------------------------
# TEST 3 — returned embedding has the expected dimension
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_returns_vectors_of_the_expected_dimension():
    gateway = GatewayDouble(vectors=[_vector(1024), _vector(1024, seed=0.02)])
    provider = GatewayEmbeddingProvider(gateway=gateway)  # type: ignore[arg-type]

    vectors = await provider.embed(["a", "b"])

    assert len(vectors) == 2
    assert all(len(v) == 1024 for v in vectors)


# ---------------------------------------------------------------------------
# TEST 4 — invalid embedding response is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_rejects_a_dimension_mismatch():
    """A model returning the wrong width must not silently populate a
    pgvector(1024) column with something that doesn't fit."""
    gateway = GatewayDouble(vectors=[_vector(512)])
    provider = GatewayEmbeddingProvider(gateway=gateway)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="1024"):
        await provider.embed([TEST_TEXT])


def test_gateway_rejects_inconsistent_batch_dimensions():
    """Gateway-level validation: a batch where vectors differ in width
    from each other must fail loudly, not silently."""
    from app.core.llm.gateway import LLMGateway

    with pytest.raises(Exception):  # LLMProviderError, exercised via the real method
        LLMGateway._to_embedding_vectors(
            type("R", (), {"data": [{"embedding": _vector(1024)}, {"embedding": _vector(512)}]})(),
            model="ollama/bge-m3",
            expected_count=2,
        )


def test_gateway_rejects_a_short_batch():
    """Fewer vectors than texts sent must fail loudly, not silently
    misalign chunk-to-vector pairing downstream."""
    from app.core.llm.gateway import LLMGateway, LLMProviderError

    with pytest.raises(LLMProviderError, match="Expected 2"):
        LLMGateway._to_embedding_vectors(
            type("R", (), {"data": [{"embedding": _vector(1024)}]})(),
            model="ollama/bge-m3",
            expected_count=2,
        )


# ---------------------------------------------------------------------------
# TEST 5 & 7 — failure preserves chunk content and marks status FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_failure_preserves_chunk_content_and_marks_failed(session, project):
    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.txt", content=TEST_TEXT.encode())
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    failing_gateway = GatewayDouble(raises=LLMConnectionError("connection refused"))
    embeddings = GatewayEmbeddingProvider(gateway=failing_gateway)  # type: ignore[arg-type]
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=FakeQwen(),  # type: ignore[arg-type]
        embeddings=embeddings,
    )
    await pipeline.process_asset(asset.id)

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    assert refreshed.processing_status is AssetProcessingStatus.COMPLETED, (
        "the deterministic pipeline must not be affected by an embedding failure"
    )

    chunks = await KnowledgeChunkRepository(session).list_by_project(project.id, asset_id=asset.id)
    assert len(chunks) > 0
    for chunk in chunks:
        # TEST 5: content preserved.
        assert chunk.content, "chunk content must survive an embedding failure"
        assert TEST_TEXT.split(".")[0] in " ".join(c.content for c in chunks)
        # TEST 7: status correctly reflects the failure, no fake vector.
        assert chunk.embedding_status is EmbeddingStatus.FAILED
        assert chunk.embedding is None

    await session.delete(asset)
    await session.commit()


# ---------------------------------------------------------------------------
# TEST 6 — successful embedding updates embedding status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_embedding_updates_status_and_stores_vector(session, project):
    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.txt", content=TEST_TEXT.encode())
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(vectors=[_vector()])
    embeddings = GatewayEmbeddingProvider(gateway=gateway)  # type: ignore[arg-type]
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=FakeQwen(),  # type: ignore[arg-type]
        embeddings=embeddings,
    )
    await pipeline.process_asset(asset.id)

    chunks = await KnowledgeChunkRepository(session).list_by_project(project.id, asset_id=asset.id)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.embedding_status is EmbeddingStatus.COMPLETED
        assert chunk.embedding_provider is EmbeddingProviderName.LOCAL
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 1024

    await session.delete(asset)
    await session.commit()


@pytest.mark.asyncio
async def test_qwen_and_embedding_steps_are_independent(session, project, monkeypatch):
    """Embedding must complete regardless of AI understanding -- Sprint
    16 Phase 8.11 Part D decoupled them further than the original
    Sprint 9B/9C "separate status fields" guarantee this test predates:
    understanding no longer even runs inline during `process_asset`, it
    is enqueued as its own Celery task (`workers.generate_ai_metadata`)
    once embedding has already committed. A real local-Ollama
    measurement (see `pipeline.py`'s module docstring) showed Ollama
    serializes requests, so the 18-sequential-call understanding step
    must never sit between "chunks exist" and "chunks are searchable".

    `.delay()` is stubbed, not exercised against the real broker/worker
    (matching `test_asset_service.py`'s identical convention for
    `process_uploaded_asset.delay`) -- this test asserts the pipeline
    *enqueues* understanding, not that understanding itself succeeds or
    fails, which is `test_document_understanding.py`'s concern.
    """
    from app.workers import tasks as tasks_module

    enqueued: list[str] = []
    monkeypatch.setattr(
        tasks_module.generate_ai_metadata, "delay", lambda asset_id: enqueued.append(asset_id)
    )

    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.txt", content=TEST_TEXT.encode())
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(vectors=[_vector()])
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=FakeQwen(),  # type: ignore[arg-type] -- would always fail if ever called
        embeddings=GatewayEmbeddingProvider(gateway=gateway),  # type: ignore[arg-type]
    )
    await pipeline.process_asset(asset.id)

    # Embedding completed without ever waiting on AI understanding.
    chunks = await KnowledgeChunkRepository(session).list_by_project(project.id, asset_id=asset.id)
    assert all(c.embedding_status is EmbeddingStatus.COMPLETED for c in chunks)

    # AI understanding was handed off as its own task, for this exact
    # asset, rather than skipped or run inline.
    assert enqueued == [str(asset.id)]

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    profile = AIProfile.model_validate(refreshed.ai_profile)
    assert profile.status.value == "pending"  # not yet run -- only enqueued

    await session.delete(asset)
    await session.commit()
