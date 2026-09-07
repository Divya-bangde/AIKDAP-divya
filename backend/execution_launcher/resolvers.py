"""`InputResolver` implementations.

`StaticInputResolver` is a typed, in-memory test double (Phase 7B.3).
`ProductionInputResolver` (Phase 7B.4) is the real one: owner -> project ->
asset authorization against the actual database, via the exact repository
classes `experiment_service.py` already uses for the same ownership checks
(`AssetRepository`, `ProjectRepository`), then a trusted-metadata-only
filesystem resolution via the existing `LocalStorageProvider._resolve()`
path-traversal guard. No new ORM layer, no new path-resolution logic, no
Docker, no subprocess.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.repository import AssetRepository
from app.modules.assets.storage import LocalStorageProvider, get_storage_provider, sanitize_filename
from app.modules.projects.repository import ProjectRepository
from execution_launcher.models import InputResolutionError, ResolvedInput


@dataclass(frozen=True)
class _FixtureAsset:
    """One entry in a `StaticInputResolver`'s fixture table."""

    owner_id: uuid.UUID
    project_id: uuid.UUID
    host_path: str
    mount_name: str
    exists: bool = True
    is_symlink: bool = False
    is_regular_file: bool = True


@dataclass
class StaticInputResolver:
    """A fixture-driven `InputResolver` for tests only.

    Every failure mode an eventual real resolver must enforce is
    reproducible here by shaping the fixture table: wrong owner/project
    (unauthorized), `exists=False` (missing), `is_symlink=True`, or
    `is_regular_file=False`.
    """

    _assets: dict[uuid.UUID, _FixtureAsset] = field(default_factory=dict)

    def register(
        self,
        asset_id: uuid.UUID,
        *,
        owner_id: uuid.UUID,
        project_id: uuid.UUID,
        host_path: str,
        mount_name: str,
        exists: bool = True,
        is_symlink: bool = False,
        is_regular_file: bool = True,
    ) -> None:
        self._assets[asset_id] = _FixtureAsset(
            owner_id=owner_id,
            project_id=project_id,
            host_path=host_path,
            mount_name=mount_name,
            exists=exists,
            is_symlink=is_symlink,
            is_regular_file=is_regular_file,
        )

    async def resolve(
        self, *, owner_id: uuid.UUID, project_id: uuid.UUID, asset_id: uuid.UUID
    ) -> ResolvedInput:
        # ponytail: no I/O to await -- async only to satisfy InputResolver
        # (Phase 7B.6), matching the one real (DB-backed) implementation.
        asset = self._assets.get(asset_id)
        if asset is None:
            raise InputResolutionError(f"asset {asset_id} not found")
        if asset.owner_id != owner_id or asset.project_id != project_id:
            raise InputResolutionError(f"asset {asset_id} not authorized for this owner/project")
        if not asset.exists:
            raise InputResolutionError(f"asset {asset_id} does not exist")
        if asset.is_symlink:
            raise InputResolutionError(f"asset {asset_id} resolves to a symlink")
        if not asset.is_regular_file:
            raise InputResolutionError(f"asset {asset_id} is not a regular file")
        return ResolvedInput(
            asset_id=asset_id, host_path=asset.host_path, mount_name=asset.mount_name
        )


class ProductionInputResolver:
    """The real `InputResolver` (Phase 7B.4).

    owner_id -> project_id -> asset_id is re-checked fresh on every call,
    independently at each step (never a single joined query standing in
    for all three) -- the caller's three identifiers are the only thing
    trusted; everything else (project ownership, asset ownership, the
    backing file) is looked up and re-verified here. The final filesystem
    path comes ONLY from `asset.storage_path` (trusted DB metadata) run
    through the existing `LocalStorageProvider._resolve()` traversal
    guard -- there is no parameter through which a caller could supply a
    path directly.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._assets = AssetRepository(session)
        self._projects = ProjectRepository(session)
        self._storage = get_storage_provider()

    async def resolve(
        self, *, owner_id: uuid.UUID, project_id: uuid.UUID, asset_id: uuid.UUID
    ) -> ResolvedInput:
        project = await self._projects.get_by_id(project_id)
        if project is None or project.owner_id != owner_id:
            raise InputResolutionError(f"project {project_id} is not owned by {owner_id}")

        asset = await self._assets.get_by_id(asset_id)
        if asset is None or asset.project_id != project_id or asset.owner_id != owner_id:
            raise InputResolutionError(f"asset {asset_id} not found in project {project_id}")

        if not isinstance(self._storage, LocalStorageProvider):
            # ponytail: only LocalStorageProvider exists today; extend when
            # a second backend (S3/etc.) actually ships.
            raise InputResolutionError("execution input resolution requires LocalStorageProvider")

        # Leaf-level symlink check BEFORE resolving -- `_resolve()` calls
        # `.resolve()`, which follows a symlink to its target and would
        # otherwise make a symlinked leaf indistinguishable from a real
        # file. Checked on the unresolved joined path, never on
        # `resolved_path` below.
        raw_path = self._storage._base_dir / asset.storage_path
        if raw_path.is_symlink():
            raise InputResolutionError(f"asset {asset_id} backing path is a symlink")

        try:
            resolved_path = self._storage._resolve(asset.storage_path)
        except ValueError as exc:
            raise InputResolutionError(
                f"asset {asset_id} storage path escapes the storage root"
            ) from exc

        if not resolved_path.is_file():
            raise InputResolutionError(f"asset {asset_id} backing file is missing or not a regular file")

        return ResolvedInput(
            asset_id=asset_id,
            host_path=str(resolved_path),
            mount_name=sanitize_filename(asset.file_name),
        )
