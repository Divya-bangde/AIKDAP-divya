"""Celery tasks for the asset processing pipeline and research execution.

Celery task bodies are synchronous by design — the default `prefork`
worker pool doesn't support native `async def` tasks. Every task here
is a thin bridge that opens a fresh event loop via `asyncio.run()` to
drive the async DB/service layer for the duration of one task, then
returns. All real business logic lives in the existing processing
services (`AssetProcessingService`, `AssetRepository`,
`get_text_extractor`, `get_embedding_provider`) — nothing here
reimplements them; each task's body is a call into one.

`process_uploaded_asset` is the one actually wired up (enqueued by
`AssetService.upload` and `POST /assets/{id}/process`) and is the only
task whose failure path is "primary" — `AssetProcessingService`
records failures on the asset's own `processing_status`/
`processing_error` rather than raising, so this task's own retry
handling is a safety net for infrastructure failures, not the main
error-reporting mechanism.

`extract_document_text`, `generate_ai_metadata`, `generate_embeddings`,
and `update_processing_status` are standalone, individually invokable
steps — useful for future composition (e.g. a Celery `chain()`, or a
future Planner triggering just one phase) even though nothing calls
them yet. `generate_ai_metadata` and `generate_embeddings` are honest
placeholders: no LLM or embedding provider is called, matching the
"do not implement real OCR or real embedding providers" constraint.
"""

import asyncio
import functools
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from app.core.logging.logger import get_logger
from app.database.session import async_session_factory
from app.modules.assets.enums import AssetProcessingStatus
from app.modules.assets.processing.extractors import (
    ExtractionNotSupportedError,
    get_text_extractor,
)
from app.modules.assets.processing.pipeline import get_asset_processing_service
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.knowledge_base.embeddings import get_embedding_provider
from app.modules.research.service import ResearchExecutionService
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


def log_task_execution(func: _F) -> _F:
    """Standardize the four log events every task must emit (started,
    completed, failed, execution time), so individual tasks only
    contain their own logic, not logging boilerplate.

    Expects to wrap a `bind=True` task body (`self` is the Celery
    `Task` instance, giving access to `self.name`/`self.request.id`).
    Re-raises on failure — logging here never swallows the exception,
    since Celery's own retry/failure bookkeeping depends on it
    propagating.

    `target_id` is the task's first positional argument by convention:
    the asset id for pipeline tasks, the run id for research execution.
    """

    @functools.wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        logger.info(
            "task_started", task=self.name, task_id=self.request.id, target_id=args[0] if args else None
        )
        try:
            result = func(self, *args, **kwargs)
        except Exception as exc:
            logger.error(
                "task_failed",
                task=self.name,
                task_id=self.request.id,
                duration_seconds=round(time.monotonic() - start, 3),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        logger.info(
            "task_completed",
            task=self.name,
            task_id=self.request.id,
            duration_seconds=round(time.monotonic() - start, 3),
        )
        return result

    return wrapper  # type: ignore[return-value]


@celery_app.task(name="workers.process_uploaded_asset", bind=True, max_retries=3, default_retry_delay=30)
@log_task_execution
def process_uploaded_asset(self, asset_id: str) -> dict[str, str]:
    """Run the full extract -> chunk -> (future) embed pipeline for one
    asset. This is the task actually enqueued after upload/reprocess."""
    try:
        asyncio.run(_run_pipeline(uuid.UUID(asset_id)))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return {"status": "ok", "asset_id": asset_id}


async def _run_pipeline(asset_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        storage = get_storage_provider()
        service = get_asset_processing_service(session, storage)
        await service.process_asset(asset_id)


@celery_app.task(name="workers.extract_document_text", bind=True, max_retries=3, default_retry_delay=30)
@log_task_execution
def extract_document_text(self, asset_id: str) -> dict[str, str | int]:
    """Extract raw text for one asset in isolation, without running
    chunking or touching `processing_status`. A standalone step for
    future composition; `process_uploaded_asset` runs the same
    extractor internally as part of the full pipeline today."""
    try:
        text = asyncio.run(_extract_text(uuid.UUID(asset_id)))
    except ExtractionNotSupportedError as exc:
        # Not retried: an unsupported MIME type won't become supported
        # by waiting, unlike a transient DB/network failure.
        logger.info("extract_document_text_unsupported", asset_id=asset_id, reason=str(exc))
        return {"status": "unsupported", "asset_id": asset_id, "reason": str(exc)}
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return {"status": "ok", "asset_id": asset_id, "character_count": len(text)}


async def _extract_text(asset_id: uuid.UUID) -> str:
    async with async_session_factory() as session:
        asset = await AssetRepository(session).get_by_id(asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found.")
        storage = get_storage_provider()
        content = await storage.read(asset.storage_path)
        extractor = get_text_extractor(asset.mime_type)
        return await extractor.extract(content)


@celery_app.task(name="workers.generate_ai_metadata", bind=True, max_retries=3, default_retry_delay=30)
@log_task_execution
def generate_ai_metadata(self, asset_id: str) -> dict[str, str]:
    """Placeholder for future AI-generated metadata (summary, keywords,
    entities, topics — see `app.modules.assets.ai_profile.AIProfile`).
    No LLM is called. Exists so a stable task name is available for a
    future sprint to implement against, and so a future scheduler can
    already reference it by name."""
    logger.info(
        "generate_ai_metadata_placeholder",
        asset_id=asset_id,
        reason="AI metadata generation is not implemented yet.",
    )
    return {"status": "not_implemented", "asset_id": asset_id}


@celery_app.task(name="workers.generate_embeddings", bind=True, max_retries=3, default_retry_delay=30)
@log_task_execution
def generate_embeddings(self, asset_id: str) -> dict[str, str]:
    """Placeholder for future embedding generation. Chunks produced by
    `process_uploaded_asset` sit at `embedding_status=PENDING`; this is
    the future home for calling `EmbeddingProvider.embed()` once a real
    provider replaces `NullEmbeddingProvider`."""
    provider = get_embedding_provider()
    logger.info(
        "generate_embeddings_placeholder",
        asset_id=asset_id,
        provider=provider.name.value,
        reason="No embedding provider is configured yet; chunks remain PENDING.",
    )
    return {"status": "not_implemented", "asset_id": asset_id, "provider": provider.name.value}


@celery_app.task(name="workers.update_processing_status", bind=True, max_retries=3, default_retry_delay=10)
@log_task_execution
def update_processing_status(self, asset_id: str, status: str, error: str | None = None) -> dict[str, str]:
    """Update an asset's `processing_status`/`processing_error` as a
    standalone step, outside the main pipeline — for a future task
    that reports progress without running the full
    `AssetProcessingService.process_asset` flow."""
    try:
        asyncio.run(_update_status(uuid.UUID(asset_id), AssetProcessingStatus(status), error))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return {"status": "ok", "asset_id": asset_id, "processing_status": status}


async def _update_status(asset_id: uuid.UUID, status: AssetProcessingStatus, error: str | None) -> None:
    async with async_session_factory() as session:
        asset = await AssetRepository(session).get_by_id(asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found.")
        asset.processing_status = status
        asset.processing_error = error
        await session.commit()


@celery_app.task(name="workers.execute_research_run", bind=True, max_retries=3, default_retry_delay=30)
@log_task_execution
def execute_research_run(self, run_id: str) -> dict[str, str]:
    """Execute the LangGraph research workflow for one research run.

    Enqueued by `ResearchService.start_run` so `POST /research/run` can
    return `201` without waiting for any part of the workflow. The same
    thin-bridge pattern as `process_uploaded_asset`: all logic lives in
    `ResearchExecutionService`, and the run row — not Celery's result
    backend — is the source of truth for whether it succeeded.

    Retries cover infrastructure failures only. A workflow failure is
    recorded on the run (`status=failed`, `error_message=...`) and does
    not raise, since retrying a deterministic planning/synthesis error
    would fail identically three more times.
    """
    try:
        asyncio.run(_run_research(uuid.UUID(run_id)))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return {"status": "ok", "run_id": run_id}


async def _run_research(run_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        await ResearchExecutionService(session).execute(run_id)
