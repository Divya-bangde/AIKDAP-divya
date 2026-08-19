"""Reusable AI profile structure stored in `Asset.ai_profile` (JSONB).

Every asset is created with a default `AIProfile` whose fields are all
empty/pending. As of Sprint 9B, `summary`/`keywords`/`entities`/
`topics`/`language`/`generated_by` are genuinely populated by local
Qwen document understanding (see
`app.modules.assets.processing.document_understanding`) when
extraction succeeds and Qwen is reachable; `status`/`error` record
whether that step ran, and why it didn't if it failed. `embedding_status`
is rolled up from the asset's chunks by
`AssetProcessingService._run_embedding` (Sprint 9I) once BGE-M3
embedding actually runs — before that it stays `PENDING`.
"""

import enum
import uuid

from pydantic import BaseModel, Field

from app.modules.assets.enums import EmbeddingStatus


class AIProfileStatus(str, enum.Enum):
    """Lifecycle of the AI-understanding step for one asset.

    Deliberately separate from `AssetProcessingStatus`: extraction and
    chunking (the deterministic, primary pipeline) can succeed even
    when this stays `FAILED`/`UNAVAILABLE` — raw extracted text must
    survive an AI failure, so a failed AI step must never be reported
    through the same status field that governs whether the asset's
    text was recovered at all.
    """

    #: Not yet attempted (default at asset creation, and while
    #: extraction itself hasn't completed).
    PENDING = "pending"
    #: Qwen produced and validated structured metadata.
    COMPLETED = "completed"
    #: Qwen was reached but its output could not be used (invalid
    #: JSON, empty extracted text, or an unsupported document).
    FAILED = "failed"
    #: Qwen/Ollama could not be reached at all (service down, model
    #: not installed, or the call timed out).
    UNAVAILABLE = "unavailable"


class AIProfile(BaseModel):
    """AI-derived metadata for an asset.

    `status`/`error` are stored as plain fields inside this existing
    JSONB-backed model — no new database column or migration — so a
    failed AI step is recorded without ever touching
    `Asset.processing_status`/`Asset.processing_error`, which describe
    the deterministic extract/chunk pipeline, not this one.
    """

    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    language: str | None = None
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    related_assets: list[uuid.UUID] = Field(default_factory=list)
    related_projects: list[uuid.UUID] = Field(default_factory=list)
    #: The model that produced `summary`/`keywords`/`entities`/`topics`
    #: (e.g. the configured `QWEN_MODEL`). `None` until a real
    #: generation succeeds — never set to a model that wasn't actually
    #: called.
    generated_by: str | None = None
    #: Only ever set to a value the model/pipeline actually produced.
    #: Qwen's structured output in this sprint does not include a
    #: confidence score, so this stays `None` rather than a fabricated
    #: number — the existing safe default.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: AIProfileStatus = AIProfileStatus.PENDING
    #: Human-readable reason when `status` is `FAILED`/`UNAVAILABLE`.
    error: str | None = None
