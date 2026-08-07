"""Upload validation: MIME type, extension, and file size.

Ownership validation (a user may only act on assets within their own
projects) is authorization logic, not file validation, and lives in
`service.py` alongside the rest of the module's business rules.
"""

from pathlib import Path

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/svg+xml",
    }
)

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".txt",
        ".csv",
        ".md",
        ".json",
        ".docx",
        ".xlsx",
        ".pptx",
        ".doc",
        ".xls",
        ".ppt",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
    }
)


class AssetValidationError(Exception):
    """Raised when an uploaded file fails MIME type, extension, or size checks."""


def validate_mime_type(mime_type: str | None) -> str:
    """Ensure the declared MIME type is permitted, returning it normalized."""
    resolved = (mime_type or "application/octet-stream").lower()
    if resolved not in ALLOWED_MIME_TYPES:
        raise AssetValidationError(f"MIME type '{resolved}' is not permitted.")
    return resolved


def validate_extension(file_name: str) -> str:
    """Ensure the file's extension is permitted, returning it lowercased."""
    extension = Path(file_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AssetValidationError(f"File extension '{extension}' is not permitted.")
    return extension


def validate_file_size(size_bytes: int, *, max_bytes: int) -> None:
    """Ensure the file is non-empty and does not exceed the configured maximum."""
    if size_bytes <= 0:
        raise AssetValidationError("Uploaded file is empty.")
    if size_bytes > max_bytes:
        raise AssetValidationError(
            f"File size ({size_bytes} bytes) exceeds the maximum of {max_bytes} bytes."
        )
