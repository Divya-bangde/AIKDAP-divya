"""Storage abstraction for asset file persistence.

`StorageProvider` is the interface every backend implements. This
sprint ships `LocalStorageProvider` (filesystem-backed); future S3,
MinIO, or Azure Blob providers implement the same interface, so
`service.py` and `router.py` never depend on where bytes physically
live — only `get_storage_provider` changes.
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.core.config import settings


class StorageProvider(ABC):
    """Abstract interface for asset binary storage backends."""

    @abstractmethod
    async def save(self, *, project_id: uuid.UUID, filename: str, content: bytes) -> str:
        """Persist file content and return its backend-specific storage path/key."""

    @abstractmethod
    async def read(self, storage_path: str) -> bytes:
        """Read and return the full file content for a given storage path."""

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Delete the file at the given storage path, if it exists."""

    @abstractmethod
    def exists(self, storage_path: str) -> bool:
        """Return whether a file exists at the given storage path."""


def sanitize_filename(filename: str) -> str:
    """Strip directory components so a crafted filename can't escape the
    intended storage location (e.g. `../../etc/passwd`).

    Public so callers (e.g. `service.py`) can derive the *same* safe name
    used on disk before persisting it as `Asset.file_name` — otherwise the
    stored/displayed filename would diverge from the sanitized one
    actually used for the storage path.
    """
    name = Path(filename).name.strip()
    if not name or name in {".", ".."}:
        name = "file"
    return name


class LocalStorageProvider(StorageProvider):
    """Filesystem-backed storage provider rooted at `base_dir`.

    Files are stored under `<base_dir>/<project_id>/<uuid>_<filename>`.
    Blocking disk I/O is offloaded to a thread via `asyncio.to_thread`
    so it never blocks the event loop.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, storage_path: str) -> Path:
        """Resolve a stored relative path to an absolute path, rejecting
        any path that would escape the storage root."""
        resolved = (self._base_dir / storage_path).resolve()
        if resolved != self._base_dir and self._base_dir not in resolved.parents:
            raise ValueError("Resolved storage path escapes the storage root.")
        return resolved

    async def save(self, *, project_id: uuid.UUID, filename: str, content: bytes) -> str:
        safe_name = sanitize_filename(filename)
        relative_path = Path(str(project_id)) / f"{uuid.uuid4()}_{safe_name}"
        absolute_path = self._resolve(str(relative_path))
        await asyncio.to_thread(absolute_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(absolute_path.write_bytes, content)
        return relative_path.as_posix()

    async def read(self, storage_path: str) -> bytes:
        absolute_path = self._resolve(storage_path)
        return await asyncio.to_thread(absolute_path.read_bytes)

    async def delete(self, storage_path: str) -> None:
        absolute_path = self._resolve(storage_path)
        await asyncio.to_thread(absolute_path.unlink, True)  # missing_ok=True

    def exists(self, storage_path: str) -> bool:
        return self._resolve(storage_path).exists()


@lru_cache
def get_storage_provider() -> StorageProvider:
    """FastAPI dependency provider for the configured storage backend.

    Currently always returns `LocalStorageProvider`. Adding S3/MinIO/
    Azure later means adding a provider class here and branching on a
    settings-driven backend flag — `service.py` and `router.py` are
    unaffected since they only depend on the `StorageProvider` interface.
    """
    return LocalStorageProvider(base_dir=Path(settings.upload_dir))
