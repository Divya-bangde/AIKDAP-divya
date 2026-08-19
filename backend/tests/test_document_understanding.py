"""Sprint 9B: local Qwen document-understanding unit tests.

Every test here is offline. `LLMGateway.generate` is replaced with a
mock (via a fake `GatewayDouble`, mirroring the `AsyncMock` pattern
`test_llm_gateway.py` uses for `litellm.acompletion`), so no test
starts Ollama, loads a model, or depends on this host having a GPU or
even Ollama installed. The real, unmocked connectivity proof is the
separate live validation run recorded in the sprint report.
"""

import uuid
from typing import Any

import pytest

from app.core.llm.gateway import (
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMResponse,
    LLMTimeoutError,
    provider_of,
)
from app.modules.assets.ai_profile import AIProfile, AIProfileStatus
from app.modules.assets.enums import AssetProcessingStatus, AssetSource, AssetStatus, AssetType
from app.modules.assets.models import Asset
from app.modules.assets.processing.document_understanding import (
    DocumentUnderstandingError,
    QwenDocumentMetadata,
    QwenDocumentUnderstandingService,
)
from app.modules.assets.processing.pipeline import AssetProcessingService
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import StorageProvider
from app.modules.knowledge_base.embeddings import EmbeddingProvider, EmbeddingProviderName

VALID_JSON = (
    '{"summary": "ABC Poultry produced 1.2 million tonnes of feed in FY2025.", '
    '"keywords": ["poultry feed", "FY2025"], '
    '"entities": ["ABC Poultry", "1.2 million tonnes"], '
    '"topics": ["agriculture"], "language": "en"}'
)

TEST_DOCUMENT = (
    "ABC Poultry produced 1.2 million tonnes of poultry feed in FY2025. "
    "The company operates in Maharashtra and Chhattisgarh. The major "
    "challenges identified are feed cost inflation and disease management. "
    "The report recommends improving feed efficiency and farm biosecurity."
)


class GatewayDouble:
    """A fake `LLMGateway` that records calls and returns a scripted result.

    Deliberately not `unittest.mock.AsyncMock` here: this double also
    needs to assert on keyword arguments in a way that reads clearly
    against `QwenDocumentUnderstandingService`'s own call signature,
    and to be swappable per test between "return a response" and
    "raise this exception" without repeating boilerplate.
    """

    def __init__(self, *, content: str | None = None, raises: Exception | None = None) -> None:
        self._content = content
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return LLMResponse(
            content=self._content or "",
            model=kwargs.get("model", ""),
            provider=provider_of(kwargs.get("model", "")),
            latency_ms=1,
        )


class FakeStorage(StorageProvider):
    """In-memory `StorageProvider`, keyed by the path `save()` returns."""

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


# ---------------------------------------------------------------------------
# TEST 1 — Ollama client (gateway) initializes from configuration
# ---------------------------------------------------------------------------


def test_gateway_ollama_settings_are_configured():
    """OLLAMA_BASE_URL/QWEN_MODEL must be real, non-empty configuration."""
    from app.core.config import settings

    assert settings.ollama_base_url
    assert settings.qwen_model
    assert settings.qwen_timeout > 0
    assert settings.qwen_max_tokens > 0


def test_provider_of_recognizes_ollama_chat_model_id():
    """Model ids route to the ollama provider via the same notation as Gemini."""
    assert provider_of("ollama_chat/qwen3.5:4b") == "ollama_chat"


# ---------------------------------------------------------------------------
# TEST 2 — the correct Qwen model is requested
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_requests_the_configured_qwen_model(monkeypatch):
    """The service must ask the gateway for `ollama_chat/<QWEN_MODEL>`."""
    from app.core.config import settings

    gateway = GatewayDouble(content=VALID_JSON)
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    await service.analyze(TEST_DOCUMENT)

    assert gateway.calls[0]["model"] == f"ollama_chat/{settings.qwen_model}"
    assert gateway.calls[0]["think"] == settings.qwen_think


@pytest.mark.asyncio
async def test_analyze_requests_structured_json_output():
    """The gateway call must ask for JSON-object structured output."""
    gateway = GatewayDouble(content=VALID_JSON)
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    await service.analyze(TEST_DOCUMENT)

    assert gateway.calls[0]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# TEST 3 — a valid structured Qwen response is parsed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_json_response_is_parsed_into_structured_metadata():
    """A well-formed response must produce a validated `QwenDocumentMetadata`."""
    gateway = GatewayDouble(content=VALID_JSON)
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    metadata = await service.analyze(TEST_DOCUMENT)

    assert isinstance(metadata, QwenDocumentMetadata)
    assert "1.2 million tonnes" in metadata.summary
    assert "poultry feed" in metadata.keywords
    assert "ABC Poultry" in metadata.entities
    assert metadata.language == "en"


@pytest.mark.asyncio
async def test_labelled_object_entities_are_coerced_to_plain_strings():
    """Regression: live Qwen 3.5 returned entities as
    `{"name": ..., "type": ...}` objects for the real acceptance-test
    document despite the prompt asking for bare strings. Confirmed
    against the real model before this coercion was added."""
    content = (
        '{"summary": "ABC Poultry report.", "keywords": ["feed"], '
        '"entities": [{"name": "ABC Poultry", "type": "Organization"}, '
        '{"name": "Maharashtra", "type": "Place"}], '
        '"topics": ["agriculture"], "language": "en"}'
    )
    gateway = GatewayDouble(content=content)
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    metadata = await service.analyze(TEST_DOCUMENT)

    assert metadata.entities == ["ABC Poultry", "Maharashtra"]


@pytest.mark.asyncio
async def test_bare_string_field_is_coerced_to_a_one_item_list():
    """A small model returning a bare string instead of an array must still parse."""
    content = (
        '{"summary": "Short doc.", "keywords": "single-keyword", '
        '"entities": [], "topics": [], "language": "en"}'
    )
    gateway = GatewayDouble(content=content)
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    metadata = await service.analyze(TEST_DOCUMENT)

    assert metadata.keywords == ["single-keyword"]


# ---------------------------------------------------------------------------
# TEST 4 — invalid JSON is handled safely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_json_raises_document_understanding_error():
    """Malformed JSON must not crash the pipeline or be silently accepted."""
    gateway = GatewayDouble(content="not json at all {{{")
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    with pytest.raises(DocumentUnderstandingError, match="valid JSON"):
        await service.analyze(TEST_DOCUMENT)


@pytest.mark.asyncio
async def test_json_missing_required_field_raises_document_understanding_error():
    """Well-formed JSON that doesn't match the schema must also fail clearly."""
    gateway = GatewayDouble(content='{"keywords": ["x"]}')  # no "summary"
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    with pytest.raises(DocumentUnderstandingError, match="schema"):
        await service.analyze(TEST_DOCUMENT)


# ---------------------------------------------------------------------------
# TEST 5 — empty document text is handled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_text_raises_without_calling_the_model():
    """No text means nothing to analyze — must fail before any network call."""
    gateway = GatewayDouble(content=VALID_JSON)
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    with pytest.raises(DocumentUnderstandingError, match="empty"):
        await service.analyze("   \n\t  ")

    assert gateway.calls == []


# ---------------------------------------------------------------------------
# Chunk-and-merge strategy for oversized documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_document_is_chunked_and_merged(monkeypatch):
    """Text over the configured budget must be split, analyzed per section, and merged."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_max_input_characters", 50)
    section_a = (
        '{"summary": "Section A summary.", "keywords": ["alpha"], '
        '"entities": ["Alpha Corp"], "topics": ["finance"], "language": "en"}'
    )
    section_b = (
        '{"summary": "Section B summary.", "keywords": ["beta", "alpha"], '
        '"entities": ["Beta Corp"], "topics": ["finance"], "language": "en"}'
    )

    class SequencedGateway(GatewayDouble):
        async def generate(self, **kwargs: Any) -> LLMResponse:
            self.calls.append(kwargs)
            content = section_a if len(self.calls) == 1 else section_b
            return LLMResponse(content=content, model=kwargs["model"], provider="ollama_chat", latency_ms=1)

    gateway = SequencedGateway()
    service = QwenDocumentUnderstandingService(gateway=gateway)  # type: ignore[arg-type]

    long_text = "First half of a long document. " * 5 + "Second half of a long document. " * 5
    metadata = await service.analyze(long_text)

    assert len(gateway.calls) >= 2, "must have made more than one call for oversized text"
    # Merged, de-duplicated (case-insensitively), order-preserving.
    assert metadata.keywords == ["alpha", "beta"]
    assert set(metadata.entities) == {"Alpha Corp", "Beta Corp"}
    assert "Section A summary." in metadata.summary
    assert "Section B summary." in metadata.summary


# ---------------------------------------------------------------------------
# TEST 6 — AI metadata is mapped into the existing Asset AI profile
# ---------------------------------------------------------------------------


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
        file_size=len(TEST_DOCUMENT),
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


@pytest.mark.asyncio
async def test_pipeline_maps_qwen_output_into_existing_ai_profile_fields(session, project):
    """A real `process_asset()` run must populate `Asset.ai_profile` in place —
    the existing structure, not a second metadata model."""
    storage = FakeStorage()
    storage_path = await storage.save(
        project_id=project.id, filename="poultry.txt", content=TEST_DOCUMENT.encode()
    )
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(content=VALID_JSON)
    pipeline = AssetProcessingService(
        session,
        storage,
        chunk_size=1000,
        chunk_overlap=100,
        understanding=QwenDocumentUnderstandingService(gateway=gateway),  # type: ignore[arg-type]
    )
    await pipeline.process_asset(asset.id)

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    profile = AIProfile.model_validate(refreshed.ai_profile)

    # Deterministic pipeline succeeded.
    assert refreshed.processing_status is AssetProcessingStatus.COMPLETED
    # Existing AIProfile fields populated, no parallel structure.
    assert "1.2 million tonnes" in profile.summary
    assert "poultry feed" in profile.keywords
    assert "ABC Poultry" in profile.entities
    assert profile.language == "en"
    assert profile.status is AIProfileStatus.COMPLETED
    # BGE-M3 embedding is real and unmocked here (only `understanding`
    # is a double) and genuinely succeeds against the local Ollama
    # endpoint, so the Sprint 9I rollup must reflect that completion —
    # not stay stuck at the pre-9I default of `pending` forever.
    assert profile.embedding_status.value == "completed"

    await session.delete(asset)
    await session.commit()


# ---------------------------------------------------------------------------
# TEST 7 — generated_by records the configured Qwen model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generated_by_records_the_configured_model(session, project):
    """`ai_profile.generated_by` must name the real configured model, on success only."""
    from app.core.config import settings

    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.txt", content=b"Some content.")
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(content=VALID_JSON)
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=QwenDocumentUnderstandingService(gateway=gateway),  # type: ignore[arg-type]
    )
    await pipeline.process_asset(asset.id)

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    profile = AIProfile.model_validate(refreshed.ai_profile)
    assert profile.generated_by == settings.qwen_model

    await session.delete(asset)
    await session.commit()


# ---------------------------------------------------------------------------
# TEST 8 — raw extracted text is preserved when Qwen fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raw_text_and_chunks_survive_when_qwen_is_unavailable(session, project):
    """Extraction/chunking success must not be undone by an AI failure."""
    from app.modules.knowledge_base.repository import KnowledgeChunkRepository

    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.txt", content=TEST_DOCUMENT.encode())
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(raises=LLMConnectionError("Could not reach the model provider: connection refused"))
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=QwenDocumentUnderstandingService(gateway=gateway),  # type: ignore[arg-type]
    )
    await pipeline.process_asset(asset.id)

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    # The deterministic pipeline's own outcome is untouched by the AI failure.
    assert refreshed.processing_status is AssetProcessingStatus.COMPLETED
    assert refreshed.processing_error is None

    chunks = await KnowledgeChunkRepository(session).list_by_project(project.id, asset_id=asset.id)
    assert len(chunks) > 0
    assert "1.2 million tonnes" in chunks[0].content or any(
        "1.2 million tonnes" in c.content for c in chunks
    )

    profile = AIProfile.model_validate(refreshed.ai_profile)
    assert profile.status is AIProfileStatus.UNAVAILABLE
    assert profile.generated_by is None
    assert profile.summary is None
    assert "connection" in profile.error.lower() or "reach" in profile.error.lower()

    await session.delete(asset)
    await session.commit()


@pytest.mark.asyncio
async def test_qwen_failure_does_not_fall_back_to_gemini(session, project):
    """No cloud model may be invoked as an invisible substitute for a failed Qwen.

    `QwenDocumentUnderstandingService` has no branch capable of naming
    any model other than the configured local one; this test asserts
    that directly (every call the service made targeted
    `ollama_chat/<QWEN_MODEL>`) rather than only checking the resulting
    status, so a future edit that *did* add a silent cloud fallback
    would fail this test even if the final status looked identical.
    """
    from app.core.config import settings

    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.txt", content=TEST_DOCUMENT.encode())
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(raises=LLMModelNotFoundError("model not found"))
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=QwenDocumentUnderstandingService(gateway=gateway),  # type: ignore[arg-type]
    )
    await pipeline.process_asset(asset.id)

    assert len(gateway.calls) == 1
    assert gateway.calls[0]["model"] == f"ollama_chat/{settings.qwen_model}"

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    profile = AIProfile.model_validate(refreshed.ai_profile)
    assert profile.status is AIProfileStatus.UNAVAILABLE
    assert profile.generated_by is None, "must not report a model that was never successfully called"

    await session.delete(asset)
    await session.commit()


# ---------------------------------------------------------------------------
# TEST 9 — Ollama timeout is handled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_is_reported_as_unavailable_not_failed(session, project):
    """A timeout is an availability problem, distinct from a bad response."""
    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.txt", content=TEST_DOCUMENT.encode())
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(raises=LLMTimeoutError("The model did not respond in time"))
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=QwenDocumentUnderstandingService(gateway=gateway),  # type: ignore[arg-type]
    )
    await pipeline.process_asset(asset.id)

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    assert refreshed.processing_status is AssetProcessingStatus.COMPLETED
    profile = AIProfile.model_validate(refreshed.ai_profile)
    assert profile.status is AIProfileStatus.UNAVAILABLE
    assert "respond in time" in profile.error

    await session.delete(asset)
    await session.commit()


# ---------------------------------------------------------------------------
# TEST 10 — unsupported document type is handled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_mime_type_never_reaches_qwen(session, project):
    """A MIME type with no extractor must skip the AI step entirely, not fail it."""
    storage = FakeStorage()
    storage_path = await storage.save(project_id=project.id, filename="doc.pdf", content=b"%PDF-fake")
    asset = _make_asset(
        project_id=project.id,
        owner_id=project.owner_id,
        storage_path=storage_path,
        mime_type="application/pdf",
        file_name="doc.pdf",
        file_extension=".pdf",
    )
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(content=VALID_JSON)
    pipeline = AssetProcessingService(
        session, storage, chunk_size=1000, chunk_overlap=100,
        understanding=QwenDocumentUnderstandingService(gateway=gateway),  # type: ignore[arg-type]
    )
    await pipeline.process_asset(asset.id)

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    assert refreshed.processing_status is AssetProcessingStatus.UNSUPPORTED
    assert gateway.calls == [], "Qwen must never be called when extraction is unsupported"

    profile = AIProfile.model_validate(refreshed.ai_profile)
    assert profile.status is AIProfileStatus.PENDING, "AI step never attempted, not failed"

    await session.delete(asset)
    await session.commit()


# ---------------------------------------------------------------------------
# Error hierarchy sanity (model-not-found vs connection vs timeout)
# ---------------------------------------------------------------------------


def test_ollama_error_types_are_distinguishable():
    """The three Ollama-relevant failure modes are separate exception types."""
    assert issubclass(LLMConnectionError, Exception)
    assert issubclass(LLMModelNotFoundError, Exception)
    assert issubclass(LLMTimeoutError, Exception)
    assert LLMConnectionError is not LLMModelNotFoundError
    assert LLMModelNotFoundError is not LLMTimeoutError


# ---------------------------------------------------------------------------
# Sprint 9I: asset.ai_profile.embedding_status rollup
#
# Root cause of the bug this section guards: `_run_embedding` always
# updated each `KnowledgeChunk.embedding_status`, but never wrote
# anything back to `Asset.ai_profile.embedding_status` — a leftover
# default from before BGE-M3 was wired in. `GET /assets/{id}` reported
# `pending` forever, even for an asset whose chunks had genuinely
# finished embedding, confirmed live (real chunks with
# `embedding_status=completed`, `dimension=1024` in the database,
# while the same asset's API response still said `pending`).
# ---------------------------------------------------------------------------


class _FailingEmbeddingProvider(EmbeddingProvider):
    """Always raises, so the failure branch of `_run_embedding` runs."""

    @property
    def name(self) -> EmbeddingProviderName:
        return EmbeddingProviderName.LOCAL

    @property
    def dimensions(self) -> int:
        return 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMConnectionError("embedding backend unreachable (simulated)")


@pytest.mark.asyncio
async def test_a_failed_embedding_is_rolled_up_onto_the_asset_profile(session, project):
    """Every chunk `FAILED` must be visible at the asset level too, not
    just the default `pending` that was never distinguishable from
    'never attempted'."""
    storage = FakeStorage()
    storage_path = await storage.save(
        project_id=project.id, filename="poultry.txt", content=TEST_DOCUMENT.encode()
    )
    asset = _make_asset(project_id=project.id, owner_id=project.owner_id, storage_path=storage_path)
    session.add(asset)
    await session.flush()
    await session.commit()

    gateway = GatewayDouble(content=VALID_JSON)
    pipeline = AssetProcessingService(
        session,
        storage,
        chunk_size=1000,
        chunk_overlap=100,
        understanding=QwenDocumentUnderstandingService(gateway=gateway),  # type: ignore[arg-type]
        embeddings=_FailingEmbeddingProvider(),
    )
    await pipeline.process_asset(asset.id)

    refreshed = await AssetRepository(session).get_by_id(asset.id)
    profile = AIProfile.model_validate(refreshed.ai_profile)

    # The deterministic pipeline and Qwen step are unaffected...
    assert refreshed.processing_status is AssetProcessingStatus.COMPLETED
    assert profile.status is AIProfileStatus.COMPLETED
    # ...but the embedding rollup must say what actually happened, and
    # never fabricate a vector or a success it did not achieve.
    assert profile.embedding_status.value == "failed"

    await session.delete(asset)
    await session.commit()
