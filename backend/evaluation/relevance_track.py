"""Track A -- relevance-gate evaluation (Sprint 16 Phase 8.1).

Exercises the REAL, production `RelevanceGate`
(`app.modules.knowledge_base.relevance.RelevanceGate`) -- never a
reimplementation of the score-vs-threshold comparison -- against:

  * the real 70-row production calibration fixture
    (`tests/fixtures_relevance_calibration.json`, recorded from the
    live BGE-M3 -> pgvector -> BGE-Reranker-v2-m3 stack), and
  * 7 hand-curated near-threshold/off-topic rows added for this phase
    (`gold_relevance_extra.json`, tagged `source: phase_8_1_curated` --
    synthetic, not retrieved from a real corpus).

Compares four threshold policies (baseline/naive, production-calibrated,
this-corpus auto-calibrated) and gate ON vs OFF.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.modules.knowledge_base.relevance import RelevanceGate
from evaluation.metrics import binary_confusion

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures_relevance_calibration.json"
CURATED_PATH = Path(__file__).parent / "gold_relevance_extra.json"

#: Naive threshold a developer might reach for without calibration --
#: "0 means neutral" is a meaningless assumption for an unbounded logit,
#: which is exactly the point this comparison exists to demonstrate.
BASELINE_THRESHOLD = 0.0


def load_rows() -> list[dict]:
    production_rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for row in production_rows:
        row.setdefault("source", "production_fixture")
    curated_rows = json.loads(CURATED_PATH.read_text(encoding="utf-8"))
    return production_rows + curated_rows


def _apply_gate_at_threshold(rows: list[dict], threshold: float | None) -> dict:
    """Run the real gate; `threshold=None` means gate OFF (accept all)."""
    if threshold is None:
        pairs = [(True, row["expected_relevance"]) for row in rows]
        return binary_confusion(pairs).as_dict()

    gate = RelevanceGate(threshold=threshold)
    decision = gate.apply(
        items=rows, scores=[row["rerank_score"] for row in rows], query="phase_8_1_eval"
    )
    accepted_ids = {id(item) for item in decision.accepted}
    pairs = [(id(row) in accepted_ids, row["expected_relevance"]) for row in rows]
    return binary_confusion(pairs).as_dict()


def auto_calibrate(rows: list[dict]) -> float:
    """Scan observed scores, pick the threshold maximizing F1 on this corpus.

    This is intentionally the simplest possible auto-calibration: every
    observed score is a candidate cut point, and the real `RelevanceGate`
    (not a reimplementation) scores each candidate. Ties break toward the
    higher (stricter) threshold, matching the production gate's own
    documented bias toward rejecting borderline evidence.
    """
    candidates = sorted({row["rerank_score"] for row in rows}, reverse=True)
    best_threshold, best_f1 = candidates[0] + 1.0, -1.0
    for threshold in candidates:
        result = _apply_gate_at_threshold(rows, threshold)
        if result["f1"] > best_f1:
            best_f1, best_threshold = result["f1"], threshold
    return best_threshold


def run() -> dict:
    rows = load_rows()
    production_threshold = settings.reranker_relevance_threshold
    calibrated_threshold = auto_calibrate(rows)

    policies = {
        "gate_off": _apply_gate_at_threshold(rows, None),
        "baseline_naive_threshold_0.0": _apply_gate_at_threshold(rows, BASELINE_THRESHOLD),
        "production_calibrated_threshold": {
            **_apply_gate_at_threshold(rows, production_threshold),
            "threshold_value": production_threshold,
        },
        "phase_8_1_auto_calibrated_threshold": {
            **_apply_gate_at_threshold(rows, calibrated_threshold),
            "threshold_value": calibrated_threshold,
        },
    }
    return {
        "row_count": len(rows),
        "production_fixture_rows": sum(1 for r in rows if r["source"] == "production_fixture"),
        "phase_8_1_curated_rows": sum(1 for r in rows if r["source"] == "phase_8_1_curated"),
        "policies": policies,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
