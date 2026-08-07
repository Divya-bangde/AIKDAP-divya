"""Asset processing pipeline orchestration.

Runs extract -> chunk -> (future) embed for one asset. This is the
only place that sequences those steps; `app.workers.tasks.
process_uploaded_asset` is a thin Celery bridge around
`AssetProcessingService.process_asset`, and `app.modules.assets.
router`'s manual reprocess endpoint enqueues the same Celery task — so
there is exactly one pipeline implementation, run either automatically
after upload or on demand.

Embedding is deliberately never invoked: chunks are created with
`embedding_status=PENDING` (see `app.modules.knowledge_base.service`)
for a future sprint's embedding worker to pick up.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging.logger import get_logger
from app.modules.assets.enums import AssetProcessingStatus
from app.modules.assets.processing.chunker import chunk_text
from app.modules.assets.processing.extractors import (
    ExtractionNotSupportedError,
    get_text_extractor,
)
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import StorageProvider
from app.modules.knowledge_base.service import KnowledgeBaseService

logger = get_logger(__name__)


class AssetProcessingService:
    """Runs the extract -> chunk -> (future) embed pipeline for one asset."""

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageProvider,
        *,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        self._session = session
        self._storage = storage
        self._assets = AssetRepository(session)
        self._knowledge_base = KnowledgeBaseService(session)
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

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

            chunks = chunk_text(
                text, chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap
            )
            await self._knowledge_base.replace_chunks_for_asset(
                project_id=asset.project_id, asset_id=asset.id, chunk_texts=chunks
            )

            asset.processing_status = AssetProcessingStatus.COMPLETED
            asset.processing_completed_at = datetime.now(timezone.utc)
            await self._session.commit()
            logger.info(
                "asset_processing_completed", asset_id=str(asset_id), chunk_count=len(chunks)
            )

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
