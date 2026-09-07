"""Real API testing script."""

import asyncio
import uuid
import time
from httpx import AsyncClient, ASGITransport
from app.main import app

async def run_real_api():
    print("--- REAL API EXECUTION ---")
    asset_id = str(uuid.uuid4())
    supporting_id = str(uuid.uuid4())
    
    payload = {
        "supporting_asset_ids": [supporting_id],
        "goal": {
            "type": "synthesis",
            "description": "Compare methodology"
        }
    }
    
    start = time.time()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/research/documents/{asset_id}/cross-paper-analysis", json=payload)
            print(f"Status: {response.status_code}")
            print(f"Latency: {int((time.time() - start)*1000)}ms")
            print("Response:")
            print(response.text)
    except Exception as e:
        print(f"API Execution failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_real_api())
