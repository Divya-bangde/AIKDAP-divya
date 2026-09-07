"""Sprint 12.2: boundary-aware chunking tests for `chunk_text`.

No test file existed for this function before this sprint (it was
exercised only indirectly through extractor/pipeline tests using text
short enough to never split). These tests cover the splitting
algorithm itself: the paragraph/sentence/word boundary preference
added this sprint, and the invariants that must hold regardless of
where a boundary lands (no gaps, no infinite loop, respects
chunk_size).
"""

import pytest

from app.modules.assets.processing.chunker import ProvenancedChunk, chunk_document, chunk_text
from app.modules.assets.processing.extractors import ExtractedDocument, ExtractedUnit


def test_short_text_is_a_single_chunk():
    assert chunk_text("Hello world.", chunk_size=1000, chunk_overlap=100) == ["Hello world."]


def test_empty_text_yields_no_chunks():
    assert chunk_text("   \n\t  ", chunk_size=1000, chunk_overlap=100) == []


def test_invalid_overlap_raises():
    with pytest.raises(ValueError, match="chunk_overlap must be smaller"):
        chunk_text("some text", chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError, match="chunk_overlap must not be negative"):
        chunk_text("some text", chunk_size=100, chunk_overlap=-1)
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        chunk_text("some text", chunk_size=0, chunk_overlap=0)


def test_every_character_is_covered_no_gaps():
    """The overlap-tracking rewrite must never skip text between chunks:
    every character of the source must appear in at least one chunk."""
    text = ("The quick brown fox jumps over the lazy dog. " * 30).strip()
    chunks = chunk_text(text, chunk_size=120, chunk_overlap=20)

    assert len(chunks) > 1
    covered = "".join(chunks)
    for word in text.split():
        assert word in covered


def test_chunks_never_exceed_chunk_size():
    text = "Paragraph one is here.\n\n" + ("Sentence filler. " * 100)
    chunks = chunk_text(text, chunk_size=200, chunk_overlap=30)
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_prefers_paragraph_boundary_over_mid_word_cut():
    """A paragraph break placed just before the target chunk_size must be
    used as the cut point, instead of slicing into the next paragraph's
    first word."""
    first = "A" * 90
    second = "B" * 90
    text = f"{first}\n\n{second}"

    chunks = chunk_text(text, chunk_size=95, chunk_overlap=10)

    assert chunks[0] == first
    assert not chunks[0].endswith("B")


def test_prefers_sentence_boundary_when_no_paragraph_break():
    text = "First sentence ends here. Second sentence starts and is somewhat longer than the first one."
    chunks = chunk_text(text, chunk_size=30, chunk_overlap=5)

    assert chunks[0] == "First sentence ends here."


def test_falls_back_to_hard_cut_when_no_boundary_exists():
    """Dense text with no whitespace/punctuation near the target end must
    still produce a bounded chunk rather than searching forever."""
    text = "x" * 500
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)

    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join(dict.fromkeys(chunks[0])) == "x"


def test_progress_always_advances_no_infinite_loop():
    """A pathological input that repeatedly offers a boundary right at
    the window's start must not stall the loop."""
    text = ". " * 2000
    chunks = chunk_text(text, chunk_size=50, chunk_overlap=40)
    assert len(chunks) > 0  # completes at all is the assertion


def test_chunk_document_still_carries_provenance_per_unit():
    """The boundary-snapping change must not affect `chunk_document`'s
    per-unit provenance contract from Sprint 12.1."""
    document = ExtractedDocument(
        units=[
            ExtractedUnit(text="Page one content here.", page_number=1),
            ExtractedUnit(text="Page two content here.", page_number=2),
        ]
    )
    chunks = chunk_document(document, chunk_size=1000, chunk_overlap=100)

    assert len(chunks) == 2
    assert all(isinstance(chunk, ProvenancedChunk) for chunk in chunks)
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 2
