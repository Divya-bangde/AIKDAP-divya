import pytest
import uuid
import json
from unittest.mock import AsyncMock, patch

from app.agents.planner.cross_paper import synthesize_cross_paper, CrossPaperValidationException
from app.modules.research.schemas import (
    ResearchDocumentUnderstanding,
    ResearchGoal,
    ResearchGap,
    GapClassification,
    SufficiencyStatus,
    CrossPaperComparison,
    ComparisonItem,
    ComparisonRelationship,
    ResearchCertainty,
    SourceReference,
    GapResolution,
    GapResolutionState,
    ResearchHypothesis,
    HypothesisStatus,
)
from app.core.llm.gateway import LLMResponse

@pytest.fixture
def primary_understanding():
    return ResearchDocumentUnderstanding(
        title="Primary Paper",
        methodology="Uses CNN with 90% accuracy",
        missing_information=[
            ResearchGap(
                gap_type="implementation",
                classification=GapClassification.REQUIRED,
                description="Missing exact learning rate.",
                why_needed="To reproduce",
            )
        ],
        sufficiency=SufficiencyStatus.PARTIALLY_SUFFICIENT,
        sufficiency_reason="Missing params"
    )

@pytest.fixture
def supporting_papers():
    return [
        {
            "id": uuid.uuid4(),
            "title": "Supporting Paper A",
            "methodology": "Uses CNN with 99% accuracy and learning rate 0.001."
        }
    ]

@pytest.fixture
def research_goal():
    return ResearchGoal(type="reproduce", description="Reproduce the results")

def _create_mock_response(content: dict) -> LLMResponse:
    return LLMResponse(
        content=json.dumps(content),
        model="gemini-1.5-pro",
        provider="gemini",
        latency_ms=100
    )


@pytest.mark.asyncio
async def test_cross_paper_real_boundary(primary_understanding, supporting_papers, research_goal):
    # Mock the LLMGateway.generate response to return valid separated claims
    mock_content = {
        "primary_paper_id": str(uuid.uuid4()),
        "supporting_paper_ids": [str(supporting_papers[0]["id"])],
        "comparison_items": [
            {
                "topic": "Accuracy",
                "primary_claim": "90%",
                "supporting_claims": ["99%"],
                "relationship": "DIFFERS",
                "evidence": "Difference in accuracy",
                "certainty": "explicit",
                "source_references": [
                    {
                        "paper_id": str(supporting_papers[0]["id"]),
                        "paper_title": "Supporting Paper A",
                        "evidence_scope": "FULL_TEXT"
                    }
                ]
            }
        ],
        "gap_resolutions": [],
        "hypotheses": []
    }
    
    with patch("app.agents.planner.cross_paper.get_llm_gateway") as mock_get_gateway:
        mock_gateway = AsyncMock()
        mock_gateway.generate.return_value = _create_mock_response(mock_content)
        mock_get_gateway.return_value = mock_gateway
        
        result = await synthesize_cross_paper(primary_understanding, supporting_papers, research_goal)
        
        assert len(result.comparison_items) == 1
        assert result.comparison_items[0].primary_claim == "90%"
        assert result.comparison_items[0].supporting_claims[0] == "99%"


@pytest.mark.asyncio
async def test_cross_paper_hypothesis_modal_validator(primary_understanding, supporting_papers, research_goal):
    # Mock to return a deterministic (invalid) hypothesis
    mock_content = {
        "primary_paper_id": str(uuid.uuid4()),
        "supporting_paper_ids": [str(supporting_papers[0]["id"])],
        "comparison_items": [],
        "gap_resolutions": [],
        "hypotheses": [
            {
                "id": str(uuid.uuid4()),
                "description": "This will improve accuracy.",
                "supporting_sources": [
                    {
                        "paper_id": str(supporting_papers[0]["id"]),
                        "paper_title": "Supporting Paper A",
                        "evidence_scope": "FULL_TEXT"
                    }
                ],
                "rationale": "Because I said so.",
                "certainty": "explicit",
                "status": "PROPOSED"
            }
        ]
    }
    
    with patch("app.agents.planner.cross_paper.get_llm_gateway") as mock_get_gateway:
        mock_gateway = AsyncMock()
        mock_gateway.generate.return_value = _create_mock_response(mock_content)
        mock_get_gateway.return_value = mock_gateway
        
        with pytest.raises(ValueError, match="Cross-paper synthesis failed safety checks"):
            await synthesize_cross_paper(primary_understanding, supporting_papers, research_goal)


@pytest.mark.asyncio
async def test_cross_paper_missing_source_references(primary_understanding, supporting_papers, research_goal):
    # Mock to return comparison missing source reference
    mock_content = {
        "primary_paper_id": str(uuid.uuid4()),
        "supporting_paper_ids": [str(supporting_papers[0]["id"])],
        "comparison_items": [
            {
                "topic": "Accuracy",
                "primary_claim": "90%",
                "supporting_claims": ["99%"],
                "relationship": "DIFFERS",
                "evidence": "Difference in accuracy",
                "certainty": "explicit",
                "source_references": []
            }
        ],
        "gap_resolutions": [],
        "hypotheses": []
    }
    
    with patch("app.agents.planner.cross_paper.get_llm_gateway") as mock_get_gateway:
        mock_gateway = AsyncMock()
        mock_gateway.generate.return_value = _create_mock_response(mock_content)
        mock_get_gateway.return_value = mock_gateway
        
        with pytest.raises(ValueError, match="Comparison item missing source references"):
            await synthesize_cross_paper(primary_understanding, supporting_papers, research_goal)
