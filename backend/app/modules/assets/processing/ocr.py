"""OCR: recovering text from an image via Tesseract (Sprint 12.5).

Deliberately small and deliberately synchronous under the hood: this
module's only job is "given raw image bytes, return the text Tesseract
is actually confident about, or nothing" -- structural decisions (which
pages need OCR, how the result becomes an `ExtractedUnit`, what
exception maps to which processing status) belong to the callers in
`extractors.py`, not here.

`ocr_image` never raises for a *specific image* being unusable
(corrupt, oversized, blank, illegible) -- it returns an `OcrOutcome`
with empty text and a `skipped_reason`, the same "no unit for this
page" shape native text extraction already uses for an empty page.
The only thing this module raises is `OcrUnavailableError`, and only
for a *deployment-wide* condition (OCR disabled by configuration, or
the `tesseract` binary genuinely isn't installed) -- callers are
expected to map that to `OcrRequiredError`, matching the honest
"scanned and this deployment cannot read it" outcome Sprint 12.3
already established.
"""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class OcrUnavailableError(Exception):
    """OCR cannot run at all on this deployment: disabled by
    configuration, or the Tesseract binary is not installed."""


def _detect_and_correct_orientation(image: Image.Image) -> Image.Image:
    """Rotate `image` upright first if Tesseract OSD confidently detects
    it is not (Sprint 12.5 Phase 3).

    OSD (`tesseract-ocr`'s `osd` trained data, already installed --
    no new dependency) classifies a page as needing a 0/90/180/270
    degree correction. Measured live against this deployment: a 90-
    or 180-degree-rotated real scanned page previously produced
    completely wrong text that still passed the word-confidence gate
    below (word-level confidence measures "did Tesseract recognize
    *some* glyphs confidently", not "is the page oriented correctly" --
    a mirrored/upside-down page can score high on the former while
    being 100% wrong). Applying OSD's correction first recovered exact
    text at ~95% confidence across all four orientations.

    Returns `image` unchanged -- never raises -- whenever OSD cannot
    confidently determine orientation: a blank/near-empty image raises
    `pytesseract.TesseractError` ("Too few characters"), which is
    treated as inconclusive, not fatal, since a single bad OSD attempt
    must never fail an otherwise processable document. A structurally
    "successful" but meaningless OSD read is also possible -- measured
    live, random noise returned `orientation_conf=0.13` versus 3.7-3.9
    for genuine rotated text -- so a low-confidence result is likewise
    ignored via `ocr_osd_min_confidence`, sitting well below the real
    range and well above the noise measurement.
    """
    import pytesseract

    try:
        osd = pytesseract.image_to_osd(
            image, timeout=settings.ocr_timeout_seconds, output_type=pytesseract.Output.DICT
        )
    except Exception as exc:  # noqa: BLE001 - OSD is a best-effort pre-step; any failure means "proceed unrotated"
        logger.debug("ocr_osd_inconclusive", error_type=type(exc).__name__, reason=str(exc))
        return image

    rotate = osd.get("rotate") or 0
    confidence = osd.get("orientation_conf") or 0.0
    if not rotate or confidence < settings.ocr_osd_min_confidence:
        return image

    logger.info("ocr_osd_rotation_applied", rotate=rotate, orientation_conf=round(confidence, 2))
    # Exact 90/180/270-degree rotations of a rectangular image need no
    # fill color -- `expand=True` produces a perfect fit with no
    # exposed corners, unlike an arbitrary-angle skew correction would.
    return image.rotate(-rotate, expand=True)


@dataclass(frozen=True)
class OcrOutcome:
    """What OCR produced for one image, plus enough of the quality
    signal to explain a rejection in a log line.

    `text` is `""` whenever the quality gate rejected the result --
    callers never need to separately re-check confidence/word_count
    themselves; they exist for diagnostics only.
    """

    text: str
    average_confidence: float
    word_count: int
    #: Set only when `text` is empty, naming why: "no text recognized",
    #: "confidence too low", "output too short", "image too large",
    #: or "not a readable image". `None` when OCR produced usable text.
    skipped_reason: str | None = None


def ocr_image(image_bytes: bytes) -> OcrOutcome:
    """Run OCR on one image's raw bytes and apply the quality gate.

    Synchronous and CPU/subprocess-bound (Tesseract runs as a child
    process); callers in an async context should run this via
    `asyncio.to_thread`, not await it directly.

    Raises `OcrUnavailableError` only for the deployment-wide case.
    Every per-image failure (corrupt bytes, oversized image, nothing
    recognized, low-confidence recognition) is reported through the
    returned `OcrOutcome`, never raised -- a single bad image must
    never abort a whole document.
    """
    if not settings.ocr_enabled:
        raise OcrUnavailableError("OCR is disabled by configuration (OCR_ENABLED=false).")

    # Imported here, not at module scope: importing pytesseract does
    # not itself require the `tesseract` binary to exist, so the real
    # "is it installed" check has to happen at call time regardless --
    # deferring the import alongside it keeps both failure modes in one
    # place instead of splitting them across import time and call time.
    import pytesseract

    try:
        # `Image.open` reads only the header (format, dimensions) --
        # cheap, no pixel data decoded yet. The size check below must
        # run on THIS, before `.load()`, or an oversized image gets
        # fully decoded into memory before its size is ever checked,
        # defeating the point of the cap (Sprint 12.5 Phase 10).
        image = Image.open(io.BytesIO(image_bytes))
    except (UnidentifiedImageError, OSError, ValueError):
        return OcrOutcome(
            text="", average_confidence=0.0, word_count=0, skipped_reason="not a readable image"
        )

    # An animated GIF is OCR'd on its first frame only (Sprint 12.5
    # Phase 3) -- `Image.open` already defaults to frame 0, so this
    # `seek(0)` changes nothing in practice; it exists to make that
    # choice explicit and logged rather than an implicit side effect of
    # Pillow's default, since nothing in this architecture models
    # "frame" as a provenance unit the way page_number/sheet_name do.
    if getattr(image, "n_frames", 1) > 1:
        logger.info("ocr_animated_image_first_frame_only", frame_count=image.n_frames)
        image.seek(0)

    pixel_count = image.width * image.height
    if pixel_count > settings.ocr_max_image_pixels:
        logger.warning(
            "ocr_image_too_large",
            width=image.width,
            height=image.height,
            pixel_count=pixel_count,
            limit=settings.ocr_max_image_pixels,
        )
        return OcrOutcome(
            text="", average_confidence=0.0, word_count=0, skipped_reason="image too large"
        )

    try:
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return OcrOutcome(
            text="", average_confidence=0.0, word_count=0, skipped_reason="not a readable image"
        )

    image = _detect_and_correct_orientation(image)

    try:
        data = pytesseract.image_to_data(
            image,
            lang=settings.ocr_language,
            timeout=settings.ocr_timeout_seconds,
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(f"Tesseract OCR engine is not installed: {exc}") from exc
    except RuntimeError as exc:
        # pytesseract's own timeout signal -- a specific image took too
        # long, not a deployment-wide problem.
        return OcrOutcome(
            text="", average_confidence=0.0, word_count=0, skipped_reason=f"OCR timed out: {exc}"
        )

    words = [(word, conf) for word, conf in zip(data["text"], data["conf"]) if word.strip()]
    confidences = [conf for _, conf in words if conf >= 0]
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    text = " ".join(word for word, _ in words)

    if not words:
        return OcrOutcome(
            text="", average_confidence=0.0, word_count=0, skipped_reason="no text recognized"
        )
    if average_confidence < settings.ocr_min_confidence:
        return OcrOutcome(
            text="",
            average_confidence=average_confidence,
            word_count=len(words),
            skipped_reason=(
                f"confidence too low ({average_confidence:.1f} < "
                f"{settings.ocr_min_confidence})"
            ),
        )
    if len(text) < settings.ocr_min_characters:
        return OcrOutcome(
            text="",
            average_confidence=average_confidence,
            word_count=len(words),
            skipped_reason="output too short",
        )

    return OcrOutcome(text=text, average_confidence=average_confidence, word_count=len(words))
