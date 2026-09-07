"""Deterministic text chunking for the knowledge base pipeline.

Pure string manipulation — no AI/ML model involved — so unlike
extraction and embeddings, this is fully implemented rather than a
placeholder.
"""

import re
from dataclasses import dataclass

from app.modules.assets.processing.extractors import ExtractedDocument


@dataclass(frozen=True)
class ProvenancedChunk:
    """One chunk of text plus the provenance of the extracted unit it
    came from. A chunk never spans two units (see `chunk_document`), so
    this locator is unambiguous — a chunk from a PDF's page 3 is never
    partly page 3, partly page 4."""

    text: str
    page_number: int | None = None
    sheet_name: str | None = None
    section: str | None = None


def chunk_document(
    document: ExtractedDocument, *, chunk_size: int = 1000, chunk_overlap: int = 100
) -> list[ProvenancedChunk]:
    """Chunk each extracted unit independently, carrying its provenance
    onto every resulting chunk.

    Chunking per-unit rather than on the whole concatenated document is
    deliberate: it guarantees a chunk (and therefore a citation built
    from it) never straddles a page/sheet/slide boundary and ends up
    unable to say which one it actually came from. The cost is that a
    unit shorter than `chunk_size` (e.g. a short PDF page, a single
    spreadsheet row) becomes its own small chunk rather than being
    packed with a neighbor — accepted deliberately: unambiguous
    provenance is worth more here than perfectly uniform chunk sizes.
    """
    chunks: list[ProvenancedChunk] = []
    for unit in document.units:
        for piece in chunk_text(unit.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            chunks.append(
                ProvenancedChunk(
                    text=piece,
                    page_number=unit.page_number,
                    sheet_name=unit.sheet_name,
                    section=unit.section,
                )
            )
    return chunks


#: How far back from a chunk's target end `_snap_to_boundary` will
#: search for a natural break. Bounded so a stretch of text with no
#: nearby paragraph/sentence/word boundary (dense numeric data, a long
#: URL) still produces a normally-sized chunk instead of degrading
#: toward one character at a time.
_BOUNDARY_LOOKBACK = 200

_SENTENCE_BREAK_RE = re.compile(r"[.!?]\s")


def _snap_to_boundary(text: str, start: int, end: int) -> int:
    """Nudge `end` back to the nearest paragraph, sentence, or word
    boundary within a bounded lookback window.

    Tried in that order because a paragraph break is the strongest
    signal that a chunk should stop there, and a mid-word cut is worse
    for both readability and embedding quality than a slightly
    shorter/longer chunk. Falls back to `end` unchanged when nothing is
    found nearby — a hard cut beats an unbounded search, and remains
    correct (just not ideal) for text with no natural breaks at all.
    """
    window_start = max(start, end - _BOUNDARY_LOOKBACK)
    window = text[window_start:end]

    paragraph_at = window.rfind("\n\n")
    if paragraph_at != -1:
        return window_start + paragraph_at + 2

    sentence_end = -1
    for match in _SENTENCE_BREAK_RE.finditer(window):
        sentence_end = match.end()
    if sentence_end != -1:
        return window_start + sentence_end

    space_at = window.rfind(" ")
    if space_at != -1:
        return window_start + space_at + 1

    return end


def chunk_text(text: str, *, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks, preferring natural boundaries.

    Each chunk is at most `chunk_size` characters. Rather than always
    cutting at exactly `chunk_size` — which regularly splits a chunk
    mid-word or mid-sentence — the cut point is nudged back to the
    nearest paragraph, sentence, or word boundary within a bounded
    lookback window (`_snap_to_boundary`), so retrieval units read as
    coherent text rather than arbitrary character windows.

    Args:
        text: The full extracted text to split.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Characters of overlap between consecutive chunks,
            so context near a chunk boundary isn't lost entirely.

    Returns:
        Chunk strings in order. Empty/whitespace-only input yields an
        empty list.

    Raises:
        ValueError: If `chunk_overlap` is not smaller than `chunk_size`.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must not be negative.")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size.")

    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(stripped)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            end = _snap_to_boundary(stripped, start, end)
        chunk = stripped[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break
        # Advance from the boundary actually used, not a fixed step, so
        # overlap stays accurate relative to where this chunk really
        # ended rather than where a hard cut would have. Guarantees
        # forward progress even when a snap produced a very short chunk.
        next_start = end - chunk_overlap
        start = next_start if next_start > start else start + 1

    return chunks
