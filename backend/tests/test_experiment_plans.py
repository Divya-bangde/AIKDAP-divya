"""ExperimentPlanService integration tests (Sprint 16 Phase 6, Part T).

Real Postgres, real storage provider, real Asset persistence -- no
execution of any kind. Uses the shared `project`/`session` fixtures
from conftest.py.
"""

import pytest

from app.modules.research.experiment_schemas import (
    ExperimentGoal,
    ExperimentPlanCreateFromEquation,
    ExperimentPlanCreateFromUnderstanding,
    ExperimentPlanUpdateRequest,
    ExperimentSweepRequest,
    ExperimentVariantCreateRequest,
    MutabilityStatus,
    RunPlanStatus,
)
from app.modules.research.experiment_service import (
    ExperimentPlanAccessDeniedError,
    ExperimentPlanNotFoundError,
    ExperimentPlanService,
    ExperimentPlanValidationError,
)


@pytest.fixture
def service(session) -> ExperimentPlanService:
    return ExperimentPlanService(session)


class TestCreateFromEquation:
    @pytest.mark.asyncio
    async def test_creates_plan_with_correct_structure(self, service, project):
        data = ExperimentPlanCreateFromEquation(
            project_id=project.id,
            title="Rational function experiment",
            expression="Y = (aX + b) / (cX + d)",
            known_inputs=["X"],
        )
        plan = await service.create_from_equation(project.owner_id, data)

        assert plan.project_id == project.id
        assert plan.version == 1
        assert [i.name for i in plan.inputs] == ["X"]
        assert plan.outputs[0].name == "Y"
        assert {v.name for v in plan.variables} == {"a", "b", "c", "d"}
        assert len(plan.constraints) == 1
        assert "!= 0" in plan.constraints[0].expression
        assert any(v.is_baseline for v in plan.variants)

    @pytest.mark.asyncio
    async def test_persists_and_can_be_read_back(self, service, project):
        data = ExperimentPlanCreateFromEquation(
            project_id=project.id, title="Persist check", expression="Y = a*X + b", known_inputs=["X"]
        )
        created = await service.create_from_equation(project.owner_id, data)
        fetched = await service.get_plan(project.owner_id, created.id)
        assert fetched.id == created.id
        assert fetched.title == "Persist check"
        assert {v.name for v in fetched.variables} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_malformed_equation_rejected(self, service, project):
        data = ExperimentPlanCreateFromEquation(
            project_id=project.id, title="Bad equation", expression="Y = a * / X"
        )
        with pytest.raises(ExperimentPlanValidationError):
            await service.create_from_equation(project.owner_id, data)

    @pytest.mark.asyncio
    async def test_wrong_project_owner_rejected(self, service, project):
        import uuid

        data = ExperimentPlanCreateFromEquation(
            project_id=project.id, title="Cross-workspace attempt", expression="Y = a*X"
        )
        with pytest.raises(ExperimentPlanAccessDeniedError):
            await service.create_from_equation(uuid.uuid4(), data)


class TestCreateFromUnderstanding:
    @pytest.mark.asyncio
    async def test_missing_understanding_rejected(self, service, project, session):
        from app.modules.assets.enums import AssetProcessingStatus, AssetSource, AssetStatus, AssetType
        from app.modules.assets.models import Asset
        from app.modules.assets.repository import AssetRepository

        asset = Asset(
            project_id=project.id, owner_id=project.owner_id, title="No understanding yet",
            file_name="paper.txt", file_extension="txt", mime_type="text/plain", file_size=0,
            storage_path="none", checksum="none", asset_type=AssetType.DOCUMENT,
            status=AssetStatus.ACTIVE, source=AssetSource.UPLOAD, tags=[], description="",
            processing_status=AssetProcessingStatus.COMPLETED,
        )
        await AssetRepository(session).create(asset)
        await session.commit()

        data = ExperimentPlanCreateFromUnderstanding(
            project_id=project.id, title="From paper", source_asset_id=asset.id
        )
        with pytest.raises(ExperimentPlanValidationError, match="research understanding"):
            await service.create_from_understanding(project.owner_id, data)

    @pytest.mark.asyncio
    async def test_reproduction_goal_surfaces_missing_required_info(self, service, project, session):
        """Part N/Scenario 4: reproduction must mark a missing detail
        as unknown, never guess a value."""
        from app.modules.assets.enums import AssetProcessingStatus, AssetSource, AssetStatus, AssetType
        from app.modules.assets.models import Asset
        from app.modules.assets.repository import AssetRepository

        asset = Asset(
            project_id=project.id, owner_id=project.owner_id, title="Pneumonia CNN paper",
            file_name="paper.txt", file_extension="txt", mime_type="text/plain", file_size=0,
            storage_path="none", checksum="none", asset_type=AssetType.DOCUMENT,
            status=AssetStatus.ACTIVE, source=AssetSource.UPLOAD, tags=[], description="",
            processing_status=AssetProcessingStatus.COMPLETED,
            asset_metadata={
                "research_understanding": {
                    "title": "Pneumonia Detection via CNN",
                    "problem_statement": "Detect pneumonia from chest X-rays.",
                    "variables": [
                        {"name": "architecture", "role": "fixed value", "description": None,
                         "unit": None, "source_evidence": None, "confidence": "explicit"},
                    ],
                    "evaluation_metrics": ["accuracy"],
                    "missing_information": [
                        {"description": "learning rate is not stated anywhere in the paper",
                         "classification": "required"}
                    ],
                }
            },
        )
        await AssetRepository(session).create(asset)
        await session.commit()

        data = ExperimentPlanCreateFromUnderstanding(
            project_id=project.id, title="Reproduce pneumonia CNN",
            source_asset_id=asset.id, goal=ExperimentGoal.REPRODUCTION,
        )
        plan = await service.create_from_understanding(project.owner_id, data)
        assert "learning rate" in plan.objective
        assert "NOT been guessed" in plan.objective
        # And no variable named learning_rate was fabricated into existence.
        assert "learning_rate" not in {v.name for v in plan.variables}


class TestUpdateAndVersioning:
    @pytest.mark.asyncio
    async def test_update_bumps_version_and_records_history(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(
                project_id=project.id, title="v1", expression="Y = a*X", known_inputs=["X"]
            ),
        )
        assert created.version == 1

        updated = await service.update_plan(
            project.owner_id, created.id,
            ExperimentPlanUpdateRequest(title="v2", reason="renamed for clarity"),
        )
        assert updated.version == 2
        assert updated.title == "v2"
        assert len(updated.history) == 1
        assert updated.history[0].changed_field == "title"
        assert updated.history[0].old_value == "v1"
        assert updated.history[0].new_value == "v2"
        assert updated.history[0].reason == "renamed for clarity"

    @pytest.mark.asyncio
    async def test_update_without_change_does_not_bump_version(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="stable", expression="Y = a*X"),
        )
        updated = await service.update_plan(
            project.owner_id, created.id, ExperimentPlanUpdateRequest(title="stable")
        )
        assert updated.version == 1
        assert updated.history == []

    @pytest.mark.asyncio
    async def test_fixed_variable_mutation_rejected_without_override(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="fixed test", expression="Y = a*X"),
        )
        var = created.variables[0]
        fixed_var = var.model_copy(
            update={
                "mutable": MutabilityStatus.FIXED,
                "mutability_reason": "Locked for this test.",
                "current_value": "1.0",
            }
        )
        # First, actually lock it in.
        locked = await service.update_plan(
            project.owner_id, created.id,
            ExperimentPlanUpdateRequest(variables=[fixed_var], allow_fixed_variable_change=True),
        )
        locked_var = next(v for v in locked.variables if v.name == var.name)
        assert locked_var.mutable == MutabilityStatus.FIXED

        # Now attempt to silently change its value -- must be rejected.
        changed_var = locked_var.model_copy(update={"current_value": "99.0"})
        with pytest.raises(ExperimentPlanValidationError, match="FIXED"):
            await service.update_plan(
                project.owner_id, created.id, ExperimentPlanUpdateRequest(variables=[changed_var])
            )

        # But it succeeds with the explicit override flag.
        allowed = await service.update_plan(
            project.owner_id, created.id,
            ExperimentPlanUpdateRequest(variables=[changed_var], allow_fixed_variable_change=True),
        )
        assert next(v for v in allowed.variables if v.name == var.name).current_value == "99.0"

    @pytest.mark.asyncio
    async def test_constraint_violation_on_update_rejected(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="lr test", expression="Y = a*X"),
        )
        var = created.variables[0].model_copy(
            update={
                "mutable": MutabilityStatus.MUTABLE,
                "mutability_reason": "User-declared tunable parameter.",
                "current_value": "-0.1",
            }
        )
        from app.modules.research.experiment_schemas import ConstraintSource, ExperimentConstraint

        constraint = ExperimentConstraint(
            expression=f"{var.name} > 0", description="must be positive",
            source=ConstraintSource.USER_CONSTRAINT,
        )
        with pytest.raises(ExperimentPlanValidationError, match="violated"):
            await service.update_plan(
                project.owner_id, created.id,
                ExperimentPlanUpdateRequest(variables=[var], constraints=[constraint]),
            )

    @pytest.mark.asyncio
    async def test_get_nonexistent_plan_raises(self, service, project):
        import uuid

        with pytest.raises(ExperimentPlanNotFoundError):
            await service.get_plan(project.owner_id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_someone_elses_plan_raises_not_found_not_leaked(self, service, project, session):
        """Ownership must fail closed as 'not found', never 'forbidden'
        -- consistent with the rest of the app (Part U)."""
        import uuid

        from app.modules.auth.models import User

        other_user = User(
            email=f"other-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x",
            full_name="Other", is_active=True,
        )
        session.add(other_user)
        await session.flush()

        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="mine", expression="Y = a*X"),
        )
        with pytest.raises(ExperimentPlanNotFoundError):
            await service.get_plan(other_user.id, created.id)

        await session.delete(other_user)
        await session.commit()


class TestVariantsAndSweep:
    @pytest.mark.asyncio
    async def test_create_variant(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="variant test", expression="Y = a*X"),
        )
        var_name = created.variables[0].name
        updated = await service.create_variant(
            project.owner_id, created.id,
            ExperimentVariantCreateRequest(name="Variant A", overrides={var_name: "0.5"}),
        )
        assert len(updated.variants) == 2  # baseline + new
        variant = next(v for v in updated.variants if v.name == "Variant A")
        assert variant.status == RunPlanStatus.PLANNED
        assert variant.overrides == {var_name: "0.5"}

    @pytest.mark.asyncio
    async def test_variant_cannot_override_fixed_variable(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="fixed variant", expression="Y = a*X"),
        )
        var = created.variables[0]
        locked = var.model_copy(update={"mutable": MutabilityStatus.FIXED, "mutability_reason": "locked"})
        await service.update_plan(
            project.owner_id, created.id,
            ExperimentPlanUpdateRequest(variables=[locked], allow_fixed_variable_change=True),
        )
        with pytest.raises(ExperimentPlanValidationError, match="FIXED"):
            await service.create_variant(
                project.owner_id, created.id,
                ExperimentVariantCreateRequest(name="Bad variant", overrides={var.name: "1.0"}),
            )

    @pytest.mark.asyncio
    async def test_sweep_plans_without_executing(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(
                project_id=project.id, title="sweep test", expression="Y = a*X + b"
            ),
        )
        names = [v.name for v in created.variables]
        updated = await service.plan_sweep(
            project.owner_id, created.id,
            ExperimentSweepRequest(
                parameter_values={names[0]: ["0.001", "0.005", "0.01"], names[1]: ["16", "32"]}
            ),
        )
        planned = [v for v in updated.variants if not v.is_baseline]
        assert len(planned) == 6  # 3 x 2 combinations
        assert all(v.status == RunPlanStatus.PLANNED for v in planned)

    @pytest.mark.asyncio
    async def test_sweep_over_limit_rejected(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(
                project_id=project.id, title="huge sweep", expression="Y = a*X + b + c"
            ),
        )
        names = [v.name for v in created.variables]
        huge_values = {name: [str(i) for i in range(10)] for name in names}  # 10^3 = 1000
        with pytest.raises(ExperimentPlanValidationError, match="exceeding"):
            await service.plan_sweep(project.owner_id, created.id, ExperimentSweepRequest(parameter_values=huge_values))
