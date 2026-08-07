"""Enumerations for the assets module."""

import enum


class AssetType(str, enum.Enum):
    """The kind of content an asset represents."""

    DOCUMENT = "document"
    DATASET = "dataset"
    REPORT = "report"
    SUMMARY = "summary"
    CHART = "chart"
    PRESENTATION = "presentation"
    IMAGE = "image"
    NOTE = "note"
    WORKFLOW_OUTPUT = "workflow_output"
    OTHER = "other"


class AssetStatus(str, enum.Enum):
    """Lifecycle state of an asset."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class AssetSource(str, enum.Enum):
    """How an asset came to exist in the platform."""

    UPLOAD = "upload"
    GENERATED = "generated"
    IMPORTED = "imported"


class EmbeddingStatus(str, enum.Enum):
    """Status of the (future) embedding-generation pipeline for an asset
    or knowledge chunk. Reused by `app.modules.knowledge_base` rather
    than duplicated, since it's the same underlying concept."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class AssetProcessingStatus(str, enum.Enum):
    """State of the extract -> chunk -> (future) embed pipeline for an
    asset. Distinct from `AssetStatus`, which tracks lifecycle
    (active/archived), not pipeline progress.

    `UNSUPPORTED` is a deliberate non-error terminal state: it means no
    extractor is implemented yet for the asset's MIME type (a known,
    expected gap), as opposed to `FAILED`, which means something broke
    while processing a MIME type we do support.
    """

    PENDING = "pending"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
