"""Evidence-state classification (Sprint 16 Phase 8.1).

A read-only projection over fields that already exist on
`ComparisonItem`/`ResearchVariable`/citation-validation results — not a
new column, not persisted, not a production decision. It exists so a
future evidence visualization (or this phase's evaluation harness) has
one place to ask "how trustworthy is this specific piece of evidence?"
instead of re-deriving the answer from four different enums at every
call site.

No migration: `classify_evidence_state` is a pure function computed at
read time from data the caller already has in hand.
"""

from __future__ import annotations

import enum

from app.modules.research.schemas import ComparisonRelationship, ResearchCertainty


class EvidenceState(str, enum.Enum):
    """Independent trust classification for one evidence item.

    Priority order in `classify_evidence_state` matters: a contradicted
    relationship outranks everything else, and a citation the backend
    actually rejected outranks a model's self-reported certainty — the
    same "backend verdict beats model claim" rule `ResearchGroundingStatus`
    already applies to the synthesis answer as a whole.
    """

    #: Backend-verified: an accepted (non-hallucinated) citation, or an
    #: explicitly-stated fact with a real source pointer.
    VERIFIED = "verified"
    #: Not directly stated but computed/paraphrased from real evidence
    #: (interpreted or strongly-supported certainty, no backend check).
    DERIVED = "derived"
    #: Backs a claim without being its primary source (e.g. a supporting
    #: paper in a cross-paper comparison).
    SUPPORTING = "supporting"
    #: No usable source pointer, or the model itself reported UNKNOWN.
    UNKNOWN = "unknown"
    #: Contradicts other evidence for the same claim.
    CONTRADICTED = "contradicted"


def classify_evidence_state(
    *,
    certainty: ResearchCertainty | None = None,
    relationship: ComparisonRelationship | None = None,
    citation_accepted: bool | None = None,
    is_primary_source: bool = True,
    has_source_evidence: bool = True,
) -> EvidenceState:
    """Derive an `EvidenceState` from existing, already-computed signals.

    Args:
        certainty: the item's `ResearchCertainty`, if any.
        relationship: the item's `ComparisonRelationship`, if any
            (cross-paper comparison items only).
        citation_accepted: `True`/`False` when a citation-id validator
            (`synthesis._validate_citation_ids`) has already ruled on
            this item; `None` when no such check applies.
        is_primary_source: `False` when the evidence comes from a
            supporting paper rather than the primary paper.
        has_source_evidence: `False` when the item carries no source
            pointer at all (e.g. `source_evidence is None`).
    """
    if relationship == ComparisonRelationship.CONTRADICTS:
        return EvidenceState.CONTRADICTED

    if citation_accepted is False:
        # Claimed but not actually present in the supplied evidence --
        # the same fact `ResearchGroundingStatus` downgrades an answer
        # for. Never "verified" no matter what the model claimed.
        return EvidenceState.UNKNOWN

    if not has_source_evidence or certainty == ResearchCertainty.UNKNOWN:
        return EvidenceState.UNKNOWN

    if citation_accepted is True or certainty == ResearchCertainty.EXPLICIT:
        return EvidenceState.VERIFIED

    if not is_primary_source:
        return EvidenceState.SUPPORTING

    return EvidenceState.DERIVED
