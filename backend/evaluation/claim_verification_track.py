"""Track C -- claim-level evidence verification (Sprint 16 Phase 8.5).

Runs the real `app.modules.research.claim_verification` functions
against `gold_claim_verification.json`, whose cases are real text from
Phase 8.4 research runs and the real aguilar_cti PDF (see that file's
`_provenance`), plus the one Phase 8.1 synthetic scenario (xp-05) this
phase's contamination check was built to catch.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.research.claim_verification import (
    ClaimSupport,
    SufficiencyVerdict,
    classify_false_insufficiency,
    detect_primary_supporting_contamination,
    verify_categorical_claim,
    verify_numeric_claim,
)
from evaluation.metrics import binary_confusion, multiclass_report

GOLD_PATH = Path(__file__).parent / "gold_claim_verification.json"

_SUPPORT_LABELS = [v.value for v in ClaimSupport]
_SUFFICIENCY_LABELS = [v.value for v in SufficiencyVerdict]


def _load() -> dict:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def run_claim_support(cases: list[dict], *, kind: str) -> dict:
    """Shared scorer for both `numeric_claims` and `categorical_claims`.

    Returns per-case results plus the multiclass report and two binary
    views the report needs: "contradiction detection" (CONTRADICTED vs
    everything else) and "unsupported-claim detection" (CONTRADICTED or
    UNVERIFIABLE, i.e. not actually backed, vs SUPPORTED/INSUFFICIENT).
    """
    pairs, contradiction_pairs, unsupported_pairs, examples = [], [], [], []
    for case in cases:
        if kind == "numeric":
            result = verify_numeric_claim(
                claimed_value=case["claimed_value"],
                is_aggregate_claim=case["is_aggregate_claim"],
                evidence=[tuple(e) for e in case["evidence"]],
            )
        else:
            result = verify_categorical_claim(
                claim_text=case["claim_text"],
                evidence=[tuple(e) for e in case["evidence"]],
                contradicting_phrases=case.get("contradicting_phrases"),
            )
        gold = case["gold_verdict"]
        predicted = result.verdict.value
        pairs.append((predicted, gold))
        contradiction_pairs.append((predicted == "contradicted", gold == "contradicted"))
        unsupported_pairs.append(
            (predicted in ("contradicted", "unverifiable"), gold in ("contradicted", "unverifiable"))
        )
        examples.append(
            {
                "id": case["id"],
                "description": case["description"],
                "predicted": predicted,
                "gold": gold,
                "correct": predicted == gold,
                "matched_evidence_ids": result.matched_evidence_ids,
                "reason": result.reason,
            }
        )

    report = multiclass_report(pairs, _SUPPORT_LABELS)
    return {
        "accuracy": round(report.accuracy, 4),
        "confusion_matrix": report.confusion_matrix(),
        "contradiction_detection": binary_confusion(contradiction_pairs).as_dict(),
        "unsupported_claim_detection": binary_confusion(unsupported_pairs).as_dict(),
        "examples": examples,
    }


def run_sufficiency(cases: list[dict]) -> dict:
    pairs, examples = [], []
    for case in cases:
        predicted = classify_false_insufficiency(
            claimed_insufficient=case["claimed_insufficient"],
            evidence_supplied=case["evidence_supplied"],
            required_values=case["required_values"],
        ).value
        gold = case["gold_verdict"]
        pairs.append((predicted, gold))
        examples.append(
            {
                "id": case["id"],
                "description": case["description"],
                "predicted": predicted,
                "gold": gold,
                "correct": predicted == gold,
            }
        )

    report = multiclass_report(pairs, _SUFFICIENCY_LABELS)
    return {
        "accuracy": round(report.accuracy, 4),
        "confusion_matrix": report.confusion_matrix(),
        "examples": examples,
    }


def run_contamination(cases: list[dict]) -> dict:
    pairs, examples = [], []
    for case in cases:
        predicted = detect_primary_supporting_contamination(
            claim_attributed_to_primary=case["claim_attributed_to_primary"],
            source_is_primary=case["source_is_primary"],
        )
        gold = case["gold_contamination"]
        pairs.append((predicted, gold))
        examples.append(
            {
                "id": case["id"],
                "description": case["description"],
                "predicted": predicted,
                "gold": gold,
                "correct": predicted == gold,
            }
        )

    return {
        "metrics": binary_confusion(pairs).as_dict(),
        "examples": examples,
    }


def run() -> dict:
    gold = _load()
    return {
        "provenance": gold["_provenance"],
        "numeric_claims": run_claim_support(gold["numeric_claims"], kind="numeric"),
        "categorical_claims": run_claim_support(gold["categorical_claims"], kind="categorical"),
        "sufficiency_claims": run_sufficiency(gold["sufficiency_claims"]),
        "primary_supporting_contamination": run_contamination(
            gold["primary_supporting_contamination"]
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
