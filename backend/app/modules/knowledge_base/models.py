"""KnowledgeChunk ORM model — the atomic unit of the knowledge base.

Each chunk is a slice of text extracted and split from one asset.
`embedding_vector` is stored as JSONB (a plain list of floats) rather
than a native `vector` column: adding a real embedding provider means
adding the `pgvector` extension and migrating this column then,
without speculatively depending on it now.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel
from app.modules.assets.enums import EmbeddingStatus
from app.modules.knowledge_base.enums import EmbeddingProviderName


def _enum_values(enum_cls: type) -> list[str]:
    """Persist enum members by their `.value`, not their `.name` (see
    the identical helper in `app.modules.assets.models` for why)."""
    return [member.value for member in enum_cls]


class KnowledgeChunk(BaseModel):
    """A chunk of extracted text from an asset, pending (future) embedding."""

    __tablename__ = "knowledge_chunks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embedding_status: Mapped[EmbeddingStatus] = mapped_column(
        SQLEnum(
            EmbeddingStatus,
            name="kb_embedding_status_enum",
            native_enum=True,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=EmbeddingStatus.PENDING,
    )
    embedding_provider: Mapped[EmbeddingProviderName | None] = mapped_column(
        SQLEnum(
            EmbeddingProviderName,
            name="kb_embedding_provider_enum",
            native_enum=True,
            values_callable=_enum_values,
        ),
        nullable=True,
    )
    embedding_vector: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
