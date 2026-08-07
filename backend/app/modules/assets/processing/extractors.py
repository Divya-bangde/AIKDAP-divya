"""Text extraction framework.

Defines `TextExtractor`, the interface every content-type-specific
extractor implements, and `get_text_extractor`, a registry that
dispatches by MIME type. Only plain-text-like formats (txt, csv,
markdown, json) have a real extractor this sprint — decoding UTF-8
bytes requires no external library or AI model, so it's genuinely
implemented rather than stubbed.

Everything else (PDF, images, Office documents) raises
`ExtractionNotSupportedError` via `UnsupportedExtractor`. This is a
deliberate placeholder, not a lie: it's a known, expected gap until a
real parser or OCR backend is wired in, distinct from an extraction
that was attempted and failed.
"""

from abc import ABC, abstractmethod

_PLAIN_TEXT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/json",
    }
)


class ExtractionNotSupportedError(Exception):
    """Raised when no extractor is implemented yet for a given MIME type."""


class TextExtractor(ABC):
    """Abstract interface for pulling plain text out of raw file bytes."""

    @abstractmethod
    async def extract(self, content: bytes) -> str:
        """Return the plain-text content of a file's raw bytes."""


class PlainTextExtractor(TextExtractor):
    """Extracts text from already-textual formats (txt, csv, md, json)."""

    async def extract(self, content: bytes) -> str:
        return content.decode("utf-8", errors="replace")


class UnsupportedExtractor(TextExtractor):
    """Placeholder for formats with no real extractor yet.

    Covers PDF, images (would need OCR), and Office formats (docx/xlsx/
    pptx). Raises rather than silently returning empty or fabricated
    text, so the pipeline can record this as `UNSUPPORTED` — a known
    gap — rather than mistaking it for a genuine failure.
    """

    def __init__(self, mime_type: str) -> None:
        self._mime_type = mime_type

    async def extract(self, content: bytes) -> str:
        raise ExtractionNotSupportedError(
            f"No text extractor implemented yet for MIME type '{self._mime_type}'."
        )


def get_text_extractor(mime_type: str) -> TextExtractor:
    """Return the extractor for a given MIME type.

    Real extraction for additional formats (pypdf/pdfplumber for PDF,
    python-docx/openpyxl for Office formats, OCR for images) is future
    work; adding a backend means adding a branch here, not touching
    `pipeline.py` or anything upstream of it.
    """
    if mime_type in _PLAIN_TEXT_MIME_TYPES:
        return PlainTextExtractor()
    return UnsupportedExtractor(mime_type)
