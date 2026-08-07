"""Pydantic v2 response schemas for the knowledge base module.

There are no create/update request schemas: chunks are produced only
by the asset processing pipeline, never authored directly by API
clients, so the router exposes read-only endpoints.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.assets.enums import EmbeddingStatus
from app.modules.knowledge_base.enums import EmbeddingProviderName


class KnowledgeChunkRead(BaseModel):
    """Public representation of a knowledge chunk.

    `embedding_vector` is intentionally omitted — it's large, not
    generated yet, and not useful to typical API consumers browsing
    the knowledge base.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    asset_id: uuid.UUID
    chunk_index: int
    content: str
    token_count: int | None
    embedding_status: EmbeddingStatus
    embedding_provider: EmbeddingProviderName | None
    created_at: datetime
    updated_at: datetime
