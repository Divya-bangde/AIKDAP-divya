"""Text extraction framework.

Defines `TextExtractor`, the interface every content-type-specific
extractor implements, and `get_text_extractor`, a registry that
dispatches by MIME type.

Every extractor returns an `ExtractedDocument` — a list of
`ExtractedUnit`s, not a flat string. A unit is one provenance-
addressable slice of content (a PDF page, a spreadsheet row, a slide,
a DOCX section) and carries whatever locator applies to it
(`page_number`, `sheet_name`, `section`). Chunking (see `chunker.py`)
never crosses a unit boundary, so every chunk — and therefore every
citation built from it — can name the page/sheet/slide it came from
instead of only an opaque `chunk_index`.

Three distinct outcomes, three distinct exceptions, on purpose (Sprint
12.1): a MIME type with no extractor at all (`ExtractionNotSupportedError`,
unchanged since Sprint 6/9), a supported type whose bytes don't
actually parse -- corrupted, malformed, password-protected
(`ExtractionFailedError`), and a PDF/image that parses fine but
contains zero machine-readable text -- almost always a scanned
document (`OcrRequiredError`). Collapsing any of these into "extraction
failed" would either hide a real corruption behind a misleading
"try OCR" message, or silently mark a scanned PDF's empty result as a
processing success -- both are the two things Sprint 12.1 was
explicitly asked not to do.
"""

from __future__ import annotations

import io
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ExtractionNotSupportedError(Exception):
    """Raised when no extractor is implemented yet for a given MIME type."""


class ExtractionFailedError(Exception):
    """Raised when a supported format's bytes could not actually be
    parsed: corrupted, malformed, truncated, or password-protected.
    Distinct from `ExtractionNotSupportedError` -- this is a genuine
    failure of a format we do support, not a known gap."""


class OcrRequiredError(Exception):
    """Raised when a PDF or image parses structurally but contains zero
    machine-readable text and OCR could not recover any -- either
    because OCR is disabled/unavailable on this deployment (Sprint
    12.5), or (pre-12.5, still possible if OCR is turned off) because
    the document is genuinely a scanned/image-only document with no
    OCR to fall back on. Never silently treated as "zero chunks,
    processing succeeded". Distinct from `ExtractionFailedError`: this
    means "OCR was never attempted", not "OCR ran and failed" -- the
    latter is a genuine extraction failure of a supported format, not
    a deployment capability gap."""


@dataclass(frozen=True)
class ExtractedUnit:
    """One provenance-addressable slice of extracted content.

    Exactly one of `page_number`/`sheet_name` is ever meaningful for a
    given format (a PDF page vs. an XLSX sheet); `section` (a heading,
    slide title, or similar) can accompany either. All three are
    `None` for formats with no internal structure (plain text, CSV).

    `extraction_method` (Sprint 12.5) records how THIS unit's text was
    recovered -- `"native"` or `"ocr"` for PDF pages and standalone
    images, `None` for every format where the distinction doesn't
    apply (DOCX, XLSX, ...). Diagnostic only: it never reaches
    `KnowledgeChunk`/citations, which already carry page/sheet/section
    provenance -- adding a second, redundant provenance field there
    would need a migration for no citation-visible benefit.
    """

    text: str
    page_number: int | None = None
    sheet_name: str | None = None
    section: str | None = None
    extraction_method: str | None = None


@dataclass
class ExtractedDocument:
    """The normalized result of extracting one asset's content.

    `warnings` records non-fatal extraction notices (e.g. "3 of 40
    pages contained no text") that don't justify failing the whole
    asset but are worth keeping -- currently logged, not yet
    surfaced to the frontend; a natural follow-up, not done this
    sprint since nothing consumes it yet.
    """

    units: list[ExtractedUnit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """All unit text concatenated, for callers that genuinely need
        the whole document as one string (AI understanding's input)."""
        return "\n\n".join(unit.text for unit in self.units if unit.text.strip())

    @property
    def has_extractable_text(self) -> bool:
        return bool(self.full_text.strip())


class TextExtractor(ABC):
    """Abstract interface for pulling normalized content out of raw file bytes."""

    @abstractmethod
    async def extract(self, content: bytes) -> ExtractedDocument:
        """Return the normalized content of a file's raw bytes.

        Raises `ExtractionFailedError` if the bytes don't parse as the
        expected format, or `OcrRequiredError` if they parse but yield
        no machine-readable text.
        """


def _clean_text(text: str) -> str:
    """Deterministic, meaning-preserving whitespace normalization.

    Collapses runs of 3+ blank lines to 2 (preserving paragraph
    boundaries, which use exactly one blank line), strips trailing
    whitespace per line, and normalizes CRLF/CR to LF. Does NOT reorder
    content, drop words, or attempt header/footer detection -- Sprint
    12.1's own Phase 4 explicitly warns against cleaning aggressively
    enough to change meaning, and repeated-header/footer stripping is a
    heuristic with real false-positive risk (a legitimately repeated
    section title looks identical to a running header); left as a
    documented gap rather than shipped half-confident.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    cleaned = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


#: Sprint 12.4: fraction of a decoded document that may be UTF-8
#: replacement characters or non-whitespace control characters before
#: it's treated as binary content mislabeled as text, not genuine
#: prose. Calibrated against real files: a real 277KB production PDF
#: decoded as UTF-8 (`errors="replace"`) came out ~53% garbage by this
#: measure; genuine text files are effectively 0%. This exists because
#: extension/MIME cross-checking (`validators.validate_extension_matches_mime`)
#: closes the common upload-time path to this, but is not exhaustive
#: (a `.txt` file that is itself corrupted/binary at the source has a
#: consistent extension and MIME with no mismatch to catch) -- this is
#: the second, content-level line of defense.
_GARBAGE_CHARACTER_RATIO_THRESHOLD = 0.03
_TEXT_WHITESPACE = frozenset("\t\n\r")


def _looks_like_binary_garbage(text: str) -> bool:
    """True when `text` is mostly control/replacement characters -- the
    signature of binary content decoded as text, not genuine prose."""
    if not text:
        return False
    garbage = sum(
        1
        for ch in text
        if ch == "�" or (ord(ch) < 32 and ch not in _TEXT_WHITESPACE) or ord(ch) == 127
    )
    return garbage / len(text) > _GARBAGE_CHARACTER_RATIO_THRESHOLD


class PlainTextExtractor(TextExtractor):
    """Extracts text from already-textual formats (txt, md)."""

    async def extract(self, content: bytes) -> ExtractedDocument:
        decoded = content.decode("utf-8", errors="replace")
        if _looks_like_binary_garbage(decoded):
            raise ExtractionFailedError(
                "File does not appear to be valid text; it may be a "
                "binary file mislabeled as a text format."
            )
        text = _clean_text(decoded)
        return ExtractedDocument(units=[ExtractedUnit(text=text)] if text else [])


class JsonExtractor(TextExtractor):
    """Pretty-prints JSON so key/value relationships stay legible to an
    embedding model, instead of passing through whatever raw formatting
    (often minified, single-line) the file happened to have.

    Genuinely validates the JSON rather than only decoding bytes: a
    malformed file previously "succeeded" (raw text, however broken)
    under the old plain-decode behavior. A file claiming to be JSON
    that isn't valid JSON is a corrupted/mislabeled upload, not usable
    content -- `ExtractionFailedError`, not a silent pass-through.
    """

    async def extract(self, content: bytes) -> ExtractedDocument:
        try:
            decoded = content.decode("utf-8")
            data = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExtractionFailedError(f"File is not valid JSON: {exc}") from exc
        text = _clean_text(json.dumps(data, indent=2, ensure_ascii=False))
        return ExtractedDocument(units=[ExtractedUnit(text=text)] if text else [])


def _format_row(headers: list[str], values: list[str]) -> str:
    """`Column=Value | Column=Value` — used by `DocxExtractor` for table
    rows embedded inside a document that already has other narrative
    text (headings, paragraphs) to give the row surrounding context, so
    a denser inline format is fine there. CSV/XLSX rows have no such
    surrounding text of their own; see `_format_row_labeled` for those."""
    pairs = [
        f"{header}={value}" for header, value in zip(headers, values, strict=False) if header
    ]
    return " | ".join(pairs)


def _format_row_labeled(headers: list[str], values: list[str]) -> str:
    """`Column: Value`, one pair per line — the CSV/XLSX row representation
    (Sprint 12.8).

    A lone row is a complete, standalone chunk with nothing else to
    place it in context (unlike a DOCX table row, which sits among
    other extracted paragraphs). Measured directly against this
    deployment's own reranker: a dense `Column=Value | Column=Value`
    row scores below a full prose sentence stating the same fact when
    both are retrieval candidates for the same query, because the row
    reads as an opaque data dump rather than a stated fact. One
    labelled pair per line reads closer to prose while still keeping
    every value attached to its real column header — no value is
    invented, only labelled with a header the source file already
    supplied.
    """
    pairs = [
        f"{header}: {value}" for header, value in zip(headers, values, strict=False) if header
    ]
    return "\n".join(pairs)


class CsvExtractor(TextExtractor):
    """Row-oriented, header-labelled text — not a raw comma dump.

    A bare CSV line ("Laptop,West,50000") carries no semantic labels
    for an embedding model or a reader; one `Column: Value` pair per
    line does (Sprint 12.8: switched from a dense `Column=Value | ...`
    single line — see `_format_row_labeled`). One `ExtractedUnit` per
    row keeps chunking from ever splitting a row's fields across two
    chunks.
    """

    async def extract(self, content: bytes) -> ExtractedDocument:
        import csv as csv_module

        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionFailedError(f"CSV is not valid UTF-8: {exc}") from exc

        reader = csv_module.reader(io.StringIO(decoded))
        rows = list(reader)
        if not rows:
            return ExtractedDocument(units=[])

        headers = rows[0]
        units = [
            ExtractedUnit(text=f"Row: {index}\n{formatted}")
            for index, row in enumerate(rows[1:], start=1)
            if (formatted := _format_row_labeled(headers, row))
        ]
        return ExtractedDocument(units=units)


class PdfExtractor(TextExtractor):
    """One `ExtractedUnit` per page, via `pypdf` (pure Python, no
    system/poppler dependency for parsing/native text).

    Pages with no extractable native text are common and not an error
    on their own (a genuine blank page). Sprint 12.5: a page with no
    native text is no longer immediately given up on -- OCR (see
    `ocr.py`) is attempted on that page's embedded image(s) first, via
    `pypdf`'s own `page.images` (no rasterization dependency needed).
    Only a page where BOTH native extraction and OCR come back empty
    counts toward the empty-page ratio that can still fail the whole
    document.
    """

    async def extract(self, content: bytes) -> ExtractedDocument:
        import asyncio

        from app.core.config import settings
        from app.modules.assets.processing.ocr import OcrUnavailableError, ocr_image
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(content))
        except PdfReadError as exc:
            raise ExtractionFailedError(f"PDF could not be parsed: {exc}") from exc

        if reader.is_encrypted:
            # pypdf can sometimes still open an encrypted PDF's
            # structure without the password but never extract text
            # from it -- treated as a parse failure, not silently
            # returning nothing.
            raise ExtractionFailedError(
                "PDF is password-protected; cannot extract text without a password."
            )

        units: list[ExtractedUnit] = []
        warnings: list[str] = []
        empty_page_indices: list[int] = []
        total_pages = len(reader.pages)

        for index, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - one bad page must not fail the whole PDF
                warnings.append(f"page {index}: extraction error ({exc})")
                empty_page_indices.append(index)
                continue
            text = _clean_text(raw)
            if text:
                units.append(ExtractedUnit(text=text, page_number=index, extraction_method="native"))
            else:
                empty_page_indices.append(index)

        # Sprint 12.5: OCR only the pages that actually need it, and
        # only up to a bounded count -- never the whole document, never
        # unbounded (Phase 10 security: a many-hundred-page scanned PDF
        # must not be able to demand unlimited OCR compute).
        ocr_unavailable = False
        if empty_page_indices and settings.ocr_enabled:
            attempted = 0
            for index in empty_page_indices:
                if attempted >= settings.ocr_max_pages_per_document:
                    warnings.append(
                        f"OCR page limit ({settings.ocr_max_pages_per_document}) reached; "
                        "remaining empty pages were not OCR'd."
                    )
                    break
                try:
                    # pypdf decompresses the image XObject internally on
                    # `.data` access -- a crafted PDF could make this
                    # slow (Phase 10 security: same class of concern as
                    # a decompression bomb). Run off the event loop with
                    # a bound, matching the timeout already applied to
                    # the OCR call itself below.
                    page_images = await asyncio.wait_for(
                        asyncio.to_thread(lambda p=reader.pages[index - 1]: list(p.images)),
                        timeout=settings.ocr_timeout_seconds,
                    )
                except Exception:  # noqa: BLE001 - a bad/slow page must not abort OCR for the rest
                    page_images = []
                if not page_images:
                    continue

                attempted += 1
                fragments: list[str] = []
                for image_file in page_images:
                    try:
                        outcome = await asyncio.to_thread(ocr_image, image_file.data)
                    except OcrUnavailableError:
                        ocr_unavailable = True
                        break
                    if outcome.text:
                        fragments.append(outcome.text)
                    elif outcome.skipped_reason:
                        warnings.append(f"page {index}: OCR skipped ({outcome.skipped_reason})")
                if ocr_unavailable:
                    break

                recovered = _clean_text("\n".join(fragments))
                if recovered:
                    units.append(
                        ExtractedUnit(text=recovered, page_number=index, extraction_method="ocr")
                    )

        recovered_pages = {u.page_number for u in units if u.extraction_method == "ocr"}
        empty_pages = len([i for i in empty_page_indices if i not in recovered_pages])

        if not units:
            if ocr_unavailable or not settings.ocr_enabled:
                raise OcrRequiredError(
                    f"PDF contains no machine-readable text across {total_pages} page(s), "
                    "and OCR is not available on this deployment."
                )
            raise ExtractionFailedError(
                f"OCR was attempted but produced no usable text across {total_pages} page(s)."
            )
        if empty_pages / total_pages >= settings.pdf_ocr_required_empty_page_ratio:
            # A minority of readable/OCR-recoverable pages (e.g. a text
            # cover page ahead of dozens of illegible scans) is not a
            # usable index of the document -- flagging the whole file
            # is more honest than silently completing on a fraction.
            if ocr_unavailable or not settings.ocr_enabled:
                raise OcrRequiredError(
                    f"{empty_pages} of {total_pages} pages ({100 * empty_pages // total_pages}%) "
                    "contain no machine-readable text, and OCR is not available on this "
                    "deployment."
                )
            raise ExtractionFailedError(
                f"{empty_pages} of {total_pages} pages ({100 * empty_pages // total_pages}%) "
                "have no usable text even after OCR; this document is not reliably readable."
            )
        if empty_pages:
            warnings.append(f"{empty_pages} of {total_pages} pages contained no extractable text")

        return ExtractedDocument(units=units, warnings=warnings)


class DocxExtractor(TextExtractor):
    """Paragraphs grouped under their most recent heading (`section`),
    plus tables rendered the same header-labelled way as CSV/XLSX
    rows. python-docx raises `PackageNotFoundError` for a corrupted or
    non-DOCX-despite-the-extension file."""

    async def extract(self, content: bytes) -> ExtractedDocument:
        import zipfile

        import docx
        from docx.opc.exceptions import PackageNotFoundError

        try:
            document = docx.Document(io.BytesIO(content))
        except (PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            # DOCX is a ZIP container -- bytes that aren't a ZIP at all
            # raise zipfile's own exception, not python-docx's; bytes
            # that are a ZIP but not a valid DOCX package raise
            # python-docx's. Both are "this file doesn't parse".
            raise ExtractionFailedError(f"DOCX could not be parsed: {exc}") from exc

        units: list[ExtractedUnit] = []
        current_section: str | None = None

        for paragraph in document.paragraphs:
            text = _clean_text(paragraph.text)
            if not text:
                continue
            style_name = (paragraph.style.name if paragraph.style else "") or ""
            if style_name.lower().startswith("heading") or style_name.lower() == "title":
                current_section = text
            units.append(ExtractedUnit(text=text, section=current_section))

        for table_index, table in enumerate(document.tables, start=1):
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not rows:
                continue
            headers = rows[0]
            for row_index, row in enumerate(rows[1:], start=1):
                formatted = _format_row(headers, row)
                if formatted:
                    units.append(
                        ExtractedUnit(
                            text=f"Table {table_index}, row {row_index}: {formatted}",
                            section=current_section,
                        )
                    )

        return ExtractedDocument(units=units)


class XlsxExtractor(TextExtractor):
    """One `ExtractedUnit` per data row, header-labelled, grouped by
    `sheet_name`. `data_only=True` reads formula *results* (what a user
    actually sees), not formula source text.

    Each row's text also states its own sheet name and row number
    (Sprint 12.8) in addition to the existing `sheet_name` provenance
    field: a lone row chunk has no other document text of its own to
    place it in context the way a DOCX table row (surrounded by other
    extracted paragraphs) or a PDF page does. Repeating the sheet name
    inline costs a fixed, small amount of text per row (not per
    document) and is not fabricated — it is the same value already
    carried on `sheet_name`, just also made visible to the embedding
    and reranking models, which never see structured fields directly.
    """

    async def extract(self, content: bytes) -> ExtractedDocument:
        import zipfile

        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException

        try:
            workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        except (InvalidFileException, KeyError, OSError, zipfile.BadZipFile) as exc:
            raise ExtractionFailedError(f"XLSX could not be parsed: {exc}") from exc

        units: list[ExtractedUnit] = []
        for sheet in workbook.worksheets:
            rows_iter = sheet.iter_rows(values_only=True)
            try:
                headers = [str(cell) if cell is not None else "" for cell in next(rows_iter)]
            except StopIteration:
                continue
            for row_index, row in enumerate(rows_iter, start=1):
                values = ["" if cell is None else str(cell) for cell in row]
                formatted = _format_row_labeled(headers, values)
                if formatted:
                    units.append(
                        ExtractedUnit(
                            text=f"Sheet: {sheet.title}\nRow: {row_index}\n{formatted}",
                            sheet_name=sheet.title,
                        )
                    )

        return ExtractedDocument(units=units)


class PptxExtractor(TextExtractor):
    """One `ExtractedUnit` per slide (`page_number` = slide number),
    with the slide's title (if any placeholder holds one) as `section`."""

    async def extract(self, content: bytes) -> ExtractedDocument:
        import zipfile

        from pptx import Presentation
        from pptx.exc import PackageNotFoundError

        try:
            presentation = Presentation(io.BytesIO(content))
        except (PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            raise ExtractionFailedError(f"PPTX could not be parsed: {exc}") from exc

        units: list[ExtractedUnit] = []
        for index, slide in enumerate(presentation.slides, start=1):
            title = None
            if slide.shapes.title and slide.shapes.title.text.strip():
                title = slide.shapes.title.text.strip()

            fragments: list[str] = []
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                shape_text = _clean_text(shape.text_frame.text)
                if shape_text:
                    fragments.append(shape_text)

            text = "\n".join(fragments)
            if text:
                units.append(ExtractedUnit(text=text, page_number=index, section=title))

        return ExtractedDocument(units=units)


class HtmlExtractor(TextExtractor):
    """Text grouped by heading (`section`, h1-h6), scripts/styles
    stripped. BeautifulSoup with the lxml backend tolerates malformed
    markup by design (best-effort parsing, not strict validation), so
    there is no realistic "corrupted HTML" failure mode to raise for --
    a file with no extractable text is a legitimately empty page, not
    an extraction error."""

    async def extract(self, content: bytes) -> ExtractedDocument:
        from bs4 import BeautifulSoup

        decoded = content.decode("utf-8", errors="replace")
        if _looks_like_binary_garbage(decoded):
            raise ExtractionFailedError(
                "File does not appear to be valid HTML; it may be a "
                "binary file mislabeled as text/html."
            )
        soup = BeautifulSoup(decoded, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()

        units: list[ExtractedUnit] = []
        current_section: str | None = None
        current_fragments: list[str] = []

        def flush() -> None:
            text = _clean_text("\n".join(current_fragments))
            if text:
                units.append(ExtractedUnit(text=text, section=current_section))
            current_fragments.clear()

        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"]):
            element_text = element.get_text(" ", strip=True)
            if not element_text:
                continue
            if element.name.startswith("h"):
                flush()
                current_section = element_text
            else:
                current_fragments.append(element_text)
        flush()

        if not units:
            # No structural tags matched (e.g. a fragment with only a
            # bare <div>) -- fall back to whole-document text rather
            # than reporting an empty document that genuinely has text.
            fallback = _clean_text(soup.get_text("\n", strip=True))
            if fallback:
                units.append(ExtractedUnit(text=fallback))

        return ExtractedDocument(units=units)


class ImageExtractor(TextExtractor):
    """OCRs a standalone image (PNG/JPEG/GIF/WEBP) into a single
    `ExtractedUnit` (Sprint 12.5; GIF/WEBP wired in Sprint 12.5 Phase 3
    -- same OCR call, no format-specific branching needed here since
    `ocr_image` decodes via Pillow, which already reads all four).

    No `page_number`: an image has no page semantics, and fabricating
    one would be a false provenance claim. A citation built from this
    asset's single unit already identifies the source through the
    asset's own title/filename (the same way any other single-unit
    format's citations do) -- no locator field is needed to make it
    traceable.

    An animated GIF is OCR'd on its first frame only (see `ocr_image`'s
    explicit `seek(0)`) -- deliberately, not a multi-page/multi-frame
    document: nothing else in this architecture models "frame" as a
    provenance unit the way `page_number`/`sheet_name` do, and guessing
    which frame(s) carry meaningful text would be unfounded.
    """

    async def extract(self, content: bytes) -> ExtractedDocument:
        import asyncio

        from app.modules.assets.processing.ocr import OcrUnavailableError, ocr_image

        try:
            outcome = await asyncio.to_thread(ocr_image, content)
        except OcrUnavailableError as exc:
            raise OcrRequiredError(str(exc)) from exc

        if not outcome.text:
            reason = outcome.skipped_reason or "no readable text was found"
            raise ExtractionFailedError(f"OCR could not extract usable text: {reason}.")

        text = _clean_text(outcome.text)
        return ExtractedDocument(
            units=[ExtractedUnit(text=text, extraction_method="ocr")] if text else []
        )


class UnsupportedExtractor(TextExtractor):
    """Placeholder for formats with no real extractor (legacy .doc/.xls/
    .ppt, SVG, anything else outside the supported set). Raises rather
    than silently returning empty or fabricated text, so
    the pipeline can record this as `UNSUPPORTED` -- a known gap --
    rather than mistaking it for a genuine failure."""

    def __init__(self, mime_type: str) -> None:
        self._mime_type = mime_type

    async def extract(self, content: bytes) -> ExtractedDocument:
        raise ExtractionNotSupportedError(
            f"No text extractor implemented yet for MIME type '{self._mime_type}'."
        )


_EXTRACTOR_FACTORIES: dict[str, type[TextExtractor]] = {
    "text/plain": PlainTextExtractor,
    "text/markdown": PlainTextExtractor,
    "application/json": JsonExtractor,
    "text/csv": CsvExtractor,
    "application/pdf": PdfExtractor,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxExtractor,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XlsxExtractor,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": PptxExtractor,
    "text/html": HtmlExtractor,
    "image/png": ImageExtractor,
    "image/jpeg": ImageExtractor,
    "image/gif": ImageExtractor,
    "image/webp": ImageExtractor,
}


def get_text_extractor(mime_type: str) -> TextExtractor:
    """Return the extractor for a given MIME type.

    Adding a format means adding one entry to `_EXTRACTOR_FACTORIES`
    and one class above -- `pipeline.py` and everything upstream of it
    never need to know a new format exists.
    """
    factory = _EXTRACTOR_FACTORIES.get(mime_type)
    if factory is not None:
        return factory()
    return UnsupportedExtractor(mime_type)
