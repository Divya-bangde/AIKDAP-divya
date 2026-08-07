"""Data-access layer for the `KnowledgeChunk` model.

Contains only persistence operations; transaction boundaries (commit)
and ownership rules live in `service.py`.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge_base.models import KnowledgeChunk


class KnowledgeChunkRepository:
    """Encapsulates all direct database access for `KnowledgeChunk` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, chunk_id: uuid.UUID) -> KnowledgeChunk | None:
        """Fetch a chunk by primary key, or None if not found."""
        return await self._session.get(KnowledgeChunk, chunk_id)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        asset_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeChunk]:
        """List chunks in a project, optionally scoped to one asset, in
        stable reading order (by asset, then chunk position)."""
        stmt = select(KnowledgeChunk).where(KnowledgeChunk.project_id == project_id)
        if asset_id is not None:
            stmt = stmt.where(KnowledgeChunk.asset_id == asset_id)
        stmt = (
            stmt.order_by(KnowledgeChunk.asset_id, KnowledgeChunk.chunk_index)
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_asset(self, asset_id: uuid.UUID) -> None:
        """Delete all chunks belonging to an asset (used before reprocessing,
        so reprocessing is idempotent rather than appending duplicates)."""
        await self._session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.asset_id == asset_id)
        )

    async def bulk_create(self, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
        """Insert multiple chunk rows and flush to populate generated fields."""
        self._session.add_all(chunks)
        await self._session.flush()
        for chunk in chunks:
            await self._session.refresh(chunk)
        return chunks
