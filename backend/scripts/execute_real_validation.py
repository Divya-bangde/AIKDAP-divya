"""Real validation execution script to test the true LLMGateway for cross-paper logic."""

import asyncio
import json
import uuid
from typing import Any

from app.agents.planner.cross_paper import synthesize_cross_paper
from app.modules.research.schemas import (
    ResearchDocumentUnderstanding,
    ResearchGoal,
    ResearchGap,
    GapClassification,
    SufficiencyStatus
)
from app.core.llm.gateway import LLMError

async def run_real_validation():
    print("--- REAL LLM PROVIDER VALIDATION ---")
    goal = ResearchGoal(type="synthesis", description="Evaluate hypotheses.")
    primary = ResearchDocumentUnderstanding(
        title="Primary Paper A", 
        methodology="Method CNN", 
        results="Accuracy = 90%",
        missing_information=[
            ResearchGap(
                gap_type="data", 
                classification=GapClassification.REQUIRED, 
                description="Needs dataset specifics", 
                why_needed="To replicate"
            ),
            ResearchGap(
                gap_type="implementation", 
                classification=GapClassification.REQUIRED, 
                description="missing learning rate", 
                why_needed="To replicate"
            )
        ],
        sufficiency=SufficiencyStatus.INSUFFICIENT,
        sufficiency_reason="Missing data specifics"
    )
    
    supporting = [
        {"id": uuid.uuid4(), "title": "Supporting Paper B", "methodology": "CNN", "results": "Accuracy = 99%"},
        {"id": uuid.uuid4(), "title": "Supporting Paper D", "learning_rate": 0.001},
        {"id": uuid.uuid4(), "title": "Supporting Paper G", "domain": "Chemistry", "topic": "Molecule binding"},
        {"id": uuid.uuid4(), "title": "Supporting Paper H", "results": "Augmentation Y improves robustness in its own experiment."}
    ]

    try:
        res = await synthesize_cross_paper(primary, supporting, goal)
        print("REAL EXECUTION SUCCESS!")
        print(res.model_dump_json(indent=2))
    except LLMError as e:
        print("REAL EXECUTION FAILED: LLMError")
        print(str(e))
    except Exception as e:
        print("REAL EXECUTION FAILED: Exception")
        print(str(e))

if __name__ == "__main__":
    asyncio.run(run_real_validation())
