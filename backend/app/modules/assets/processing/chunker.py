"""Deterministic text chunking for the knowledge base pipeline.

Pure string manipulation — no AI/ML model involved — so unlike
extraction and embeddings, this is fully implemented rather than a
placeholder.
"""


def chunk_text(text: str, *, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[str]:
    """Split text into overlapping fixed-size chunks.

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
    step = chunk_size - chunk_overlap

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = stripped[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == text_length:
            break
        start += step

    return chunks
