"""Reusable AI profile structure stored in `Asset.ai_profile` (JSONB).

Every asset is created with a default `AIProfile` whose fields are all
empty/pending. Populating them — summarization, keyword/entity/topic
extraction, embeddings, cross-asset relations — is explicitly out of
scope for this sprint and left for future work (see module docstring
in `service.py`). No embeddings, LangGraph, RAG, or agent logic exists
here; this is purely the placeholder schema they will eventually write
into.
"""

import uuid

from pydantic import BaseModel, Field

from app.modules.assets.enums import EmbeddingStatus


class AIProfile(BaseModel):
    """AI-derived metadata for an asset, populated by future sprints."""

    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    language: str | None = None
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    related_assets: list[uuid.UUID] = Field(default_factory=list)
    related_projects: list[uuid.UUID] = Field(default_factory=list)
    generated_by: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
