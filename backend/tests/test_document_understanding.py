import uuid
from typing import Any
import pytest
from unittest.mock import AsyncMock

from app.modules.research.schemas import (
    ResearchDocumentUnderstanding,
    ResearchGoal,
    AnalyzeDocumentRequest,
    SufficiencyStatus
)
from app.modules.research.service import ResearchService, ProjectAccessDeniedError

@pytest.fixture
def mock_analyze_research_document(monkeypatch):
    """Mocks the LLM-heavy analysis function."""
    mock = AsyncMock()
    mock.return_value = ResearchDocumentUnderstanding(
        title="Fake Research Paper",
        abstract="This is a fake paper.",
        objectives=["Test extraction"],
        sufficiency=SufficiencyStatus.SUFFICIENT,
        sufficiency_reason="It has enough data."
    )
    monkeypatch.setattr("app.agents.planner.analysis.analyze_research_document", mock)
    return mock

@pytest.mark.asyncio
async def test_analyze_document_service_success(
    session: Any,
    project: Any, 
    mock_analyze_research_document: AsyncMock
):
    # Mock asset ID
    asset_id = uuid.uuid4()
    goal = ResearchGoal(type="understand", description="Just testing the endpoint")
    req = AnalyzeDocumentRequest(goal=goal)

    service = ResearchService(session)
    result = await service.analyze_document(project.owner_id, asset_id, project.id, req)
    
    assert result.title == "Fake Research Paper"
    assert result.sufficiency == SufficiencyStatus.SUFFICIENT
    mock_analyze_research_document.assert_awaited_once()

@pytest.mark.asyncio
async def test_analyze_document_service_unauthorized_project(
    session: Any,
    mock_analyze_research_document: AsyncMock
):
    # Wrong user ID or project ID
    asset_id = uuid.uuid4()
    wrong_owner_id = uuid.uuid4()
    wrong_project_id = uuid.uuid4()
    
    goal = ResearchGoal(type="understand", description="Just testing")
    req = AnalyzeDocumentRequest(goal=goal)

    service = ResearchService(session)
    with pytest.raises(ProjectAccessDeniedError):
        await service.analyze_document(wrong_owner_id, asset_id, wrong_project_id, req)
    
    mock_analyze_research_document.assert_not_awaited()
