"""Asset processing pipeline orchestration.

Runs extract -> chunk -> AI understanding -> embed for one asset. This
is the only place that sequences those steps; `app.workers.
tasks.process_uploaded_asset` is a thin Celery bridge around
`AssetProcessingService.process_asset`, and `app.modules.assets.
router`'s manual reprocess endpoint enqueues the same Celery task — so
there is exactly one pipeline implementation, run either automatically
after upload or on demand.

AI document understanding (Sprint 9B, local Qwen through Ollama) and
embedding generation (Sprint 9C, local BGE-M3 through Ollama) are both
best-effort and strictly non-fatal to the deterministic pipeline:
neither failure changes `processing_status`/`processing_error`, and
neither discards the extracted text/chunks already persisted. See
`AIProfileStatus` (Qwen) and `EmbeddingStatus` (BGE-M3) for why each is
tracked on its own field rather than through the asset's own status.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm import LLMError
from app.core.logging.logger import get_logger
from app.modules.assets.ai_profile import AIProfile, AIProfileStatus
from app.modules.assets.enums import AssetProcessingStatus, EmbeddingStatus
from app.modules.assets.models import Asset
from app.modules.assets.processing.chunker import chunk_text
from app.modules.assets.processing.document_understanding import (
    DocumentUnderstandingError,
    QwenDocumentUnderstandingService,
    get_document_understanding_service,
)
from app.modules.assets.processing.extractors import (
    ExtractionNotSupportedError,
    get_text_extractor,
)
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import StorageProvider
from app.modules.knowledge_base.embeddings import EmbeddingProvider, get_embedding_provider
from app.modules.knowledge_base.models import KnowledgeChunk
from app.modules.knowledge_base.service import KnowledgeBaseService

logger = get_logger(__name__)


class AssetProcessingService:
    """Runs the extract -> chunk -> AI understanding -> (future) embed
    pipeline for one asset."""

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageProvider,
        *,
        chunk_size: int,
        chunk_overlap: int,
        understanding: QwenDocumentUnderstandingService | None = None,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._assets = AssetRepository(session)
        self._knowledge_base = KnowledgeBaseService(session)
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._understanding = understanding or get_document_understanding_service()
        self._embeddings = embeddings or get_embedding_provider()

    async def process_asset(self, asset_id: uuid.UUID) -> None:
        """Extract, chunk, and store knowledge chunks for one asset.

        Idempotent: rerunning replaces any chunks from a previous run.
        Never raises — failures are recorded on the asset's
        `processing_status`/`processing_error` rather than propagated,
        since this is the primary failure-reporting mechanism for a
        background job (visible via `GET /assets/{id}`, not just
        buried in a task queue's result backend).
        """
        asset = await self._assets.get_by_id(asset_id)
        if asset is None:
            logger.warning("asset_processing_asset_missing", asset_id=str(asset_id))
            return

        asset.processing_status = AssetProcessingStatus.EXTRACTING
        asset.processing_started_at = datetime.now(timezone.utc)
        asset.processing_error = None
        await self._session.commit()

        try:
            content = await self._storage.read(asset.storage_path)
            extractor = get_text_extractor(asset.mime_type)
            text = await extractor.extract(content)

            asset.processing_status = AssetProcessingStatus.CHUNKING
            await self._session.commit()

            chunk_texts = chunk_text(
                text, chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap
            )
            chunks = await self._knowledge_base.replace_chunks_for_asset(
                project_id=asset.project_id, asset_id=asset.id, chunk_texts=chunk_texts
            )

            asset.processing_status = AssetProcessingStatus.COMPLETED
            asset.processing_completed_at = datetime.now(timezone.utc)
            await self._session.commit()
            logger.info(
                "asset_processing_completed", asset_id=str(asset_id), chunk_count=len(chunk_texts)
            )

            # Best-effort from here: the deterministic pipeline already
            # succeeded and `processing_status` is final. Neither the
            # Qwen nor the embedding step below can change it — only
            # `ai_profile` / each chunk's own `embedding_status`.
            await self._run_ai_understanding(asset, text)
            await self._run_embedding(asset, chunks)

        except ExtractionNotSupportedError as exc:
            asset.processing_status = AssetProcessingStatus.UNSUPPORTED
            asset.processing_error = str(exc)
            asset.processing_completed_at = datetime.now(timezone.utc)
            await self._session.commit()
            logger.info("asset_processing_unsupported", asset_id=str(asset_id), reason=str(exc))

        except Exception as exc:  # noqa: BLE001 - recorded on the asset, not swallowed
            asset.processing_status = AssetProcessingStatus.FAILED
            asset.processing_error = str(exc)
            asset.processing_completed_at = datetime.now(timezone.utc)
            await self._session.commit()
            logger.error("asset_processing_failed", asset_id=str(asset_id), error=str(exc))

    async def _run_ai_understanding(self, asset: Asset, text: str) -> None:
        """Best-effort local AI document understanding via Qwen/Ollama.

        Never raises and never falls back to a cloud model: a failure
        here is reported on `ai_profile.status`/`ai_profile.error`, not
        masked by silently calling Gemini (Sprint 9A's cloud gateway).
        The two failure branches below distinguish, per Sprint 9B's
        requirements, "Qwen answered but the answer was unusable"
        (`DocumentUnderstandingError` — empty text, invalid JSON,
        schema mismatch) from "Qwen/Ollama could not be reached at
        all" (`LLMError` — service down, model not installed, timeout).
        """
        profile = AIProfile.model_validate(asset.ai_profile or {})
        try:
            metadata = await self._understanding.analyze(text)
        except DocumentUnderstandingError as exc:
            profile.status = AIProfileStatus.FAILED
            profile.error = str(exc)
            logger.warning(
                "asset_ai_understanding_failed", asset_id=str(asset.id), reason=str(exc)
            )
        except LLMError as exc:
            profile.status = AIProfileStatus.UNAVAILABLE
            profile.error = str(exc)
            logger.warning(
                "asset_ai_understanding_unavailable",
                asset_id=str(asset.id),
                error_type=type(exc).__name__,
                reason=str(exc),
            )
        else:
            profile.summary = metadata.summary
            profile.keywords = metadata.keywords
            profile.entities = metadata.entities
            profile.topics = metadata.topics
            profile.language = metadata.language
            profile.generated_by = settings.qwen_model
            profile.status = AIProfileStatus.COMPLETED
            profile.error = None
            logger.info(
                "asset_ai_understanding_completed",
                asset_id=str(asset.id),
                generated_by=settings.qwen_model,
                keyword_count=len(metadata.keywords),
                entity_count=len(metadata.entities),
            )

        asset.ai_profile = profile.model_dump(mode="json")
        await self._session.commit()

    async def _run_embedding(self, asset: Asset, chunks: list[KnowledgeChunk]) -> None:
        """Best-effort embedding generation for one asset's chunks.

        One batch call for all of an asset's chunks (`embed_documents`
        semantics, not one round trip per chunk) — matches the
        `EmbeddingProvider.embed(texts: list[str])` interface Sprint 6
        already defined. Never raises and never fabricates a vector:
        a failure marks every chunk `FAILED` with a recorded reason,
        leaving `content` (already committed above) untouched.

        Sprint 9I: also rolls the outcome up onto
        `asset.ai_profile.embedding_status`. Per-chunk status on
        `KnowledgeChunk` has always been the retrieval-time source of
        truth and this fix does not change that — but the asset-level
        field existed in the API response and was never written by any
        code path (a leftover default from before embedding was wired
        in), so `GET /assets/{id}` reported `pending` forever even
        after every chunk genuinely completed. Read fresh from
        `asset.ai_profile` rather than trusting a stale local variable,
        since `_run_ai_understanding` above may have just written to it.
        """
        if not chunks:
            return

        for chunk in chunks:
            chunk.embedding_status = EmbeddingStatus.PROCESSING
        await self._session.commit()

        try:
            vectors = await self._embeddings.embed([chunk.content for chunk in chunks])
        except Exception as exc:  # noqa: BLE001 - recorded per chunk, not swallowed
            for chunk in chunks:
                chunk.embedding_status = EmbeddingStatus.FAILED
            profile = AIProfile.model_validate(asset.ai_profile or {})
            profile.embedding_status = EmbeddingStatus.FAILED
            asset.ai_profile = profile.model_dump(mode="json")
            await self._session.commit()
            logger.warning(
                "asset_embedding_failed",
                asset_id=str(chunks[0].asset_id),
                chunk_count=len(chunks),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return

        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_status = EmbeddingStatus.COMPLETED
            chunk.embedding_provider = self._embeddings.name
        profile = AIProfile.model_validate(asset.ai_profile or {})
        profile.embedding_status = EmbeddingStatus.COMPLETED
        asset.ai_profile = profile.model_dump(mode="json")
        await self._session.commit()
        logger.info(
            "asset_embedding_completed",
            asset_id=str(chunks[0].asset_id),
            chunk_count=len(chunks),
            provider=self._embeddings.name.value,
            dimension=self._embeddings.dimensions,
        )


def get_asset_processing_service(
    session: AsyncSession, storage: StorageProvider
) -> AssetProcessingService:
    """Factory for `AssetProcessingService`, used by the Celery bridge
    in `app.workers.tasks` (not a FastAPI route dependency, since
    Celery tasks run outside the request/response cycle)."""
    return AssetProcessingService(
        session,
        storage,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
