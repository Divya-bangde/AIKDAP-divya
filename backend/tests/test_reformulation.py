import pytest
from app.agents.planner.reformulation import QueryReformulation, is_reformulation_safe

def test_safe_reformulation():
    original = "What was Q3 production?"
    structured = QueryReformulation(
        search_query="Q3 production volume",
        intent="query",
        entities=[],
        metrics=["production volume"],
        dates=["Q3"],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=[],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    safe, reason = is_reformulation_safe(original, structured)
    assert safe is True

def test_hallucinated_entity():
    original = "How much did they produce in Q3?"
    structured = QueryReformulation(
        search_query="Meridian Q3 production",
        intent="query",
        entities=["Meridian"],
        metrics=["production"],
        dates=["Q3"],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=[],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    safe, reason = is_reformulation_safe(original, structured)
    assert safe is False
    assert "Hallucinated entity: Meridian" in reason

def test_dropped_negation():
    original = "Which products did not meet the target?"
    structured = QueryReformulation(
        search_query="products meeting target",
        intent="query",
        entities=[],
        metrics=[],
        dates=[],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=[],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    safe, reason = is_reformulation_safe(original, structured)
    assert safe is False
    assert "Dropped negation" in reason

def test_dropped_number():
    original = "Revenue above 8000"
    structured = QueryReformulation(
        search_query="Revenue",
        intent="query",
        entities=[],
        metrics=[],
        dates=[],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=[],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    safe, reason = is_reformulation_safe(original, structured)
    assert safe is False
    assert "Dropped comparison constraint: above" in reason or "Dropped numerical constraint" in reason

def test_ambiguity_caught():
    original = "How much did they produce?"
    structured = QueryReformulation(
        search_query="production",
        intent="query",
        entities=[],
        metrics=[],
        dates=[],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=[],
        ambiguities=["they"],
        unsupported_assumptions=[]
    )
    safe, reason = is_reformulation_safe(original, structured)
    assert safe is False
    assert "Ambiguous terms detected" in reason

def test_dropped_comparison():
    original = "Was revenue > 1000?"
    structured = QueryReformulation(
        search_query="revenue 1000",
        intent="query",
        entities=[],
        metrics=["revenue"],
        dates=[],
        regions=[],
        products=[],
        numbers=["1000"],
        constraints=[],
        negations=[],
        context_resolutions=[],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    safe, reason = is_reformulation_safe(original, structured)
    assert safe is False
    assert "Dropped comparison operator: >" in reason


def test_hallucinated_entity_allowed_by_context():
    original = "How much did they produce in Q3?"
    structured = QueryReformulation(
        search_query="Meridian Q3 production",
        intent="query",
        entities=["Meridian"],
        metrics=["production"],
        dates=["Q3"],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=["they -> Meridian"],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    workspace_context = {"active_entity": "Meridian"}
    safe, reason = is_reformulation_safe(original, structured, workspace_context)
    assert safe is True


def test_hallucinated_entity_rejected_by_wrong_context():
    original = "How much did they produce in Q3?"
    structured = QueryReformulation(
        search_query="Meridian Q3 production",
        intent="query",
        entities=["Meridian"],
        metrics=["production"],
        dates=["Q3"],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=["they -> Meridian"],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    workspace_context = {"active_entity": "Tesla"}
    safe, reason = is_reformulation_safe(original, structured, workspace_context)
    assert safe is False
    assert "Hallucinated entity: Meridian" in reason


def test_hallucinated_date_rejected_despite_context():
    original = "How much did they produce?"
    structured = QueryReformulation(
        search_query="Meridian Q3 production",
        intent="query",
        entities=["Meridian"],
        metrics=["production"],
        dates=["Q3"],
        regions=[],
        products=[],
        numbers=[],
        constraints=[],
        negations=[],
        context_resolutions=["they -> Meridian"],
        ambiguities=[],
        unsupported_assumptions=[]
    )
    workspace_context = {"active_entity": "Meridian"}
    safe, reason = is_reformulation_safe(original, structured, workspace_context)
    assert safe is False
    assert "Hallucinated date: Q3" in reason
