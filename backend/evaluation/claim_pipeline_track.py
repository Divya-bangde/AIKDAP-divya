"""Track D -- Sprint 16 Phase 8.6: answer -> extraction -> binding -> verification -> state.

Evaluation-scoped only. Runs `evaluation.claim_extraction` (this
phase's new rules) and the real, unmodified `app.modules.research.
claim_verification` (Phase 8.5) against `gold_claim_pipeline.json`'s
dev and held-out sets.

The central design choice: every claim-level check is run TWICE --
once against the claim structure GOLD says the answer actually makes,
once against the structure `extract_claims` actually produced -- so a
wrong final verdict can be attributed to extraction (structures
differ) or to verification (structures agree, verdict still wrong)
instead of being reported as one opaque failure. See `run()`'s
docstring for how the two numbers are used.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.research.claim_verification import (
    classify_false_insufficiency,
    detect_primary_supporting_contamination,
    evidence_state_from_claim_verification,
    verify_categorical_claim,
    verify_numeric_claim,
)
from evaluation.claim_extraction import extract_claims

GOLD_PATH = Path(__file__).parent / "gold_claim_pipeline.json"


def _load() -> dict:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def _resolve(ids: list[str], citations: dict[str, str]) -> list[tuple[str, str]]:
    return [(cid, citations[cid]) for cid in ids if cid in citations]


def _verify(claim_type: str, claimed_value: str | None, scope: str | None, evidence: list[tuple[str, str]], claim_text: str):
    if claim_type == "numeric":
        return verify_numeric_claim(
            claimed_value=claimed_value, is_aggregate_claim=(scope == "aggregate"), evidence=evidence
        )
    return verify_categorical_claim(claim_text=claim_text, evidence=evidence)


def score_free_text_case(case: dict) -> dict:
    gold = case["gold"]
    citations = case.get("citations", {})
    result = extract_claims(case["answer_text"], case["run_citation_ids"])

    insufficiency_correct = (
        result.insufficiency.claimed_insufficient == gold["insufficiency"]["claimed_insufficient"]
        and result.insufficiency.source == gold["insufficiency"]["source"]
    )

    record: dict = {
        "id": case["id"],
        "categories": case["categories"],
        "insufficiency": {
            "predicted": {
                "claimed_insufficient": result.insufficiency.claimed_insufficient,
                "source": result.insufficiency.source,
            },
            "gold": gold["insufficiency"],
            "correct": insufficiency_correct,
        },
    }

    # Sufficiency-verdict stage, for cases that carry one (evidence_supplied +
    # required_values are only meaningful once claimed_insufficient is true).
    if "gold_sufficiency_verdict" in gold:
        predicted_sufficiency = classify_false_insufficiency(
            claimed_insufficient=result.insufficiency.claimed_insufficient,
            evidence_supplied=case.get("evidence_supplied", []),
            required_values=case.get("required_values", []),
        ).value
        given_gold_flag_sufficiency = classify_false_insufficiency(
            claimed_insufficient=gold["insufficiency"]["claimed_insufficient"],
            evidence_supplied=case.get("evidence_supplied", []),
            required_values=case.get("required_values", []),
        ).value
        record["sufficiency_verdict"] = {
            "predicted_end_to_end": predicted_sufficiency,
            "predicted_given_gold_insufficiency_flag": given_gold_flag_sufficiency,
            "gold": gold["gold_sufficiency_verdict"],
            "end_to_end_correct": predicted_sufficiency == gold["gold_sufficiency_verdict"],
            "correct_given_gold_flag": given_gold_flag_sufficiency == gold["gold_sufficiency_verdict"],
        }

    # Itemized claim-level stages, only for cases gold bothered to itemize
    # (some insufficiency-focused cases deliberately don't -- see
    # ho-vaniscak-gate-on-r2's claims_note).
    gold_claims = gold.get("claims")
    if gold_claims is None:
        record["claim_extraction"] = {"applicable": False}
        return record

    predicted_claims = result.claims
    count_match = len(predicted_claims) == len(gold_claims)
    record["claim_extraction"] = {
        "applicable": True,
        "expected_count": len(gold_claims),
        "predicted_count": len(predicted_claims),
        "count_match": count_match,
    }

    claim_records = []
    for i, gc in enumerate(gold_claims):
        gold_evidence = _resolve(gc["gold_citation_ids"], citations)
        gold_side_result = _verify(
            gc["claim_type"], gc["claimed_value"], gc["scope"], gold_evidence, gc.get("claim_text", "")
        )
        gold_side_verdict = gold_side_result.verdict.value
        gold_side_state = evidence_state_from_claim_verification(gold_side_result.verdict).value

        entry = {
            "index": i,
            "gold": gc,
            "verification_given_gold_extraction": {
                "verdict": gold_side_verdict,
                "matches_gold_verdict": gold_side_verdict == gc["gold_verdict"],
                "evidence_state": gold_side_state,
                "matches_gold_evidence_state": gold_side_state == gc["gold_evidence_state"],
            },
        }

        if count_match:
            pc = predicted_claims[i]
            fields_match = (
                pc.claim_type == gc["claim_type"]
                and pc.claimed_value == gc["claimed_value"]
                and pc.scope == gc["scope"]
            )
            binding_match = set(pc.source_reference_ids) == set(gc["gold_citation_ids"])
            predicted_evidence = _resolve(pc.source_reference_ids, citations)
            predicted_side_result = _verify(
                pc.claim_type, pc.claimed_value, pc.scope, predicted_evidence, pc.claim_text
            )
            predicted_side_verdict = predicted_side_result.verdict.value
            predicted_side_state = evidence_state_from_claim_verification(
                predicted_side_result.verdict
            ).value

            end_to_end_correct = predicted_side_verdict == gc["gold_verdict"]
            if fields_match and binding_match:
                root_cause = None if end_to_end_correct else "verification"
            else:
                root_cause = None if end_to_end_correct else "extraction"

            entry["extraction"] = {
                "predicted_claim_type": pc.claim_type,
                "predicted_claimed_value": pc.claimed_value,
                "predicted_scope": pc.scope,
                "fields_match": fields_match,
                "predicted_citation_ids": pc.source_reference_ids,
                "binding_method": pc.binding_method,
                "binding_match": binding_match,
            }
            entry["verification_given_predicted_extraction"] = {
                "verdict": predicted_side_verdict,
                "evidence_state": predicted_side_state,
                "end_to_end_correct": end_to_end_correct,
                "root_cause_if_wrong": root_cause,
            }
        else:
            entry["extraction"] = {"skipped_reason": "claim count mismatch, no reliable pairing"}
            entry["verification_given_predicted_extraction"] = None

        claim_records.append(entry)

    record["claims"] = claim_records
    return record


def score_structured_input_case(case: dict) -> dict:
    if case["id"].startswith("si-contradiction"):
        result = verify_categorical_claim(
            claim_text=case["claim_text"],
            evidence=[tuple(e) for e in case["evidence"]],
            contradicting_phrases=case["contradicting_phrases"],
        )
        return {
            "id": case["id"],
            "categories": case["categories"],
            "predicted": result.verdict.value,
            "gold": case["gold_verdict"],
            "correct": result.verdict.value == case["gold_verdict"],
        }
    predicted = detect_primary_supporting_contamination(
        claim_attributed_to_primary=case["claim_attributed_to_primary"],
        source_is_primary=case["source_is_primary"],
    )
    return {
        "id": case["id"],
        "categories": case["categories"],
        "predicted": predicted,
        "gold": case["gold_contamination"],
        "correct": predicted == case["gold_contamination"],
    }


def _summarize(records: list[dict]) -> dict:
    """Aggregate one dataset's case records into the required, separated metrics."""
    insuff_checked = [r for r in records if "insufficiency" in r]
    extraction_applicable = [r for r in records if r.get("claim_extraction", {}).get("applicable")]
    count_matched = [r for r in extraction_applicable if r["claim_extraction"]["count_match"]]

    # "given gold extraction" checks are well-defined for every itemized gold
    # claim regardless of whether the predicted claim COUNT matched -- so
    # they run over every claim, not just count-matched cases. Restricting
    # this to count-matched cases would silently exclude exactly the claims
    # in the most broken cases from the verifier-soundness number, hiding
    # the failure it exists to surface.
    all_gold_claim_entries = [c for r in extraction_applicable for c in r["claims"]]
    unverifiable_gold = [c for c in all_gold_claim_entries if c["gold"]["gold_verdict"] == "unverifiable"]

    # End-to-end / field / binding checks require a reliable predicted<->gold
    # pairing, which only exists when the claim count matched.
    all_claim_entries = [c for r in count_matched for c in r["claims"]]

    sufficiency_checked = [r for r in records if "sufficiency_verdict" in r]

    def _rate(items, pred):
        return round(sum(1 for i in items if pred(i)) / len(items), 4) if items else None

    return {
        "n_cases": len(records),
        "insufficiency_detection_accuracy": _rate(insuff_checked, lambda r: r["insufficiency"]["correct"]),
        "claim_extraction_count_match_rate": _rate(
            extraction_applicable, lambda r: r["claim_extraction"]["count_match"]
        ),
        "claim_field_accuracy_given_count_match": _rate(
            all_claim_entries, lambda c: c["extraction"]["fields_match"]
        ),
        "citation_binding_accuracy_given_count_match": _rate(
            all_claim_entries, lambda c: c["extraction"]["binding_match"]
        ),
        "verification_accuracy_given_gold_extraction": _rate(
            all_gold_claim_entries, lambda c: c["verification_given_gold_extraction"]["matches_gold_verdict"]
        ),
        "verification_accuracy_given_predicted_extraction_end_to_end": _rate(
            all_claim_entries, lambda c: c["verification_given_predicted_extraction"]["end_to_end_correct"]
        ),
        "evidence_state_accuracy_given_gold_extraction": _rate(
            all_gold_claim_entries,
            lambda c: c["verification_given_gold_extraction"]["matches_gold_evidence_state"],
        ),
        "honest_abstention_rate_on_gold_unverifiable_claims": _rate(
            unverifiable_gold,
            lambda c: c["verification_given_gold_extraction"]["verdict"] == "unverifiable",
        ),
        "sufficiency_verdict_accuracy_end_to_end": _rate(
            sufficiency_checked, lambda r: r["sufficiency_verdict"]["end_to_end_correct"]
        ),
        "sufficiency_verdict_accuracy_given_gold_insufficiency_flag": _rate(
            sufficiency_checked, lambda r: r["sufficiency_verdict"]["correct_given_gold_flag"]
        ),
        "extraction_caused_failures": [
            {"case": next(r["id"] for r in count_matched if c in r["claims"]), "claim_index": c["index"]}
            for c in all_claim_entries
            if c["verification_given_predicted_extraction"]
            and not c["verification_given_predicted_extraction"]["end_to_end_correct"]
            and c["verification_given_predicted_extraction"]["root_cause_if_wrong"] == "extraction"
        ],
        "verification_caused_failures": [
            {"case": next(r["id"] for r in count_matched if c in r["claims"]), "claim_index": c["index"]}
            for c in all_claim_entries
            if c["verification_given_predicted_extraction"]
            and not c["verification_given_predicted_extraction"]["end_to_end_correct"]
            and c["verification_given_predicted_extraction"]["root_cause_if_wrong"] == "verification"
        ],
        "claim_count_mismatch_cases": [
            r["id"] for r in extraction_applicable if not r["claim_extraction"]["count_match"]
        ],
    }


def run() -> dict:
    gold = _load()
    dev_records = [score_free_text_case(c) for c in gold["dev_set"]]
    held_out_records = [score_free_text_case(c) for c in gold["held_out_set"]]
    structured_records = [score_structured_input_case(c) for c in gold["structured_input_set"]]

    return {
        "provenance": gold["_provenance"],
        "dev_set": {"cases": dev_records, "summary": _summarize(dev_records)},
        "held_out_set": {"cases": held_out_records, "summary": _summarize(held_out_records)},
        "structured_input_set": {
            "cases": structured_records,
            "accuracy": round(
                sum(1 for r in structured_records if r["correct"]) / len(structured_records), 4
            ),
        },
        "generalization_note": (
            "held_out_set summary vs dev_set summary is the generalization result. Any dimension "
            "where held-out accuracy is 1.0 only because the dev set already covers 100% of that "
            "dimension's cases is not evidence of generalization -- see the written report for which "
            "held-out numbers are non-trivial."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
