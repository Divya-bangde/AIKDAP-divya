"""Sprint 16 Phase 8.4 -- primary-axis real experiment runner.

Dispatches real research-run queries through the real HTTP API for
every (paper, question, repetition) triple, at whatever gate state the
server is CURRENTLY configured with (RERANKER_ENABLED, set by the
caller before starting the server -- this script does not toggle it,
since that requires a server restart).

For each real run, waits for real completion, then correlates it to
the exact `grounded_synthesis_completed`/`grounded_synthesis_skipped`
log line the real worker emitted for it (log lines are read
sequentially and the worker is a single --pool=solo process, so the
first such line to appear after dispatch, and before the run reaches a
terminal status, is unambiguously this run's).

Usage: python .e2e_scratch_8_4/run_condition.py <gate_on|gate_off>
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001/api/v1"
SCRATCH = Path(__file__).parent
CELERY_LOG = Path(__file__).parent.parent / "celery_8_4c.log"
REPS = 3

QUESTIONS = {
    "aguilar_cti": {
        "answerable": "What was the overall AI-instrument pass rate across all 1,000 generated executive reports, and which prompt strategy performed best?",
        "unanswerable": "What was the model's accuracy on the SQuAD question-answering benchmark?",
    },
    "sinanian_lte": {
        "answerable": "How did allowlist suppression affect stalkerware family detection within a ten-flow review budget?",
        "unanswerable": "What detection accuracy did the framework achieve against Pegasus spyware specifically?",
    },
    "vaniscak_c2": {
        "answerable": "Which detection tier and specific indicator achieved the highest detection rate against C2 channels running on trusted services, and what was that rate?",
        "unanswerable": "What detection rate did the study achieve against C2 traffic tunneled through Slack or Microsoft Teams?",
    },
}


def tail_new_lines(path: Path, since_line_count: int) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[since_line_count:]


def extract_synthesis_event(new_lines: list[str]) -> dict | None:
    for line in new_lines:
        if '"event": "grounded_synthesis_completed"' in line or '"event": "grounded_synthesis_skipped"' in line:
            try:
                return json.loads(line[line.index("{"):])
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def main() -> None:
    gate_state = sys.argv[1] if len(sys.argv) > 1 else "gate_on"
    assert gate_state in ("gate_on", "gate_off")

    registry = json.loads((SCRATCH / "registry.json").read_text())
    client = httpx.Client(timeout=15)
    r = client.post(f"{BASE}/auth/login", json={"email": registry["email"], "password": registry["password"]})
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    out_path = SCRATCH / f"results_{gate_state}.jsonl"
    done_keys = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            row = json.loads(line)
            done_keys.add((row["paper"], row["question_kind"], row["rep"]))

    with out_path.open("a", encoding="utf-8") as out:
        for paper_key, info in registry["papers"].items():
            for question_kind, query in QUESTIONS[paper_key].items():
                for rep in range(1, REPS + 1):
                    key = (paper_key, question_kind, rep)
                    if key in done_keys:
                        print("skip (already done)", key)
                        continue

                    line_count_before = len(CELERY_LOG.read_text(encoding="utf-8", errors="replace").splitlines()) if CELERY_LOG.exists() else 0

                    r = client.post(
                        f"{BASE}/research/run",
                        headers=headers,
                        json={"project_id": info["project_id"], "query": query},
                    )
                    r.raise_for_status()
                    run_id = r.json()["run_id"]

                    status = None
                    for _ in range(60):
                        r = client.get(f"{BASE}/research/runs/{run_id}", headers=headers)
                        detail = r.json()
                        status = detail["status"]
                        if status in ("completed", "failed"):
                            break
                        time.sleep(3)

                    new_lines = tail_new_lines(CELERY_LOG, line_count_before)
                    synth_event = extract_synthesis_event(new_lines)

                    row = {
                        "paper": paper_key,
                        "question_kind": question_kind,
                        "query": query,
                        "rep": rep,
                        "gate_state": gate_state,
                        "run_id": run_id,
                        "status": status,
                        "grounding_status": detail.get("grounding_status"),
                        "citations": detail.get("citations"),
                        "error_message": detail.get("error_message"),
                        "synthesis_event": synth_event,
                    }
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    print(paper_key, question_kind, rep, "->", status, detail.get("grounding_status"),
                          "accepted=", (synth_event or {}).get("citations_accepted"),
                          "rejected=", (synth_event or {}).get("citations_rejected"),
                          "evidence_supplied=", (synth_event or {}).get("evidence_supplied"))


if __name__ == "__main__":
    main()
