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
them yet. `generate_ai_metadata` (Sprint 9B, Qwen) and
`generate_embeddings` (Sprint 9C, BGE-M3) both run real local models
now; each shares its underlying service/provider with the inline
pipeline call in `AssetProcessingService.process_asset` rather than
reimplementing it — this file adds only the standalone-invocation
bridge.
"""

import asyncio
import functools
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from app.core.config import settings
from app.core.llm import LLMError
from app.core.logging.logger import get_logger
from app.database.session import async_session_factory
from app.modules.assets.ai_profile import AIProfile, AIProfileStatus
from app.modules.assets.enums import AssetProcessingStatus, EmbeddingStatus
from app.modules.assets.processing.document_understanding import (
    DocumentUnderstandingError,
    get_document_understanding_service,
)
from app.modules.assets.processing.extractors import (
    ExtractionNotSupportedError,
    get_text_extractor,
)
from app.modules.assets.processing.pipeline import get_asset_processing_service
from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import get_storage_provider
from app.modules.knowledge_base.embeddings import get_embedding_provider
from app.modules.knowledge_base.repository import KnowledgeChunkRepository
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


def _run_task_loop(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Drive one Celery task body to completion, then reset LiteLLM's
    global logging worker before this loop closes (Sprint 9J).

    The single choke point every task below runs through instead of a
    bare `asyncio.run(...)`, so the fix lives in exactly one place
    rather than being repeated at each of the six call sites. The
    reset itself is `reset_litellm_logging_worker_for_task_boundary`
    in `app.core.llm.gateway` — kept there rather than here so this
    module never imports `litellm` directly, preserving the
    containment invariant `test_litellm_is_imported_only_by_the_gateway`
    checks (see that function's docstring for the full root-cause
    explanation of what is being reset and why).
    """
    from app.core.llm.gateway import reset_litellm_logging_worker_for_task_boundary

    async def _wrapped() -> Any:
        try:
            return await coroutine
        finally:
            await reset_litellm_logging_worker_for_task_boundary()

    return asyncio.run(_wrapped())


@celery_app.task(name="workers.process_uploaded_asset", bind=True, max_retries=3, default_retry_delay=30)
@log_task_execution
def process_uploaded_asset(self, asset_id: str) -> dict[str, str]:
    """Run the full extract -> chunk -> (future) embed pipeline for one
    asset. This is the task actually enqueued after upload/reprocess."""
    try:
        _run_task_loop(_run_pipeline(uuid.UUID(asset_id)))
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
        text = _run_task_loop(_extract_text(uuid.UUID(asset_id)))
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
    """Run local Qwen document understanding for one asset in isolation.

    Standalone step for future composition (a Celery `chain()`, or a
    caller that wants to re-run just this stage) — the automatic
    pipeline (`process_uploaded_asset` -> `AssetProcessingService.
    process_asset`) already runs the same underlying
    `QwenDocumentUnderstandingService` inline after extraction
    succeeds. Both entry points call the one implementation; nothing
    is duplicated between them.

    Requires the asset to already have extracted text available (i.e.
    `processing_status` has reached at least `CHUNKING`/`COMPLETED`);
    this task does not run extraction itself.
    """
    try:
        result = _run_task_loop(_generate_ai_metadata(uuid.UUID(asset_id)))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return {"asset_id": asset_id, **result}


async def _generate_ai_metadata(asset_id: uuid.UUID) -> dict[str, str]:
    async with async_session_factory() as session:
        repository = AssetRepository(session)
        asset = await repository.get_by_id(asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found.")

        storage = get_storage_provider()
        content = await storage.read(asset.storage_path)
        extractor = get_text_extractor(asset.mime_type)
        text = await extractor.extract(content)

        profile = AIProfile.model_validate(asset.ai_profile or {})
        understanding = get_document_understanding_service()
        try:
            metadata = await understanding.analyze(text)
        except DocumentUnderstandingError as exc:
            profile.status = AIProfileStatus.FAILED
            profile.error = str(exc)
            status = "failed"
        except LLMError as exc:
            profile.status = AIProfileStatus.UNAVAILABLE
            profile.error = str(exc)
            status = "unavailable"
        else:
            profile.summary = metadata.summary
            profile.keywords = metadata.keywords
            profile.entities = metadata.entities
            profile.topics = metadata.topics
            profile.language = metadata.language
            profile.generated_by = settings.qwen_model
            profile.status = AIProfileStatus.COMPLETED
            profile.error = None
            status = "completed"

        asset.ai_profile = profile.model_dump(mode="json")
        await session.commit()
        return {"status": status}


@celery_app.task(name="workers.generate_embeddings", bind=True, max_retries=3, default_retry_delay=30)
@log_task_execution
def generate_embeddings(self, asset_id: str) -> dict[str, str]:
    """Generate BGE-M3 embeddings for one asset's existing knowledge
    chunks, in isolation.

    Standalone step for future composition — the automatic pipeline
    (`process_uploaded_asset` -> `AssetProcessingService.
    process_asset`) already runs the same `EmbeddingProvider.embed()`
    call inline, right after chunking. Both entry points call the one
    provider from `get_embedding_provider()`; nothing is duplicated.

    Requires the asset to already have chunks (i.e. extraction/chunking
    has already run); this task does not extract or chunk.
    """
    try:
        result = _run_task_loop(_generate_embeddings(uuid.UUID(asset_id)))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return {"asset_id": asset_id, **result}


async def _generate_embeddings(asset_id: uuid.UUID) -> dict[str, str]:
    async with async_session_factory() as session:
        asset = await AssetRepository(session).get_by_id(asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found.")

        chunks = await KnowledgeChunkRepository(session).list_by_project(
            asset.project_id, asset_id=asset_id
        )
        if not chunks:
            return {"status": "no_chunks", "chunk_count": "0"}

        provider = get_embedding_provider()
        for chunk in chunks:
            chunk.embedding_status = EmbeddingStatus.PROCESSING
        await session.commit()

        try:
            vectors = await provider.embed([chunk.content for chunk in chunks])
        except Exception as exc:
            for chunk in chunks:
                chunk.embedding_status = EmbeddingStatus.FAILED
            await session.commit()
            logger.warning(
                "generate_embeddings_failed",
                asset_id=str(asset_id),
                chunk_count=len(chunks),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return {"status": "failed", "chunk_count": str(len(chunks))}

        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_status = EmbeddingStatus.COMPLETED
            chunk.embedding_provider = provider.name
        await session.commit()
        return {"status": "completed", "chunk_count": str(len(chunks)), "provider": provider.name.value}


@celery_app.task(name="workers.update_processing_status", bind=True, max_retries=3, default_retry_delay=10)
@log_task_execution
def update_processing_status(self, asset_id: str, status: str, error: str | None = None) -> dict[str, str]:
    """Update an asset's `processing_status`/`processing_error` as a
    standalone step, outside the main pipeline — for a future task
    that reports progress without running the full
    `AssetProcessingService.process_asset` flow."""
    try:
        _run_task_loop(_update_status(uuid.UUID(asset_id), AssetProcessingStatus(status), error))
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
        _run_task_loop(_run_research(uuid.UUID(run_id)))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    return {"status": "ok", "run_id": run_id}


async def _run_research(run_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        await ResearchExecutionService(session).execute(run_id)
