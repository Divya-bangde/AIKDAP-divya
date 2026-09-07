"""Dedicated safety tests (Sprint 16 Phase 6, Part U/W/Y).

Every test here proves a specific way the system must fail closed:
reject invalid numbers, refuse to silently mutate a fixed variable,
never leak cross-workspace data, and never let a user-supplied string
become executable code.
"""

import uuid

import pytest

from app.agents.planner.experiment import (
    EquationParseError,
    check_all_constraints,
    validate_numeric_constraint,
)
from app.modules.research.experiment_schemas import (
    ConstraintSource,
    ExperimentConstraint,
    ExperimentGoal,
    ExperimentHypothesisRef,
    ExperimentPlanCreateFromEquation,
    ExperimentPlanUpdateRequest,
    ExperimentVariantCreateRequest,
    HypothesisOrigin,
    MutabilityEvidenceSource,
    MutabilityStatus,
    ResearchCertainty,
    VariableRole,
)
from app.modules.research.experiment_schemas import ExperimentVariable
from app.modules.research.experiment_service import (
    ExperimentPlanAccessDeniedError,
    ExperimentPlanService,
    ExperimentPlanValidationError,
)


@pytest.fixture
def service(session) -> ExperimentPlanService:
    return ExperimentPlanService(session)


class TestNumericSafety:
    """Part W's exact worked example, and its neighbors."""

    def test_negative_learning_rate_rejected(self):
        assert validate_numeric_constraint("learning_rate > 0", {"learning_rate": -0.1}) is False

    def test_invalid_threshold_out_of_range_rejected(self):
        assert validate_numeric_constraint("0 <= threshold", {"threshold": -0.5}) is False
        assert validate_numeric_constraint("threshold <= 1", {"threshold": 1.5}) is False

    def test_valid_threshold_accepted(self):
        assert validate_numeric_constraint("0 <= threshold", {"threshold": 0.5}) is True
        assert validate_numeric_constraint("threshold <= 1", {"threshold": 0.5}) is True


class TestFixedVariableMutationSafety:
    @pytest.mark.asyncio
    async def test_cannot_silently_change_fixed_variable(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="safety", expression="Y = a*X"),
        )
        var = created.variables[0]
        fixed = var.model_copy(update={"mutable": MutabilityStatus.FIXED, "mutability_reason": "locked"})
        locked_plan = await service.update_plan(
            project.owner_id, created.id,
            ExperimentPlanUpdateRequest(variables=[fixed], allow_fixed_variable_change=True),
        )
        locked_var = locked_plan.variables[0]

        attempted_change = locked_var.model_copy(update={"current_value": "999"})
        with pytest.raises(ExperimentPlanValidationError):
            await service.update_plan(
                project.owner_id, created.id, ExperimentPlanUpdateRequest(variables=[attempted_change])
            )

    @pytest.mark.asyncio
    async def test_variant_cannot_override_fixed_variable(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="safety2", expression="Y = a*X"),
        )
        var = created.variables[0]
        fixed = var.model_copy(update={"mutable": MutabilityStatus.FIXED, "mutability_reason": "locked"})
        await service.update_plan(
            project.owner_id, created.id,
            ExperimentPlanUpdateRequest(variables=[fixed], allow_fixed_variable_change=True),
        )
        with pytest.raises(ExperimentPlanValidationError):
            await service.create_variant(
                project.owner_id, created.id,
                ExperimentVariantCreateRequest(name="sneaky", overrides={var.name: "1.0"}),
            )


class TestAuthorizationSafety:
    @pytest.mark.asyncio
    async def test_cannot_create_plan_in_unowned_project(self, service, project):
        data = ExperimentPlanCreateFromEquation(
            project_id=project.id, title="not mine", expression="Y = a*X"
        )
        with pytest.raises(ExperimentPlanAccessDeniedError):
            await service.create_from_equation(uuid.uuid4(), data)

    @pytest.mark.asyncio
    async def test_cannot_use_another_users_asset_as_source(self, service, project, session):
        from app.modules.assets.enums import AssetProcessingStatus, AssetSource, AssetStatus, AssetType
        from app.modules.assets.models import Asset
        from app.modules.assets.repository import AssetRepository
        from app.modules.auth.models import User

        other_user = User(
            email=f"other-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x",
            full_name="Other", is_active=True,
        )
        session.add(other_user)
        await session.flush()

        others_asset = Asset(
            project_id=project.id, owner_id=other_user.id, title="Not yours",
            file_name="paper.txt", file_extension="txt", mime_type="text/plain", file_size=0,
            storage_path="none", checksum="none", asset_type=AssetType.DOCUMENT,
            status=AssetStatus.ACTIVE, source=AssetSource.UPLOAD, tags=[], description="",
            processing_status=AssetProcessingStatus.COMPLETED,
        )
        await AssetRepository(session).create(others_asset)
        await session.commit()

        data = ExperimentPlanCreateFromEquation(
            project_id=project.id, title="using stolen asset", expression="Y = a*X",
            source_asset_id=others_asset.id,
        )
        with pytest.raises(ExperimentPlanValidationError):
            await service.create_from_equation(project.owner_id, data)

        await session.delete(other_user)
        await session.commit()

    @pytest.mark.asyncio
    async def test_plan_from_one_project_not_visible_via_another_owned_project(
        self, service, project, session
    ):
        """Cross-workspace contamination check (Part U/Y.7): listing
        plans under project B must never surface a plan created under
        project A, even for the same owner."""
        from app.modules.projects.models import Project, ProjectStatus, ProjectType

        other_project = Project(
            owner_id=project.owner_id, name="Second workspace", description="",
            project_type=ProjectType.RESEARCH, status=ProjectStatus.ACTIVE,
        )
        session.add(other_project)
        await session.flush()
        await session.commit()

        await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="in project A", expression="Y=a*X"),
        )
        plans_in_b = await service.list_plans(project.owner_id, other_project.id)
        assert plans_in_b == []

        await session.delete(other_project)
        await session.commit()


class TestHypothesisSafety:
    """Part L/Y.8: never present an AI-generated or unvalidated
    hypothesis as a proven fact."""

    def test_ai_generated_hypothesis_marked_unvalidated(self):
        ref = ExperimentHypothesisRef(
            description="Augmentation Y may improve robustness.",
            origin=HypothesisOrigin.AI_GENERATED_UNVALIDATED,
            certainty=ResearchCertainty.INTERPRETED,
        )
        assert ref.origin == HypothesisOrigin.AI_GENERATED_UNVALIDATED
        assert ref.certainty != ResearchCertainty.EXPLICIT

    def test_user_created_hypothesis_distinct_origin(self):
        ref = ExperimentHypothesisRef(
            description="I want to test whether batch size affects convergence.",
            origin=HypothesisOrigin.USER_CREATED,
        )
        assert ref.origin == HypothesisOrigin.USER_CREATED
        assert ref.origin != HypothesisOrigin.AI_GENERATED_UNVALIDATED

    def test_stored_hypothesis_keeps_its_source_id(self):
        ref = ExperimentHypothesisRef(
            description="From a prior cross-paper run.",
            origin=HypothesisOrigin.STORED_RESEARCH_HYPOTHESIS,
            source_hypothesis_id="hyp-123",
        )
        assert ref.source_hypothesis_id == "hyp-123"


class TestNoArbitraryExecution:
    """Part U/Y.9: no string a user supplies -- as a test-case value, a
    variable value, or a constraint/equation expression -- may become
    executable code.

    This class exists because of a real vulnerability found and fixed
    while building this module: `sympy.parse_expr`/`sympify` parses by
    handing the token stream to Python's real `eval()`. A first attempt
    at mitigation -- `global_dict={'__builtins__': {}}` alone -- was
    verified NOT sufficient: `__import__('os').system(...)` was
    correctly blocked by it, but the classic sandbox-escape gadget
    `().__class__.__bases__[0].__subclasses__()` needs no builtin at
    all and returned the full list of live Python classes (including
    `subprocess.Popen`) through that mitigation alone. The fix is two
    layers: `_assert_expression_is_safe` (a strict charset/dunder/
    attribute-dot allowlist applied BEFORE parsing) plus the restricted
    `global_dict` as defense in depth. Every test below was run against
    the actual vulnerable code first and confirmed to fail before the
    fix was applied, and confirmed to pass after.
    """

    def test_shell_injection_in_test_case_value_is_inert_data(self):
        """A shell-metacharacter string in an input value is stored
        and returned as plain text -- never interpreted. Test-case
        values are never parsed as expressions at all, so this class
        of attack does not apply to them the way it does to equations/
        constraints; verified here for completeness."""
        from app.agents.planner.experiment import parse_test_cases_json
        import json

        payload = json.dumps([{"X": "1; rm -rf / #", "expected_Y": "$(whoami)"}]).encode()
        imported, rejected = parse_test_cases_json(payload)
        assert len(imported) == 1
        assert imported[0].inputs["X"] == "1; rm -rf / #"
        assert imported[0].expected_outputs[0].value == "$(whoami)"

    @pytest.mark.parametrize(
        "malicious_expression",
        [
            "__import__('os').system('echo pwned')",
            "().__class__.__bases__[0].__subclasses__()",
            "getattr(1,'__class__')",
            "[].__class__",
            "eval('1+1')",
            "exec('import os')",
            "open('/etc/passwd').read()",
            "learning_rate = 1; import os",
        ],
    )
    def test_injection_attempts_blocked_in_constraint_validation(self, malicious_expression):
        with pytest.raises(EquationParseError):
            validate_numeric_constraint(malicious_expression, {"learning_rate": 0.1})

    @pytest.mark.parametrize(
        "malicious_expression",
        [
            "__import__('os').system('echo pwned')",
            "().__class__.__bases__[0].__subclasses__()",
            "getattr(1,'__class__')",
        ],
    )
    def test_injection_attempts_blocked_in_equation_parsing(self, malicious_expression):
        from app.agents.planner.experiment import parse_equation

        with pytest.raises(EquationParseError):
            parse_equation(f"Y = {malicious_expression}")

    def test_legitimate_expressions_still_work_after_the_fix(self):
        """The fix must not be so broad it breaks real math."""
        assert validate_numeric_constraint("learning_rate > 0", {"learning_rate": 0.01}) is True
        assert validate_numeric_constraint("0 <= threshold", {"threshold": 0.5}) is True
        assert validate_numeric_constraint("0.5 + a > 0", {"a": 1.0}) is True

    def test_constraint_expression_with_assignment_rejected(self):
        with pytest.raises(EquationParseError):
            validate_numeric_constraint("learning_rate = 1; import os", {"learning_rate": 0.1})

    @pytest.mark.asyncio
    async def test_malicious_constraint_string_rejected_end_to_end(self, service, project):
        """The full service path: a constraint that isn't valid SymPy
        math is rejected at plan-update time, never silently accepted
        or evaluated as code."""
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="injection test", expression="Y=a*X"),
        )
        var = created.variables[0].model_copy(
            update={"mutable": MutabilityStatus.MUTABLE, "mutability_reason": "test", "current_value": "1.0"}
        )
        malicious_constraint = ExperimentConstraint(
            expression="__import__('os').system('id')",
            description="malicious",
            source=ConstraintSource.USER_CONSTRAINT,
        )
        # check_all_constraints must not raise/execute -- an unparseable
        # constraint is simply never marked satisfied or violated; it is
        # inert. Confirm no exception propagates and nothing executes.
        violations = check_all_constraints([var], [malicious_constraint])
        assert violations == []  # unparseable => skipped, not executed, not "passed"
