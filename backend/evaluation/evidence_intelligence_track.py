"""Track B -- evidence-intelligence evaluation (Sprint 16 Phase 8.1).

No live LLM is reachable in this environment (local Ollama at
`OLLAMA_BASE_URL` refused the connection when checked for this phase --
see the Phase 8.1 report). Every "model output" in
`gold_evidence_intelligence.json` is therefore a hand-authored MOCKED
stand-in for what an LLM call would return, clearly labeled as such.

What is REAL in this track: every mocked output is run through the
actual, unmodified production verification code --
`app.agents.planner.synthesis._validate_citation_ids` /
`_grounding_status`, `app.agents.planner.cross_paper._validate_cross_paper_result`,
and the new `app.modules.research.evidence_state.classify_evidence_state`.
Sub-tracks with no backend verification at all (sufficiency, gap
classification, contradiction detection) are scored as "LLM-only",
because that is the entire pipeline that exists for them today -- the
harness cannot invent a verifier production doesn't have.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.agents.planner.cross_paper import (
    CrossPaperValidationException,
    _validate_cross_paper_result,
)
from app.agents.planner.synthesis import _grounding_status, _validate_citation_ids
from app.modules.research.evidence_state import EvidenceState, classify_evidence_state
from app.modules.research.schemas import (
    ComparisonItem,
    ComparisonRelationship,
    CrossPaperComparison,
    ResearchCertainty,
    ResearchHypothesis,
    SourceReference,
)
from evaluation.metrics import binary_confusion, multiclass_report

GOLD_PATH = Path(__file__).parent / "gold_evidence_intelligence.json"


def _load() -> dict:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Citation grounding: LLM-only vs LLM+verification
# ---------------------------------------------------------------------------

_GROUNDING_LABELS = ["grounded", "partially_grounded", "insufficient_evidence", "failed"]


def run_citation_grounding(cases: list[dict]) -> dict:
    llm_only_pairs, verified_pairs = [], []
    examples = []
    for case in cases:
        supplied = case["supplied_citations"]
        accepted, rejected = _validate_citation_ids(case["claimed_cited_ids"], supplied)
        verified_status = _grounding_status(
            claimed_status=case["claimed_grounding_status"], accepted=accepted, rejected=rejected
        ).value

        llm_only_pairs.append((case["claimed_grounding_status"], case["gold_grounding_status"]))
        verified_pairs.append((verified_status, case["gold_grounding_status"]))
        examples.append({
            "id": case["id"], "description": case["description"],
            "claimed": case["claimed_grounding_status"], "gold": case["gold_grounding_status"],
            "verified": verified_status,
            "verification_corrected_a_wrong_claim": (
                case["claimed_grounding_status"] != case["gold_grounding_status"]
                and verified_status == case["gold_grounding_status"]
            ),
        })

    return {
        "llm_only_accuracy": round(sum(p == a for p, a in llm_only_pairs) / len(llm_only_pairs), 4),
        "llm_plus_verification_accuracy": round(
            sum(p == a for p, a in verified_pairs) / len(verified_pairs), 4
        ),
        "llm_only_report": multiclass_report(llm_only_pairs, _GROUNDING_LABELS).confusion_matrix(),
        "verified_report": multiclass_report(verified_pairs, _GROUNDING_LABELS).confusion_matrix(),
        "examples": examples,
    }


# ---------------------------------------------------------------------------
# Cross-paper structural validation
# ---------------------------------------------------------------------------

def _build_comparison(case: dict) -> CrossPaperComparison:
    items = [
        ComparisonItem(
            topic=i["topic"], primary_claim=i["primary_claim"],
            supporting_claims=i["supporting_claims"],
            relationship=ComparisonRelationship(i["relationship"]),
            evidence=i["evidence"], certainty=ResearchCertainty(i["certainty"]),
            source_references=[
                SourceReference(paper_id=uuid.UUID(r["paper_id"]), paper_title=r["paper_title"], page=r.get("page"))
                for r in i["source_references"]
            ],
        )
        for i in case["comparison_items"]
    ]
    hypotheses = [
        ResearchHypothesis(
            description=h["description"],
            supporting_sources=[
                SourceReference(paper_id=uuid.UUID(s["paper_id"]), paper_title=s["paper_title"])
                for s in h["supporting_sources"]
            ],
            rationale=h["rationale"], certainty=ResearchCertainty(h["certainty"]),
        )
        for h in case["hypotheses"]
    ]
    return CrossPaperComparison(
        primary_paper_id=uuid.UUID(case["primary_id"]),
        supporting_paper_ids=[uuid.UUID(s) for s in case["supporting_ids"]],
        comparison_items=items, gap_resolutions=[], hypotheses=hypotheses,
    )


def run_cross_paper_structural(cases: list[dict]) -> dict:
    pairs = []
    examples = []
    for case in cases:
        comparison = _build_comparison(case)
        try:
            _validate_cross_paper_result(
                comparison, uuid.UUID(case["primary_id"]), {uuid.UUID(s) for s in case["supporting_ids"]}
            )
            actually_passed = True
        except CrossPaperValidationException:
            actually_passed = False

        pairs.append((actually_passed, case["gold_should_pass_validation"]))
        examples.append({
            "id": case["id"], "description": case["description"],
            "gold_should_pass": case["gold_should_pass_validation"],
            "actually_passed": actually_passed,
            "violation_rule": case.get("gold_violation_rule"),
            "caught_by_real_validator": actually_passed == case["gold_should_pass_validation"],
        })

    confusion = binary_confusion(pairs)
    return {
        "note": "predicted=validator_passed, actual=gold_should_pass -- a mismatch means the "
                "real validator disagreed with the gold label (either missed a real flaw, or "
                "rejected valid output).",
        "metrics": confusion.as_dict(),
        "examples": examples,
        "detected_but_not_structurally_catchable": [
            e["id"] for e in examples
            if e["violation_rule"] == "primary_supporting_merge_not_structurally_detectable"
            and e["actually_passed"]
        ],
    }


# ---------------------------------------------------------------------------
# Sufficiency / gap / contradiction -- no backend oracle exists
# ---------------------------------------------------------------------------

def run_sufficiency_gap_contradiction(cases: list[dict]) -> dict:
    sufficiency_pairs, examples = [], []
    for case in cases:
        sufficiency_pairs.append((case["claimed_sufficiency"], case["gold_sufficiency"]))
        # "Verification" for this dimension is a no-op in production today --
        # there is no function to call here, which is itself the finding.
        # LLM-only and LLM+verification are therefore identical.
        examples.append({
            "id": case["id"], "description": case["description"],
            "claimed_sufficiency": case["claimed_sufficiency"], "gold_sufficiency": case["gold_sufficiency"],
            "sufficiency_claim_correct": case["claimed_sufficiency"] == case["gold_sufficiency"],
            "gaps_match_gold": case["claimed_gaps"] == case["gold_gaps_expected"],
            "conflicts_match_gold": case["claimed_conflicts"] == case["gold_conflicts_expected"],
            "is_flawed_llm_output": case["is_flawed_llm_output"],
        })

    sufficiency_labels = ["sufficient", "partially_sufficient", "insufficient", "ambiguous"]
    flawed = [e for e in examples if e["is_flawed_llm_output"]]
    return {
        "note": "No production code verifies sufficiency/gap/contradiction claims against source "
                "text (confirmed absent by codebase survey) -- 'LLM-only' is the entire pipeline. "
                "'llm_plus_verification_catch_rate' is reported as 0.0 by construction, not "
                "measured error: there is nothing for a harness to invoke that would catch these "
                "injected errors, which is the gap this section documents.",
        "llm_only_sufficiency_accuracy": round(
            sum(p == a for p, a in sufficiency_pairs) / len(sufficiency_pairs), 4
        ),
        "llm_only_sufficiency_report": multiclass_report(sufficiency_pairs, sufficiency_labels).confusion_matrix(),
        "injected_error_scenarios": len(flawed),
        "llm_plus_verification_catch_rate": 0.0,
        "examples": examples,
    }


# ---------------------------------------------------------------------------
# Evidence-state classification (new, additive, pure function)
# ---------------------------------------------------------------------------

_STATE_LABELS = [s.value for s in EvidenceState]


def run_evidence_state(cases: list[dict]) -> dict:
    pairs, examples = [], []
    for case in cases:
        relationship = ComparisonRelationship(case["relationship"]) if case["relationship"] else None
        predicted = classify_evidence_state(
            certainty=ResearchCertainty(case["certainty"]) if case["certainty"] else None,
            relationship=relationship,
            citation_accepted=case["citation_accepted"],
            is_primary_source=case["is_primary_source"],
            has_source_evidence=case["has_source_evidence"],
        ).value
        pairs.append((predicted, case["gold_state"]))
        examples.append({
            "id": case["id"], "description": case["description"],
            "predicted": predicted, "gold": case["gold_state"], "correct": predicted == case["gold_state"],
        })

    report = multiclass_report(pairs, _STATE_LABELS)
    return {
        "accuracy": round(report.accuracy, 4),
        "per_class": report.per_class(),
        "confusion_matrix": report.confusion_matrix(),
        "examples": examples,
    }


def run() -> dict:
    gold = _load()
    return {
        "provenance": gold["_provenance"],
        "citation_grounding": run_citation_grounding(gold["citation_grounding"]),
        "cross_paper_structural": run_cross_paper_structural(gold["cross_paper_structural"]),
        "sufficiency_gap_contradiction": run_sufficiency_gap_contradiction(gold["sufficiency_gap_contradiction"]),
        "evidence_state": run_evidence_state(gold["evidence_state"]),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
