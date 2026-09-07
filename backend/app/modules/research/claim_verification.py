"""Claim-level evidence verification (Sprint 16 Phase 8.5).

Phase 8.4 found three real failure modes that citation-id validation
cannot catch, because a citation id being valid says nothing about
whether the sentence attached to it is actually true of the cited
text:

1. aguilar_cti -- the model cited three real, supplied chunks and
   still reported "73.5%" as the *overall* pass rate. Every cited
   occurrence of 73.5% is scoped to one strategy (S4); none is labelled
   as an aggregate. `_validate_citation_ids` passes this answer because
   the ids are real -- it has no concept of what the citation is being
   used to assert.
2. vaniscak_c2 -- the model declined to answer, citing nothing, even
   though the evidence it was given ("JA4 fingerprints (100%
   detection)") already contained the requested value.
3. Phase 8.1 xp-05 -- a claim attributed to the primary paper whose
   only source reference is a supporting paper. Structurally valid
   (every reference resolves to a real paper id); semantically wrong.

This module is deliberately narrow: it answers "is this specific claim
supported by the specific evidence text cited for it?", not "is this
claim true." It takes structured inputs (a claimed value, a flag for
whether the claim asserts an aggregate, the literal evidence strings)
rather than parsing free text, because auto-extracting "what a
sentence claims" from prose is exactly the general-NLU problem this
phase declines to solve. Callers -- an evaluation harness today, a
future synthesis-time check tomorrow -- do that extraction and hand
this module the structured comparison.

No LLM call. No new taxonomy: `evidence_state_from_claim_verification`
projects a verdict onto the existing `EvidenceState` from Phase 8.1
rather than introducing a second, competing state model.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field

from app.modules.research.evidence_state import EvidenceState, classify_evidence_state

# Deferred (see `evidence_state_from_claim_verification`, the only user):
# `schemas.py` imports `ClaimSupport` from this module for
# `VerifiedClaimRead` (Sprint 16 Phase 8.7), so importing `schemas`
# back at module level here would be circular. Function-local avoids it
# without moving `ResearchCertainty` out of `schemas.py`.


class ClaimSupport(str, enum.Enum):
    """Whether a specific claim is backed by the evidence cited for it."""

    #: The claimed value/text appears in the cited evidence, consistent
    #: with how the claim uses it (e.g. not an aggregate claim resting
    #: on a per-component number).
    SUPPORTED = "supported"
    #: The cited evidence explicitly states something incompatible with
    #: the claim -- a different value for the same aggregate, or an
    #: alternate name for the same fact.
    CONTRADICTED = "contradicted"
    #: No evidence was cited/supplied at all, so there is nothing to
    #: check the claim against.
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    #: Evidence was cited, but it neither confirms nor contradicts this
    #: specific claim -- it is simply silent on it.
    UNVERIFIABLE = "unverifiable"


class SufficiencyVerdict(str, enum.Enum):
    """Distinguishes a genuine evidence gap from a model that had the answer and missed it."""

    #: The model did not claim insufficiency; this check does not apply.
    NOT_APPLICABLE = "not_applicable"
    #: The model claimed insufficiency and none of the evidence supplied
    #: to it (or none was supplied at all) contains the value needed.
    SOURCE_INSUFFICIENT = "source_insufficient"
    #: The model claimed insufficiency, but the evidence it was actually
    #: given contains the required value verbatim.
    MODEL_FAILED_TO_USE_SUFFICIENT_EVIDENCE = "model_failed_to_use_sufficient_evidence"


@dataclass(frozen=True)
class ClaimVerification:
    """The result of checking one claim against the evidence cited for it."""

    verdict: ClaimSupport
    #: Ids of the evidence items that drove the verdict (matched or
    #: contradicted), so the result stays traceable to real text rather
    #: than being a bare label.
    matched_evidence_ids: list[str] = field(default_factory=list)
    reason: str = ""


#: Language that marks a number as describing the whole, not one part
#: of it. Narrow on purpose: this is the exact vocabulary the aguilar_cti
#: failure turned on ("overall pass rate"), not a general aggregation
#: detector.
_AGGREGATE_LANGUAGE = re.compile(r"\b(overall|aggregate|combined|across all|total)\b", re.I)

#: Marks a number as scoped to one named component rather than the
#: whole -- either this paper's own strategy-code convention (S0-S9,
#: also Tier/Phase/Strategy N) or a generic "Label:" prefix. The
#: generic alternative excludes document-structure captions (Figure/
#: Table/Note/Appendix/Section N:) -- a figure or table NUMBER next to
#: a value says nothing about which component that value belongs to,
#: and a real Phase 8.7 production false positive was exactly this:
#: "N = 1,000" sitting a few dozen characters after "Figure 1:" was
#: read as a component label for the genuinely aggregate 1,000 figure.
_COMPONENT_LABEL = re.compile(
    r"\b(?:S\d|Strategy\s*\d|Tier\s*\d|Phase\s*\d)\b|"
    r"\b(?!Figure\b|Table\b|Note\b|Appendix\b|Section\b)[A-Z][\w\- ]{0,24}:\s",
    re.I,
)

#: How far (characters) around one occurrence of a claimed value to
#: look for a component label. Phase 8.5 originally searched the whole
#: evidence block, which is what produced the Phase 8.7 false positive:
#: a per-strategy table sharing a chunk with a genuinely aggregate
#: figure made the aggregate figure look component-scoped merely
#: because a component label existed *somewhere* in the same chunk.
#:
#: Asymmetric on purpose, from the real shapes observed: a genuine
#: label PRECEDES the row it scopes, with the row's other numbers in
#: between ("S4: One-Shot + BLUF 200 3.55 3.35 3.70 4.07 3.60 / 73.5%"
#: -- 51 characters from label to value), so the backward window has to
#: be generous. A genuine trailing qualifier is short ("...73.5% rate
#: under the S4 prompt configuration" -- 21 characters), while an
#: unrelated label can appear just as close on the far side purely by
#: prose coincidence (the exact Phase 8.7 case: "...N = 1,000) 3.2.1
#: The Underperformance of S1..." puts an unrelated "S1" 37 characters
#: after "1,000", inside the next sentence/subsection, not scoping it).
#: 60/30 catches every real labeled-row and trailing-qualifier case
#: observed so far while excluding that coincidental mention.
_COMPONENT_LABEL_WINDOW_BEFORE = 60
_COMPONENT_LABEL_WINDOW_AFTER = 30

_WORD = re.compile(r"[a-z0-9]+")


def _normalize_words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _shares_long_ngram(claim_text: str, evidence_text: str, *, min_words: int = 8) -> bool:
    """True if a run of `min_words` consecutive claim words appears verbatim in evidence.

    A cheap, deterministic stand-in for "this evidence states the same
    thing" that does not require a model call: near-verbatim source
    text is exactly what grounded synthesis is supposed to produce, so
    a long shared word run is real signal rather than a heuristic
    reaching past what it can support.

    Kept as-is (Sprint 16 Phase 8.9) alongside `_token_set_supported`
    below rather than replaced by it: this exact function is what keeps
    `test_categorical_claim_supported_verbatim` (a real Phase 8.5
    production case -- see that test's docstring) SUPPORTED, because the
    real cited text there uses "families"/"raising" where the claim says
    "family"/"raised" -- a token-set check with no stemming would reject
    it on those two words alone even though a verbatim run spans
    everything else. Removing this in favor of the new rule would trade
    one real regression for another; running both and requiring only one
    to fire is strictly additive.

    `min_words` raised from 6 to 8 this same phase: the Phase 8.9 safety
    tests (see `tests/test_claim_verification.py`) caught this function
    itself producing false SUPPORTED verdicts on two constructed cases --
    a claim sharing a 6-word prefix with evidence that then states
    something the claim never asserts ("...with zero false positives" /
    a differing "91%" vs "89%") -- 6 was simply too short a run to imply
    "this evidence backs this whole claim" once the claim extends past
    it. 8 clears both false positives with room to spare while the real
    families case above still shares a 16-word run, comfortably above
    either threshold.
    """
    claim_words = _normalize_words(claim_text)
    evidence_words = _normalize_words(evidence_text)
    if len(claim_words) < min_words:
        return " ".join(claim_words) in " ".join(evidence_words)
    evidence_joined = " ".join(evidence_words)
    for start in range(len(claim_words) - min_words + 1):
        window = " ".join(claim_words[start : start + min_words])
        if window in evidence_joined:
            return True
    return False


#: Sprint 16 Phase 8.9 -- paraphrase matching for `verify_categorical_claim`.
#:
#: `_shares_long_ngram` above requires a *contiguous* run of claim words
#: to appear verbatim, so it misses a claim that states the same fact
#: with different word order, tense, or number spelling. The rule below
#: is deliberately not a similarity score (no difflib, no embeddings, no
#: LLM): a claim's normalized content words either all appear together
#: in the cited text or they don't. Containment has no threshold to
#: calibrate; a similarity ratio would.
#:
#: Standard grammatical function words only -- articles, copulas,
#: relative pronouns, a handful of prepositions/conjunctions that never
#: carry the claim's meaning on their own. Quantifiers and negators
#: (all, no, none, not, never, only, just, most, some, both, each,
#: every, any, without) are deliberately NOT dropped: "all five
#: families" and "some families" differ only in a word a stopword list
#: would normally discard, and discarding it would erase exactly the
#: distinction a claim can get wrong.
_CATEGORICAL_STOPWORDS = frozenset(
    "a an the and or of in on at to for from by with as is are was were "
    "be been being that this these those it its than then so such into "
    "over under about which who whom".split()
)

#: Spelled-out numbers up to twenty, the range that shows up in these
#: papers' counts (families, strategies, tiers) -- not a general numeral
#: parser, which would be scope creep for a containment check.
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20",
}

#: "Same tokens, opposite meaning" is the one failure mode plain
#: containment cannot see -- "support is present" and "support is not
#: present" share every content word. Checked as presence-of-negation-
#: word rather than parsed polarity (no NLU here either): if the claim
#: and the matched evidence window disagree on whether a negator is
#: present at all, that is already enough signal to withhold SUPPORTED.
_NEGATION = re.compile(
    r"\b(not|no|never|without|cannot|can't|doesn't|does\s+not|didn't|did\s+not|"
    r"fails?\s+to|failed\s+to)\b",
    re.I,
)

#: How many evidence content-tokens wide a match window is allowed to
#: be, at minimum. Derived from a real adversarial case, not guessed: in
#: the real vaniscak_c2 evidence used in this phase's regression, "Traffic
#: Metadata" and the unrelated "...proved most viable" (which actually
#: describes "Traffic Patterns") sit 13 content-tokens apart in the same
#: chunk. A window has to stay under that distance or a claim that swaps
#: which entity a nearby property belongs to would falsely pass. 10 stays
#: under 13 while still covering every genuine single-clause paraphrase
#: observed. A claim with more than 10 content tokens of its own widens
#: the window to fit (see `_token_set_supported`) -- unavoidable, since a
#: window smaller than the claim itself could never contain it -- and is
#: a disclosed, accepted reduction in cross-entity protection for long
#: claims rather than an attempt to solve proximity-aware attribution.
_CATEGORICAL_WINDOW = 10


def _categorical_tokens(text: str) -> list[str]:
    """Lowercase, digit-group, number-word-normalize, and drop stopwords.

    Order-preserving (a list, not a set) because `_token_set_supported`
    still needs positions to build sliding windows; only the final
    containment comparison treats a window's tokens as a set.
    """
    text = re.sub(r"(?<=\d),(?=\d)", "", text)  # "1,000" -> "1000"
    words = (_NUMBER_WORDS.get(w, w) for w in _WORD.findall(text.lower()))
    return [w for w in words if w not in _CATEGORICAL_STOPWORDS]


def _token_set_supported(claim_text: str, evidence_text: str) -> bool:
    """True if every normalized content token of the claim co-occurs in one evidence window.

    Order-independent (a paraphrase may reorder clauses) but NOT
    position-independent (see `_CATEGORICAL_WINDOW`): the claim's tokens
    must all fall within one bounded stretch of the evidence, not merely
    appear somewhere in the whole chunk, or a chunk that discusses two
    different, contrasted entities could satisfy a claim about either
    one interchangeably.
    """
    claim_tokens = set(_categorical_tokens(claim_text))
    if not claim_tokens:
        return False
    claim_negated = bool(_NEGATION.search(claim_text))
    evidence_tokens = _categorical_tokens(evidence_text)
    window = max(_CATEGORICAL_WINDOW, len(claim_tokens))
    span_count = len(evidence_tokens)
    starts = range(max(1, span_count - window + 1)) if span_count > window else (0,)
    for start in starts:
        span = evidence_tokens[start : start + window]
        if claim_tokens <= set(span):
            if claim_negated == bool(_NEGATION.search(" ".join(span))):
                return True
    return False


def _has_local_component_label(text: str, claimed_value: str) -> bool:
    """True if a component label appears near an occurrence of `claimed_value`.

    Matches `_COMPONENT_LABEL` against the *full* text and compares
    spans, rather than slicing out a substring window and matching
    against that: slicing can cut a label in half at the window
    boundary (e.g. "Figure 1:" sliced to "gure 1:"), and because the
    generic label pattern is case-insensitive, the surviving fragment's
    leading lowercase letter still satisfies `[A-Z]` and the negative
    lookahead no longer sees the word it was written to exclude,
    reintroducing the exact false-positive family this function exists
    to remove. Span comparison has no such boundary.

    Checked around *every* occurrence of the value in `text` (a chunk
    can repeat a number in more than one context) rather than the
    first, so one component-scoped repeat cannot be missed because an
    earlier, unrelated repeat happened to be checked instead.
    """
    label_spans = [match.span() for match in _COMPONENT_LABEL.finditer(text)]
    if not label_spans:
        return False
    for value_match in re.finditer(re.escape(claimed_value), text):
        window_start = value_match.start() - _COMPONENT_LABEL_WINDOW_BEFORE
        window_end = value_match.end() + _COMPONENT_LABEL_WINDOW_AFTER
        for label_start, label_end in label_spans:
            if label_end > window_start and label_start < window_end:
                return True
    return False


def verify_numeric_claim(
    *,
    claimed_value: str,
    is_aggregate_claim: bool,
    evidence: list[tuple[str, str]],
) -> ClaimVerification:
    """Check a claimed number against the literal text cited for it.

    `evidence` is `(id, text)` pairs -- exactly the citations actually
    supplied to the synthesis model, never a superset. `claimed_value`
    is matched by literal substring (e.g. "73.5%"): this module does
    not parse numeric equivalence (comma separators, unit conversion,
    rounding) because that widens scope from "is this claim supported"
    toward a numeric reasoning engine, which is explicitly out of
    scope for this phase.
    """
    if not evidence:
        return ClaimVerification(ClaimSupport.INSUFFICIENT_EVIDENCE, [], "no evidence was cited")

    occurrences = [(eid, text) for eid, text in evidence if claimed_value in text]
    if not occurrences:
        return ClaimVerification(
            ClaimSupport.UNVERIFIABLE,
            [],
            f"cited evidence never mentions {claimed_value!r}",
        )

    if is_aggregate_claim:
        # Component scoping is checked in the LOCAL region around each
        # occurrence of the value (see `_has_local_component_label`),
        # not anywhere in the evidence text -- a per-strategy table
        # sharing a chunk with a genuinely aggregate figure must not
        # make that aggregate figure look component-scoped merely
        # because a component label exists elsewhere in the same chunk
        # (the real Phase 8.7 production false positive on "1,000").
        # Aggregate language is still checked over the whole text: it
        # only ever prevents a CONTRADICTED verdict, so a wider search
        # here is the conservative direction -- it can make the
        # verifier trust the model more, never wrongly contradict it.
        component_scoped = [
            (eid, text) for eid, text in occurrences if _has_local_component_label(text, claimed_value)
        ]
        aggregate_scoped = [
            (eid, text) for eid, text in occurrences if _AGGREGATE_LANGUAGE.search(text)
        ]
        if component_scoped and not aggregate_scoped:
            return ClaimVerification(
                ClaimSupport.CONTRADICTED,
                [eid for eid, _ in component_scoped],
                f"every cited occurrence of {claimed_value!r} is scoped to a named component, "
                "none is stated as an aggregate/overall figure",
            )

    return ClaimVerification(
        ClaimSupport.SUPPORTED, [eid for eid, _ in occurrences], f"{claimed_value!r} found in cited evidence"
    )


def verify_categorical_claim(
    *,
    claim_text: str,
    evidence: list[tuple[str, str]],
    contradicting_phrases: list[str] | None = None,
) -> ClaimVerification:
    """Check a non-numeric factual claim against the text cited for it.

    `contradicting_phrases` are literal, caller-supplied alternates for
    the same fact (e.g. a rival value the source states elsewhere for
    the same field) -- not inferred, for the same reason
    `verify_numeric_claim` does not infer aggregation: detecting
    "these two sentences assert incompatible things" in the general
    case is a semantic-truth problem, and this module only ever
    compares to phrases the caller already knows are the contradiction.

    A chunk counts as supporting evidence if EITHER `_shares_long_ngram`
    (a verbatim run) or `_token_set_supported` (Sprint 16 Phase 8.9 --
    reordered/renumbered paraphrase, still guarded against negation)
    fires -- the two catch different real cases and neither subsumes the
    other (see `_shares_long_ngram`'s docstring for why both stay).
    """
    if not evidence:
        return ClaimVerification(ClaimSupport.INSUFFICIENT_EVIDENCE, [], "no evidence was cited")

    contradicting_phrases = contradicting_phrases or []
    contradicted = [
        (eid, text)
        for eid, text in evidence
        if any(phrase.lower() in text.lower() for phrase in contradicting_phrases)
    ]
    if contradicted:
        return ClaimVerification(
            ClaimSupport.CONTRADICTED,
            [eid for eid, _ in contradicted],
            "cited evidence contains a stated alternative for the same fact",
        )

    supported = [
        (eid, text)
        for eid, text in evidence
        if _shares_long_ngram(claim_text, text) or _token_set_supported(claim_text, text)
    ]
    if supported:
        return ClaimVerification(
            ClaimSupport.SUPPORTED, [eid for eid, _ in supported], "claim text matches cited evidence"
        )

    return ClaimVerification(
        ClaimSupport.UNVERIFIABLE, [], "cited evidence does not state or contradict this claim"
    )


def classify_false_insufficiency(
    *,
    claimed_insufficient: bool,
    evidence_supplied: list[str],
    required_values: list[str],
) -> SufficiencyVerdict:
    """Tell a genuine evidence gap apart from a model that had the answer.

    `required_values` are the literal string(s) that would answer the
    question (e.g. `["100%"]`) -- supplied by the caller, not derived
    from the question text. Deriving "what value would satisfy this
    question" from free text is a general question-answering problem;
    this function only ever checks a caller-identified target against
    the evidence the model actually saw.
    """
    if not claimed_insufficient:
        return SufficiencyVerdict.NOT_APPLICABLE
    if not evidence_supplied or not required_values:
        return SufficiencyVerdict.SOURCE_INSUFFICIENT

    found = any(
        value.lower() in text.lower() for value in required_values for text in evidence_supplied
    )
    return (
        SufficiencyVerdict.MODEL_FAILED_TO_USE_SUFFICIENT_EVIDENCE
        if found
        else SufficiencyVerdict.SOURCE_INSUFFICIENT
    )


def detect_primary_supporting_contamination(
    *, claim_attributed_to_primary: bool, source_is_primary: list[bool]
) -> bool:
    """True when a primary-paper claim is backed only by supporting-paper sources.

    This is the Phase 8.1 xp-05 gap: `_validate_cross_paper_result`
    checks that every source reference resolves to a *known* paper id,
    not that a claim's sources match the paper it is attributed to. A
    claim with no sources at all is a different, already-caught
    failure (`missing_source_references`), so this only fires when
    sources exist and every one of them is a supporting paper.
    """
    return (
        claim_attributed_to_primary
        and bool(source_is_primary)
        and not any(source_is_primary)
    )


def evidence_state_from_claim_verification(
    verdict: ClaimSupport,
    *,
    citation_accepted: bool | None = None,
    is_primary_source: bool = True,
) -> EvidenceState:
    """Project a claim verdict onto the existing `EvidenceState` taxonomy.

    Reuses `classify_evidence_state` rather than re-deriving its
    priority rules: a contradicted claim maps straight to
    `CONTRADICTED`; a supported one is handed to the existing
    classifier as an explicit, backend-checked fact; anything the
    verifier could not confirm collapses to `UNKNOWN`, the same state a
    citation with no usable source pointer already gets.

    Inherits `classify_evidence_state`'s existing priority order as-is,
    including that EXPLICIT certainty maps to `VERIFIED` regardless of
    `is_primary_source` -- so a SUPPORTED verdict alone does not surface
    the xp-05 primary/supporting contamination case. Call
    `detect_primary_supporting_contamination` for that; it is a
    deliberately separate check rather than folded in here, since fixing
    it inside `classify_evidence_state` would change already-reviewed
    Phase 8.1 production behaviour this phase has no mandate to alter.
    """
    if verdict == ClaimSupport.CONTRADICTED:
        return EvidenceState.CONTRADICTED
    if verdict == ClaimSupport.SUPPORTED:
        from app.modules.research.schemas import ResearchCertainty

        return classify_evidence_state(
            certainty=ResearchCertainty.EXPLICIT,
            citation_accepted=citation_accepted,
            is_primary_source=is_primary_source,
            has_source_evidence=True,
        )
    return EvidenceState.UNKNOWN
