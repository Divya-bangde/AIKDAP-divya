"""Sprint 16 Phase 8.1 -- run both evaluation tracks, write results JSON.

    python -m evaluation.run_all

Run from `backend/` so `app` and `evaluation` are both importable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation import (
    claim_pipeline_track,
    claim_verification_track,
    evidence_intelligence_track,
    relevance_track,
)

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    results = {
        "phase": "Sprint 16 Phase 8.6 -- Evaluation Harness, Evidence Intelligence, Claim Verification & Claim Extraction",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track_a_relevance": relevance_track.run(),
        "track_b_evidence_intelligence": evidence_intelligence_track.run(),
        "track_c_claim_verification": claim_verification_track.run(),
        "track_d_claim_extraction_pipeline": claim_pipeline_track.run(),
    }
    out_path = RESULTS_DIR / "phase_8_6_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out_path}")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
