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
