"""Sprint 12.4: tests for the extension/MIME consistency check.

No test file existed for `app.modules.assets.validators` before this
sprint -- `validate_extension`/`validate_mime_type` were each exercised
only indirectly through upload-path integration elsewhere. This file
covers `validate_extension_matches_mime` specifically: the new
cross-check closing the gap where two individually-allowed values
could still disagree with each other (see the function's own
docstring for the confirmed real-world exploit this closes).
"""

import pytest

from app.modules.assets.validators import AssetValidationError, validate_extension_matches_mime


def test_matching_extension_and_mime_passes():
    validate_extension_matches_mime(".pdf", "application/pdf")
    validate_extension_matches_mime(
        ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    validate_extension_matches_mime(".png", "image/png")


def test_mismatched_extension_and_mime_rejected():
    """The exact real-world case this sprint confirmed exploitable: a
    .pdf-named file declaring text/plain -- individually allowed, but
    inconsistent -- would have been routed to PlainTextExtractor."""
    with pytest.raises(AssetValidationError, match="does not match"):
        validate_extension_matches_mime(".pdf", "text/plain")


def test_docx_declared_as_image_rejected():
    with pytest.raises(AssetValidationError, match="does not match"):
        validate_extension_matches_mime(".docx", "image/png")


@pytest.mark.parametrize("extension", [".md", ".csv", ".json"])
def test_permissive_extensions_accept_text_plain(extension):
    """Real browsers/OSes are inconsistent about what they declare for
    these three -- Windows commonly sends text/plain for all of them.
    Rejecting that would break legitimate uploads with no evidence
    this sprint found justifying it."""
    validate_extension_matches_mime(extension, "text/plain")


def test_unmapped_extension_is_a_noop():
    """An extension with no entry in the family map must not reject --
    fails open so a future format added to ALLOWED_EXTENSIONS without
    a matching entry here doesn't start rejecting every upload of it."""
    validate_extension_matches_mime(".unknown", "application/octet-stream")
