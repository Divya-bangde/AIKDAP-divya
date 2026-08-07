"""Business logic for browsing the knowledge base and (internally)
writing chunks produced by the asset processing pipeline.

Ownership is enforced transitively via the project a chunk belongs to,
matching every other module: "exists but not yours" and "doesn't
exist" both surface as `KnowledgeChunkNotFoundError`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.enums import EmbeddingStatus
from app.modules.knowledge_base.models import KnowledgeChunk
from app.modules.knowledge_base.repository import KnowledgeChunkRepository
from app.modules.projects.repository import ProjectRepository


class KnowledgeChunkNotFoundError(Exception):
    """Raised when a chunk does not exist or is not owned by the caller."""


class ProjectAccessDeniedError(Exception):
    """Raised when the caller does not own the project being queried."""


class KnowledgeBaseService:
    """Coordinates knowledge chunk retrieval, listing, and (re)population."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = KnowledgeChunkRepository(session)
        self._projects = ProjectRepository(session)

    async def _ensure_project_owned(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> None:
        project = await self._projects.get_by_id(project_id)
        if project is None or project.owner_id != owner_id:
            raise ProjectAccessDeniedError(project_id)

    async def list_for_owner(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        asset_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeChunk]:
        """List knowledge chunks in a project owned by the given user."""
        await self._ensure_project_owned(owner_id, project_id)
        return await self._repository.list_by_project(
            project_id, asset_id=asset_id, skip=skip, limit=limit
        )

    async def get_owned(self, owner_id: uuid.UUID, chunk_id: uuid.UUID) -> KnowledgeChunk:
        """Fetch a chunk, ensuring its project belongs to the given user."""
        chunk = await self._repository.get_by_id(chunk_id)
        if chunk is None:
            raise KnowledgeChunkNotFoundError(chunk_id)
        project = await self._projects.get_by_id(chunk.project_id)
        if project is None or project.owner_id != owner_id:
            raise KnowledgeChunkNotFoundError(chunk_id)
        return chunk

    async def replace_chunks_for_asset(
        self,
        *,
        project_id: uuid.UUID,
        asset_id: uuid.UUID,
        chunk_texts: list[str],
    ) -> list[KnowledgeChunk]:
        """Replace all chunks for an asset with a freshly extracted set.

        Internal API used by the processing pipeline (not exposed via
        the public router). Deletes any chunks from a prior run first,
        so reprocessing an asset is idempotent rather than accumulating
        duplicates.
        """
        await self._repository.delete_by_asset(asset_id)
        chunks = [
            KnowledgeChunk(
                project_id=project_id,
                asset_id=asset_id,
                chunk_index=index,
                content=text,
                embedding_status=EmbeddingStatus.PENDING,
            )
            for index, text in enumerate(chunk_texts)
        ]
        created = await self._repository.bulk_create(chunks)
        await self._session.commit()
        return created
