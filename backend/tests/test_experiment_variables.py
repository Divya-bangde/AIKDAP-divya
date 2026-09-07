"""Variable role classification and mutability analysis (Sprint 16 Phase 6, Part C/D).

Pure deterministic functions -- no DB, no LLM.
"""

from app.agents.planner.experiment import analyze_mutability, classify_variable_role
from app.modules.research.experiment_schemas import MutabilityEvidenceSource, MutabilityStatus, VariableRole
from app.modules.research.schemas import ResearchCertainty, ResearchVariable


def _var(name: str, role: str) -> ResearchVariable:
    return ResearchVariable(
        name=name, role=role, description=None, unit=None, source_evidence=None,
        confidence=ResearchCertainty.EXPLICIT,
    )


class TestVariableClassification:
    def test_input_keyword(self):
        assert classify_variable_role(_var("X", "independent variable")) == VariableRole.INPUT

    def test_output_keyword(self):
        assert classify_variable_role(_var("Y", "target label")) == VariableRole.OUTPUT

    def test_parameter_keyword(self):
        assert classify_variable_role(_var("lr", "hyperparameter")) == VariableRole.PARAMETER

    def test_constant_keyword(self):
        assert classify_variable_role(_var("pi", "fixed value")) == VariableRole.CONSTANT

    def test_derived_quantity_keyword(self):
        assert classify_variable_role(_var("f1", "derived from precision and recall")) == VariableRole.DERIVED_QUANTITY

    def test_unknown_role_stays_unknown(self):
        """An unmapped role must not silently default to VARIABLE (Part C)."""
        assert classify_variable_role(_var("z", "something unrecognized")) == VariableRole.UNKNOWN

    def test_blank_role_is_unknown(self):
        assert classify_variable_role(_var("z", "")) == VariableRole.UNKNOWN


class TestMutabilityAnalysis:
    def test_explicit_paper_fixed(self):
        status, reason, evidence = analyze_mutability(
            name="architecture", paper_statement="The model architecture is held constant across all runs."
        )
        assert status == MutabilityStatus.FIXED
        assert evidence == MutabilityEvidenceSource.PAPER_STATEMENT
        assert "held constant" in reason

    def test_explicit_paper_mutable(self):
        status, reason, evidence = analyze_mutability(
            name="learning_rate", paper_statement="The learning rate was tuned via grid search."
        )
        assert status == MutabilityStatus.MUTABLE
        assert evidence == MutabilityEvidenceSource.PAPER_STATEMENT

    def test_experiment_context_mutable(self):
        status, _, evidence = analyze_mutability(
            name="augmentation", experiment_context="Ablation study varying augmentation strategy."
        )
        assert status == MutabilityStatus.MUTABLE
        assert evidence == MutabilityEvidenceSource.EXPERIMENT_CONTEXT

    def test_workspace_state_mutable(self):
        status, _, evidence = analyze_mutability(name="batch_size", workspace_mutable_hint=True)
        assert status == MutabilityStatus.MUTABLE
        assert evidence == MutabilityEvidenceSource.WORKSPACE_STATE

    def test_workspace_state_fixed(self):
        status, _, evidence = analyze_mutability(name="dataset", workspace_mutable_hint=False)
        assert status == MutabilityStatus.FIXED
        assert evidence == MutabilityEvidenceSource.WORKSPACE_STATE

    def test_research_understanding_parameter_role_is_mutable(self):
        status, _, evidence = analyze_mutability(
            name="lr", research_understanding_role=VariableRole.PARAMETER
        )
        assert status == MutabilityStatus.MUTABLE
        assert evidence == MutabilityEvidenceSource.RESEARCH_UNDERSTANDING

    def test_research_understanding_constant_role_is_fixed(self):
        status, _, evidence = analyze_mutability(
            name="pi", research_understanding_role=VariableRole.CONSTANT
        )
        assert status == MutabilityStatus.FIXED

    def test_research_understanding_derived_role_is_fixed(self):
        status, _, _ = analyze_mutability(
            name="f1", research_understanding_role=VariableRole.DERIVED_QUANTITY
        )
        assert status == MutabilityStatus.FIXED

    def test_llm_interpretation_is_lowest_confidence(self):
        status, reason, evidence = analyze_mutability(name="z", llm_suggested_mutable=True)
        assert status == MutabilityStatus.MUTABLE
        assert evidence == MutabilityEvidenceSource.LLM_INTERPRETATION
        assert "low-confidence" in reason

    def test_no_evidence_is_unknown_not_guessed(self):
        """The system must never say 'you can change all these
        variables' without evidence (Part D)."""
        status, reason, evidence = analyze_mutability(name="mystery")
        assert status == MutabilityStatus.UNKNOWN
        assert evidence == MutabilityEvidenceSource.NONE
        assert "No evidence" in reason

    def test_evidence_hierarchy_order_paper_beats_context(self):
        """Paper statement (rung 1) must win over experiment context
        (rung 2) when both are present."""
        status, _, evidence = analyze_mutability(
            name="lr",
            paper_statement="Held constant across all experiments.",
            experiment_context="Part of the ablation sweep.",
        )
        assert status == MutabilityStatus.FIXED
        assert evidence == MutabilityEvidenceSource.PAPER_STATEMENT
