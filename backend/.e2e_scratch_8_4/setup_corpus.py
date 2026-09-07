"""Sprint 16 Phase 8.4 -- real corpus setup.

Registers one test user, creates one project PER paper (so a research
run's retrieval can never cross-contaminate between papers), uploads
each real PDF through the real /assets/upload endpoint, and polls each
until extraction+chunking+embedding is real and complete.

Run from backend/: python .e2e_scratch_8_4/setup_corpus.py
"""
import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001/api/v1"
SCRATCH = Path(__file__).parent
EMAIL = "phase84-eval@example.com"
PASSWORD = "Phase84Pass!234"

PAPERS = [
    {
        "key": "aguilar_cti",
        "title": "Evaluating LLMs as a Bridge Between Cyber Threats and Business Risk",
        "path": "../uploads/183296cf-7ccf-4fc7-975c-546852152c21/4a7c0b82-6f62-4c1b-ad75-eb39ee78c44a_SANS-Evaluating-LLMs-Aguilar (1).pdf",
    },
    {
        "key": "sinanian_lte",
        "title": "The Invisible Checkpoint: Passive LTE Traffic Capture for Mobile Malware Detection",
        "path": "../uploads/183296cf-7ccf-4fc7-975c-546852152c21/04c5d24a-66b0-41b2-bbd3-c16169eb4ebe_SANS-Invisible-Checkpoint-Sinanian.pdf",
    },
    {
        "key": "vaniscak_c2",
        "title": "Network Artifacts of Trusted Service Abuse",
        "path": "../uploads/183296cf-7ccf-4fc7-975c-546852152c21/f6e29d80-beb5-4cfe-bcba-4414277a8f26_SANS-Network-Artifacts-Trusted-Service-Abuse-080626.pdf",
    },
]


def main() -> None:
    client = httpx.Client(timeout=60)

    r = client.post(f"{BASE}/auth/register", json={"email": EMAIL, "password": PASSWORD, "full_name": "Phase 8.4 Eval"})
    print("register", r.status_code)
    r = client.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    registry: dict[str, dict] = {}
    for paper in PAPERS:
        r = client.post(f"{BASE}/projects", json={"name": f"Phase 8.4 - {paper['key']}", "description": paper["title"]}, headers=headers)
        r.raise_for_status()
        project_id = r.json()["id"]

        pdf_path = (SCRATCH / paper["path"]).resolve()
        with open(pdf_path, "rb") as f:
            r = client.post(
                f"{BASE}/assets/upload",
                headers=headers,
                data={"project_id": project_id, "title": paper["title"], "asset_type": "document"},
                files={"file": (pdf_path.name, f, "application/pdf")},
            )
        r.raise_for_status()
        asset_id = r.json()["id"]
        print(paper["key"], "project", project_id, "asset", asset_id, "uploaded")

        # Poll for real extract -> chunk -> embed completion.
        for _ in range(60):
            r = client.get(f"{BASE}/assets/{asset_id}", headers=headers)
            data = r.json()
            status = data["processing_status"]
            embed_status = data["ai_profile"]["embedding_status"]
            if status == "completed" and embed_status == "completed":
                break
            time.sleep(3)
        else:
            raise RuntimeError(f"{paper['key']} never finished processing: {status}/{embed_status}")

        registry[paper["key"]] = {"project_id": project_id, "asset_id": asset_id, "title": paper["title"]}
        print(paper["key"], "ready")

    (SCRATCH / "registry.json").write_text(json.dumps({"email": EMAIL, "password": PASSWORD, "papers": registry}, indent=2))
    print("wrote registry.json")


if __name__ == "__main__":
    main()
