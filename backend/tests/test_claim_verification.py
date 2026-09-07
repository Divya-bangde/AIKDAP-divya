"""Sprint 16 Phase 8.5 -- claim-level evidence verification.

The three real-text regression cases below are copied verbatim from
real Phase 8.4 research runs (run ids in each test's docstring) rather
than paraphrased, so a change that breaks the exact behaviour observed
on real model output fails here first.
"""

from app.modules.research.claim_verification import (
    ClaimSupport,
    SufficiencyVerdict,
    classify_false_insufficiency,
    detect_primary_supporting_contamination,
    evidence_state_from_claim_verification,
    verify_categorical_claim,
    verify_numeric_claim,
)
from app.modules.research.evidence_state import EvidenceState


def test_aggregate_claim_contradicted_when_only_component_scoped():
    """Real Phase 8.4 failure: run 23d1361f-9d05-4d86-8f0f-a9705773a19b
    (aguilar_cti). Qwen reported "73.5%" as the overall pass rate; every
    cited occurrence of 73.5% is the S4 row of a per-strategy table.
    """
    evidence = [
        (
            "c1",
            "S0: Baseline 200 3.60 3.77 3.30 2.96 3.50 / 61.0% S1: Template 200 3.22 "
            "3.20 3.53 2.85 3.22 / 1.5% S4: One-Shot + BLUF 200 3.55 3.35 3.70 4.07 "
            "3.60 / 73.5% Figure 1: Prompt Strategy Summary (AI-Instrument Scoring, N = 1,000)",
        ),
        (
            "c2",
            "At the S4 configuration's 73.5% AI-instrument pass rate, and assuming the "
            "26.5% of failing reports still require meaningful analyst revision...",
        ),
        (
            "c4",
            "Gemma3:27b ... produced passing-quality executive CTI reports at a 73.5% "
            "rate under the S4 prompt configuration per AI-instrument scoring...",
        ),
    ]
    result = verify_numeric_claim(claimed_value="73.5%", is_aggregate_claim=True, evidence=evidence)
    assert result.verdict == ClaimSupport.CONTRADICTED
    assert set(result.matched_evidence_ids) == {"c1", "c2", "c4"}


# ---------------------------------------------------------------------------
# Sprint 16 Phase 8.8 -- aggregate/component false-positive hardening.
#
# The real Phase 8.7 production false positive: a claim asserting the
# dataset's real aggregate size ("1,000" reports) was marked CONTRADICTED
# because `_COMPONENT_LABEL` searched the *entire* evidence block for a
# strategy code, found "S4:" from an unrelated per-strategy table sharing
# the same chunk, and never checked whether "S4:" was anywhere near the
# claimed value "1,000" itself (it is not -- "1,000" appears ~120
# characters later, next to "Figure 1:"). Fixed by scoping the component
# search to a local window around each occurrence of the claimed value.
# ---------------------------------------------------------------------------


def test_exact_phase_8_7_production_false_positive_now_supported():
    """Real: run 249d1e9b-b445-48a2-a829-1909b55dc487 (aguilar_cti, Phase
    8.7 production). Qwen claimed "The dataset included 1,000 reports
    evaluated across five prompt strategies" (scope=aggregate,
    claimed_value="1,000"), citing c1. `evidence_state` was CONTRADICTED
    in production; the real aggregate figure ("N = 1,000") is genuine and
    sits far from every per-strategy row in the same chunk.
    """
    c1 = (
        "he mean composite scores, dimension scores, and pass rates for each of the five prompt "
        "strategies. Strategy N Avg Action. Avg Rigor Avg Language Avg Structure Composite / Pass % "
        "S0: Baseline 200 3.60 3.77 3.30 2.96 3.50 / 61.0% S1: Template 200 3.22 3.20 3.53 2.85 3.22 / "
        "1.5% S2: Template + BLUF 200 3.28 3.19 3.58 3.68 3.37 / 20.0% S3: One-Shot Template 200 3.37 "
        "3.54 3.66 3.14 3.44 / 38.0% S4: One-Shot + BLUF 200 3.55 3.35 3.70 4.07 3.60 / 73.5% Figure 1: "
        "Prompt Strategy Summary (AI-Instrument Scoring, N = 1,000) 3.2.1 The Underperformance of S1 "
        "The most counterintuitive finding in the dataset is S1's severe under performance relative to "
        "the unstructured baseline S0. The addition of a..."
    )
    result = verify_numeric_claim(
        claimed_value="1,000", is_aggregate_claim=True, evidence=[("c1", c1)]
    )
    assert result.verdict == ClaimSupport.SUPPORTED


def test_genuine_component_vs_aggregate_contradiction_still_caught():
    """A component label immediately adjacent to the claimed value must
    still contradict an aggregate claim -- the fix narrows the search
    window, it must not blind the check entirely. Same real 73.5% case
    as the test above this section.
    """
    evidence = [
        ("c1", "S4: One-Shot + BLUF 200 3.55 3.35 3.70 4.07 3.60 / 73.5% Figure 1: Prompt Strategy Summary."),
        ("c2", "At the S4 configuration's 73.5% AI-instrument pass rate, and assuming..."),
        ("c4", "produced passing-quality executive CTI reports at a 73.5% rate under the S4 prompt configuration."),
    ]
    result = verify_numeric_claim(claimed_value="73.5%", is_aggregate_claim=True, evidence=evidence)
    assert result.verdict == ClaimSupport.CONTRADICTED


def test_genuine_supported_aggregate_with_component_table_in_same_chunk():
    """Real: run 084a9ed7-2573-4421-a09a-28fbbc637a0d (aguilar_cti,
    Phase 8.6 held-out). "38.8%" is the real, correctly-cited aggregate
    figure, explicitly under an "Overall Performance and Aggregate
    Findings" heading -- and the SAME evidence chunk elsewhere still
    contains no component label near 38.8% itself.
    """
    c5 = (
        "ompt configuration achieves a 73.5% pass rate, while the least effective achieves a 1.5% pass "
        "rate. A subsequent human-analyst inter-rater exercise revealed a 61.7% verdict-flip rate across "
        "60 dual-scored reports, establishing that the AI scoring instrument overestimated quality in a "
        "significant proportion of cases. The findings establish that model capability alone is neither "
        "the limiting factor nor the reliable determinant of output quality. 3.1 Overall Performance and "
        "Aggregate Findings Of the 1,000 AI-generated reports scored against the four-dimension composite "
        "rubric, 388 (38.8%) met or exceeded the ≥3.5 quality threshold under AI-instrument scoring."
    )
    result = verify_numeric_claim(claimed_value="38.8%", is_aggregate_claim=True, evidence=[("c5", c5)])
    assert result.verdict == ClaimSupport.SUPPORTED


def test_unrelated_component_label_far_from_claimed_value_is_ignored():
    """A component label present in the same chunk but nowhere near the
    claimed value's own occurrence must not contradict it -- this is the
    exact bug class (global scan vs. local context), stated as its own
    minimal case independent of any one paper's real wording.
    """
    text = (
        "S4: One-Shot + BLUF 200 3.55 3.35 3.70 4.07 3.60 / 73.5% Figure 1: Prompt Strategy Summary. "
        + ("filler text keeps this evidence chunk long and unrelated to any strategy. " * 10)
        + "3.1 Overall Performance: 388 of 1,000 reports met the quality threshold, an overall rate of 38.8%."
    )
    result = verify_numeric_claim(claimed_value="1,000", is_aggregate_claim=True, evidence=[("c1", text)])
    assert result.verdict == ClaimSupport.SUPPORTED


def test_non_aggregate_numeric_claim_supported():
    evidence = [("c1", "S4: One-Shot + BLUF ... 3.60 / 73.5%")]
    result = verify_numeric_claim(claimed_value="73.5%", is_aggregate_claim=False, evidence=evidence)
    assert result.verdict == ClaimSupport.SUPPORTED


def test_numeric_claim_unverifiable_when_value_absent():
    evidence = [("c1", "S0: Baseline 200 ... 3.50 / 61.0%")]
    result = verify_numeric_claim(claimed_value="99.9%", is_aggregate_claim=True, evidence=evidence)
    assert result.verdict == ClaimSupport.UNVERIFIABLE


def test_numeric_claim_insufficient_evidence_when_nothing_cited():
    result = verify_numeric_claim(claimed_value="73.5%", is_aggregate_claim=True, evidence=[])
    assert result.verdict == ClaimSupport.INSUFFICIENT_EVIDENCE


def test_categorical_claim_supported_verbatim():
    """Real: run 50163fe6-5f61-4cf7-935a-70f23719aad2 (sinanian_lte)."""
    claim = (
        "Allowlist suppression raised stalkerware family detection within a "
        "ten-flow review budget from just two out of five families to all five families."
    )
    evidence = [
        (
            "c1",
            "The results revealed that the allowlist suppression was the decisive "
            "factor, raising detection within a ten-flow review budget from just two "
            "out of five families to all five. A quantitative...",
        )
    ]
    result = verify_categorical_claim(claim_text=claim, evidence=evidence)
    assert result.verdict == ClaimSupport.SUPPORTED
    assert result.matched_evidence_ids == ["c1"]


def test_categorical_claim_contradicted_by_known_alternate():
    """Real: aguilar_cti's own source text disagrees with itself (Phase 8.2
    document-understanding conflict) -- chunk 24 names Claude Sonnet 4.6 as
    the scoring instrument, chunks 42-44 name Gemma3.
    """
    claim = "Reports were submitted to Claude (Sonnet 4.6) ... the scoring instrument"
    evidence = [
        ("chunk-24", "Reports were submitted to Claude (Sonnet 4.6) in randomized batches..."),
        ("chunk-42", "Gemma3 Pass -> Human Fail 17 28.3% Model over-credited report quality"),
    ]
    result = verify_categorical_claim(
        claim_text=claim, evidence=evidence, contradicting_phrases=["Gemma3"]
    )
    assert result.verdict == ClaimSupport.CONTRADICTED
    assert result.matched_evidence_ids == ["chunk-42"]


def test_categorical_claim_unverifiable_when_unrelated():
    result = verify_categorical_claim(
        claim_text="The model achieved state-of-the-art results on ImageNet.",
        evidence=[("c1", "This paper studies stalkerware detection over LTE traffic.")],
    )
    assert result.verdict == ClaimSupport.UNVERIFIABLE


# ---------------------------------------------------------------------------
# Sprint 16 Phase 8.9 -- categorical paraphrase matching.
#
# `_shares_long_ngram` (above) only fires on a contiguous verbatim run,
# so it misses a claim that states the same fact with different word
# order or number spelling. `_token_set_supported` adds an
# order-independent, negation-guarded containment check; the two run in
# OR, since removing the verbatim check breaks
# `test_categorical_claim_supported_verbatim` above (see that function's
# docstring in claim_verification.py: the real cited text there says
# "families"/"raising" where the claim says "family"/"raised", and this
# phase deliberately does not stem words).
#
# The reproduction case named in this phase's brief -- "raised detection
# ... from two to five families" -- is `test_categorical_claim_supported_verbatim`
# itself: run through `verify_categorical_claim` before this phase's
# change, it was ALREADY correctly SUPPORTED (the verbatim run survives
# every real phrasing captured in Phase 8.5-8.8 production data). The
# case below is a real reordering of the same fact that the *old* code
# also happened to pass (the anchor phrase "within a ten-flow review
# budget" stays intact even after reordering), so it is not, by itself,
# a before/after fix -- it is the target class of paraphrase this phase
# exists to cover, verified via the new mechanism specifically, not
# lucky verbatim survival. See the phase report for the full
# before/after table across every real categorical claim captured in
# 8.6-8.8 production data.
# ---------------------------------------------------------------------------


def test_categorical_paraphrase_reordered_clause_now_supported_via_token_set():
    """Real evidence (sinanian_lte c1), reordered claim clauses.

    Moving "within a ten-flow review budget" to the front breaks the
    contiguous run `_shares_long_ngram` looks for starting from
    "allowlist"; `_token_set_supported` (order-independent within its
    window) still finds every content token of the claim inside one
    stretch of the evidence.
    """
    claim = (
        "Within a ten-flow review budget, allowlist suppression raised "
        "stalkerware family detection from two out of five families to all five."
    )
    evidence = [
        (
            "c1",
            "The results revealed that the allowlist suppression was the decisive "
            "factor, raising detection within a ten-flow review budget from just two "
            "out of five families to all five. A quantitative...",
        )
    ]
    result = verify_categorical_claim(claim_text=claim, evidence=evidence)
    assert result.verdict == ClaimSupport.SUPPORTED


def test_categorical_paraphrase_digit_grouping_normalized():
    """"1,000" (claim) vs "1000" (evidence) -- the comma-grouping rule."""
    result = verify_categorical_claim(
        claim_text="The dataset contained 1,000 executive reports evaluated in this study overall.",
        evidence=[(
            "c1",
            "In total the dataset contained 1000 executive reports evaluated in this overall study.",
        )],
    )
    assert result.verdict == ClaimSupport.SUPPORTED


def test_categorical_paraphrase_number_word_normalized():
    """"two" (claim) vs "2" (evidence) -- the number-word rule."""
    result = verify_categorical_claim(
        claim_text="Only two commercial vendors were evaluated in the baseline experiment overall.",
        evidence=[(
            "c1",
            "The baseline experiment overall evaluated only 2 commercial vendors.",
        )],
    )
    assert result.verdict == ClaimSupport.SUPPORTED


def test_categorical_paraphrase_stays_unverifiable_when_synonym_not_literal():
    """Real: run 1d8bc5de-fdfd-446d-b218-e9496448bcc5 (aguilar_cti production).

    "Corresponds to" / "configuration" are never literally in the cited
    text -- only "S4: One-Shot + BLUF" is. Neither the verbatim-run nor
    the token-set check can bridge a synonym the source never uses, and
    this phase adds no synonym table, embeddings, or LLM call to do so:
    staying UNVERIFIABLE here is the correct, safe outcome, not a gap to
    close.
    """
    claim = "The S4 strategy corresponds to the 'One-Shot + BLUF' configuration."
    evidence = [
        (
            "c1",
            "he mean composite scores, dimension scores, and pass rates for each of "
            "the five prompt strategies. Strategy N Avg Action. Avg Rigor Avg Language "
            "Avg Structure Composite / Pass % S0: Baseline 200 3.60 3.77 3.30 2.96 3.50 "
            "/ 61.0% S1: Template 200 3.22 3.20 3.53 2.85 3.22 / 1.5% S2: Template + BLUF "
            "200 3.28 3.19 3.58 3.68 3.37 / 20.0% S3: One-Shot Template 200 3.37 3.54 "
            "3.66 3.14 3.44 / 38.0% S4: One-Shot + BLUF 200 3.55 3.35 3.70 4.07 3.60 / "
            "73.5% Figure 1: Prompt Strategy Summary",
        )
    ]
    result = verify_categorical_claim(claim_text=claim, evidence=evidence)
    assert result.verdict == ClaimSupport.UNVERIFIABLE


# --- Safety tests (the deliverable): every one of these must stay
# UNVERIFIABLE/CONTRADICTED. A single false SUPPORTED here means the
# offending normalization rule must be deleted, per this phase's abort
# condition -- see the phase report for the two pre-existing false
# positives this table actually caught in `_shares_long_ngram` (fixed by
# raising its `min_words` from 6 to 8, not by touching the new rule).


def test_safety_similar_words_different_meaning_stays_unverifiable():
    """SYNTHETIC: 'false positives' vs 'true positives' -- one word apart, opposite claim."""
    result = verify_categorical_claim(
        claim_text="The framework achieved zero false positives across all test cases.",
        evidence=[(
            "c1",
            "The framework achieved zero true positives across all test cases, "
            "missing every real intrusion.",
        )],
    )
    assert result.verdict == ClaimSupport.UNVERIFIABLE


def test_safety_partial_support_stays_unverifiable():
    """SYNTHETIC: the claim's extra clause ('zero false positives') is never stated.

    Also the regression case that caught `_shares_long_ngram`'s own
    false positive this phase: a 6-word shared prefix is not enough
    signal once the claim continues past it into unstated territory.
    """
    result = verify_categorical_claim(
        claim_text="The system detected all five malware families with zero false positives.",
        evidence=[("c1", "The system detected all five malware families in the test set.")],
    )
    assert result.verdict == ClaimSupport.UNVERIFIABLE


def test_safety_related_but_different_numbers_stays_unverifiable():
    """SYNTHETIC: 91% claimed, source says 89% -- digit normalization must not blur this."""
    result = verify_categorical_claim(
        claim_text="Detection accuracy improved from 62% to 91% after tuning.",
        evidence=[("c1", "Detection accuracy improved from 62% to 89% after tuning.")],
    )
    assert result.verdict == ClaimSupport.UNVERIFIABLE


def test_safety_negated_source_stays_unverifiable():
    """SYNTHETIC, isolates the negation guard: every claim token literally

    appears in the evidence (containment alone would say SUPPORTED) --
    only the added "not" distinguishes them. Without the negation guard
    this would be the exact "same tokens, opposite meaning" false
    positive the guard exists to catch.
    """
    result = verify_categorical_claim(
        claim_text="Support for offline mode is present in this release.",
        evidence=[("c1", "Support for offline mode is not present in this release.")],
    )
    assert result.verdict == ClaimSupport.UNVERIFIABLE


def test_safety_same_entities_different_relationship_stays_unverifiable():
    """Real evidence (vaniscak_c2 c1), wrong entity attribution.

    The source says "Traffic Patterns proved most viable"; this claim
    misattributes that same property to "Traffic Metadata", a different
    entity thirteen content-tokens away in the same chunk. Whole-chunk
    containment would wrongly say SUPPORTED (both entities and "most
    viable" all appear somewhere in the chunk); the bounded window in
    `_token_set_supported` requires them to co-occur locally, which they
    do not.
    """
    evidence_text = (
        "sing 51 packet captures (3 baselines, 6 automated browser tests and 6 framework "
        "tests per service). Across four detection tiers, Reputation-based detection failed "
        "to identify any C2 channels; Beacon Detection was marginally viable when using "
        "clustering (2/4); Traffic Metadata was partially viable, with mixed results other "
        "than JA4 fingerprints (100% detection); and Traffic Patterns proved most viable, "
        "with both TLS session resumption near-zero (vs 22%+ for browser) and a 2.6x "
        "upload/download ratio gap (1.41 vs 0.55 means)."
    )
    result = verify_categorical_claim(
        claim_text="Traffic Metadata was most viable for detection.",
        evidence=[("c1", evidence_text)],
    )
    assert result.verdict == ClaimSupport.UNVERIFIABLE

    # Sanity check: the CORRECT attribution for the same real evidence
    # must still be reachable, proving the window isn't simply too
    # narrow to ever match anything.
    correct = verify_categorical_claim(
        claim_text="Traffic Patterns was most viable for detection.",
        evidence=[("c1", evidence_text)],
    )
    assert correct.verdict == ClaimSupport.SUPPORTED


def test_safety_ambiguous_wording_negated_in_source_stays_unverifiable():
    """SYNTHETIC: a vague claim ('results were significant') that containment

    alone would accept because every one of its few tokens appears in
    the source -- the source's own hedge ("not statistically
    significant") is exactly what the negation guard is for.
    """
    result = verify_categorical_claim(
        claim_text="The results were significant.",
        evidence=[(
            "c1",
            "The results were not statistically significant across all metrics.",
        )],
    )
    assert result.verdict == ClaimSupport.UNVERIFIABLE


def test_false_insufficiency_when_evidence_has_the_value():
    """Real: run 637d6cf1-1f5e-470e-9332-431b6e0ca575 (vaniscak_c2). Qwen
    declined to answer despite the supplied evidence stating "JA4
    fingerprints (100% detection)" -- the highest rate in the evidence set.
    """
    verdict = classify_false_insufficiency(
        claimed_insufficient=True,
        evidence_supplied=[
            "Traffic Metadata was partially viable, with mixed results other than "
            "JA4 fingerprints (100% detection); and Traffic Patterns proved most "
            "viable, with both TLS session resumption near-zero (vs 22%+ for browser) "
            "and a 2.6x upload/download ratio gap.",
        ],
        required_values=["100% detection"],
    )
    assert verdict == SufficiencyVerdict.MODEL_FAILED_TO_USE_SUFFICIENT_EVIDENCE


def test_source_insufficient_when_evidence_genuinely_lacks_it():
    """Real: run 80f5f264-a55a-4e72-a4ce-78e7a5c73b3b (aguilar_cti,
    unanswerable/SQuAD question). All 5 retrieved chunks were withheld by
    the relevance gate as irrelevant; no grounded evidence ever reached
    synthesis, and the paper genuinely does not discuss SQuAD.
    """
    verdict = classify_false_insufficiency(
        claimed_insufficient=True, evidence_supplied=[], required_values=["SQuAD"]
    )
    assert verdict == SufficiencyVerdict.SOURCE_INSUFFICIENT


def test_not_applicable_when_model_did_not_claim_insufficiency():
    verdict = classify_false_insufficiency(
        claimed_insufficient=False, evidence_supplied=["anything"], required_values=["100%"]
    )
    assert verdict == SufficiencyVerdict.NOT_APPLICABLE


def test_primary_supporting_contamination_detected():
    """Phase 8.1 xp-05 (synthetic, gold_evidence_intelligence.json): primary_claim
    'Primary paper reports 97% accuracy' whose only source_reference is the
    supporting paper.
    """
    assert detect_primary_supporting_contamination(
        claim_attributed_to_primary=True, source_is_primary=[False]
    )


def test_no_contamination_when_a_primary_source_backs_it():
    assert not detect_primary_supporting_contamination(
        claim_attributed_to_primary=True, source_is_primary=[True, False]
    )


def test_no_contamination_when_claim_not_attributed_to_primary():
    assert not detect_primary_supporting_contamination(
        claim_attributed_to_primary=False, source_is_primary=[False]
    )


def test_evidence_state_bridge_contradicted():
    assert (
        evidence_state_from_claim_verification(ClaimSupport.CONTRADICTED)
        == EvidenceState.CONTRADICTED
    )


def test_evidence_state_bridge_supported_uses_existing_classifier():
    """A SUPPORTED verdict is always passed to `classify_evidence_state` as
    an explicit fact, so it inherits that function's existing priority
    order verbatim -- including the fact that EXPLICIT certainty maps to
    VERIFIED regardless of `is_primary_source`. That is why
    `detect_primary_supporting_contamination` exists as a separate check:
    this bridge does not, by itself, catch a supported claim whose only
    source is a supporting paper.
    """
    assert (
        evidence_state_from_claim_verification(
            ClaimSupport.SUPPORTED, citation_accepted=True, is_primary_source=True
        )
        == EvidenceState.VERIFIED
    )
    assert (
        evidence_state_from_claim_verification(
            ClaimSupport.SUPPORTED, citation_accepted=None, is_primary_source=False
        )
        == EvidenceState.VERIFIED
    )


def test_evidence_state_bridge_unverifiable_and_insufficient_are_unknown():
    assert evidence_state_from_claim_verification(ClaimSupport.UNVERIFIABLE) == EvidenceState.UNKNOWN
    assert (
        evidence_state_from_claim_verification(ClaimSupport.INSUFFICIENT_EVIDENCE)
        == EvidenceState.UNKNOWN
    )
