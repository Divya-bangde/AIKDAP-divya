"""Sprint 16 Phase 8.4 -- derive conditions A/B/C/D from the two real batches.

Design: citation validation is not an optional code path in production
(`GroundedSynthesizer` always calls `_validate_citation_ids`), so "no
citation validation" is not a separate real run -- it is the same real
run's raw claimed-citation count treated as final, instead of the
validated (accepted) count. One real gate-ON run therefore yields both
condition B (validation off) and D (validation on); one real gate-OFF
run yields both A and C. This halves the real calls needed and pairs
A/C and B/D perfectly (same model output, two ways of trusting it),
rather than sampling them independently.

  A = gate_off, claimed  (accepted + rejected, i.e. trust every claim)
  B = gate_on,  claimed
  C = gate_off, accepted (validated)
  D = gate_on,  accepted (validated)  -- full AIKDAP
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

SCRATCH = Path(__file__).parent


def load(gate_state: str) -> list[dict]:
    return [json.loads(l) for l in (SCRATCH / f"results_{gate_state}.jsonl").read_text().splitlines()]


def claimed_and_accepted(row: dict) -> tuple[int, int]:
    """(claimed_total, accepted) for one run, from whichever real path fired."""
    ev = row["synthesis_event"] or {}
    if ev.get("event") == "grounded_synthesis_skipped" or row["grounding_status"] == "insufficient_evidence" and not ev:
        return 0, 0
    accepted = ev.get("citations_accepted")
    rejected = ev.get("citations_rejected")
    if accepted is None:
        # grounded_synthesis_skipped path: zero evidence ever reached the model.
        return 0, 0
    return accepted + rejected, accepted


def per_condition_metrics(rows: list[dict], *, use_claimed: bool) -> dict:
    """Aggregate one condition's rows into the four required metrics."""
    total_claims, total_accepted_or_claimed = 0, 0
    zero_evidence_runs = 0
    grounding_dist: Counter = Counter()
    n = len(rows)
    for row in rows:
        ev = row["synthesis_event"] or {}
        evidence_supplied = ev.get("evidence_supplied")
        if evidence_supplied == 0 or evidence_supplied is None:
            zero_evidence_runs += 1
        claimed, accepted = claimed_and_accepted(row)
        numerator = claimed if use_claimed else accepted
        total_claims += claimed
        total_accepted_or_claimed += numerator
        grounding_dist[row["grounding_status"]] += 1

    unsupported = total_claims - total_accepted_or_claimed if use_claimed else 0
    return {
        "n_runs": n,
        "unsupported_claim_rate": round(unsupported / total_claims, 4) if (use_claimed and total_claims) else 0.0,
        "citation_validity_rate": round(total_accepted_or_claimed / total_claims, 4) if total_claims else None,
        "grounding_status_distribution": dict(grounding_dist),
        "zero_evidence_rate": round(zero_evidence_runs / n, 4) if n else None,
        "total_claimed_citations": total_claims,
        "total_counted_citations": total_accepted_or_claimed,
    }


def main() -> None:
    gate_on = load("gate_on")
    gate_off = load("gate_off")

    papers = sorted({r["paper"] for r in gate_on})
    report: dict = {}
    for paper in papers:
        on_rows = [r for r in gate_on if r["paper"] == paper]
        off_rows = [r for r in gate_off if r["paper"] == paper]
        report[paper] = {
            "A_llm_only_no_gate_no_validation": per_condition_metrics(off_rows, use_claimed=True),
            "B_gate_no_validation": per_condition_metrics(on_rows, use_claimed=True),
            "C_validation_no_gate": per_condition_metrics(off_rows, use_claimed=False),
            "D_full_aikdap": per_condition_metrics(on_rows, use_claimed=False),
        }
        # Split out answerable vs unanswerable too -- the aggregate above
        # blends both question kinds, which hides where zero-evidence
        # actually comes from.
        for kind in ("answerable", "unanswerable"):
            on_k = [r for r in on_rows if r["question_kind"] == kind]
            off_k = [r for r in off_rows if r["question_kind"] == kind]
            report[paper][f"_breakdown_{kind}"] = {
                "gate_on": per_condition_metrics(on_k, use_claimed=False),
                "gate_off": per_condition_metrics(off_k, use_claimed=False),
            }

    print(json.dumps(report, indent=2))
    (SCRATCH / "primary_axis_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
