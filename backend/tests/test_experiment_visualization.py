"""Test-case visualization data prep (Sprint 16 Phase 6, Part H/R).

The backend only ever returns raw trace data -- no chart is rendered
server-side, and no causal claim is generated from a mere trend.
"""

import pytest

from app.agents.planner.experiment import prepare_input_output_series
from app.modules.research.experiment_schemas import (
    ExperimentPlanCreateFromEquation,
    ExperimentOutputValue,
    ExperimentTestCase,
    OutputKind,
)
from app.modules.research.experiment_service import ExperimentPlanService


def _case(id_, x, y):
    return ExperimentTestCase(
        id=id_,
        inputs={"X": x},
        expected_outputs=[ExperimentOutputValue(output_name="Y", value=y, kind=OutputKind.EXPECTED)],
    )


class TestPrepareInputOutputSeries:
    def test_numeric_cases_sorted_by_x(self):
        cases = [_case("c1", "2", "5.0"), _case("c2", "1", "2.5")]
        pairs = prepare_input_output_series(cases, "X", "Y")
        assert pairs == [("1", 2.5), ("2", 5.0)]

    def test_missing_input_skipped(self):
        cases = [ExperimentTestCase(id="c1", inputs={"Z": "1"}, expected_outputs=[])]
        pairs = prepare_input_output_series(cases, "X", "Y")
        assert pairs == []

    def test_missing_output_gives_none_not_fabricated_value(self):
        cases = [ExperimentTestCase(id="c1", inputs={"X": "1"}, expected_outputs=[])]
        pairs = prepare_input_output_series(cases, "X", "Y")
        assert pairs == [("1", None)]

    def test_non_numeric_x_sorted_last_not_dropped(self):
        cases = [_case("c1", "abc", "1.0"), _case("c2", "1", "2.0")]
        pairs = prepare_input_output_series(cases, "X", "Y")
        assert pairs[0] == ("1", 2.0)
        assert pairs[1] == ("abc", 1.0)

    def test_categorical_parameter_values(self):
        """Categorical (non-numeric) parameter comparison -- values are
        preserved as labels, not coerced to numbers."""
        cases = [_case("c1", "adam", "0.9"), _case("c2", "sgd", "0.85")]
        pairs = prepare_input_output_series(cases, "X", "Y")
        assert {p[0] for p in pairs} == {"adam", "sgd"}


class TestVisualizationEndpointBehavior:
    @pytest.fixture
    def service(self, session) -> ExperimentPlanService:
        return ExperimentPlanService(session)

    @pytest.mark.asyncio
    async def test_visualization_reflects_imported_test_cases(self, service, project):
        import json

        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(
                project_id=project.id, title="viz test", expression="Y = a*X", known_inputs=["X"]
            ),
        )
        content = json.dumps([
            {"X": "1", "expected_Y": "2.0"},
            {"X": "2", "expected_Y": "4.0"},
            {"X": "3", "expected_Y": "6.0"},
        ]).encode()
        await service.import_test_cases(project.owner_id, created.id, content, "application/json")

        viz = await service.get_visualization_data(project.owner_id, created.id, "X", "Y")
        assert viz.chart_type == "scatter"
        assert viz.x_label == "X"
        assert viz.y_label == "Y"
        assert len(viz.series) == 1
        assert viz.series[0].x == ["1", "2", "3"]
        assert viz.series[0].y == [2.0, 4.0, 6.0]

    @pytest.mark.asyncio
    async def test_trend_note_never_claims_causality(self, service, project):
        """Part H: 'Y increases with X' is fine; 'X causes Y to
        increase' is not -- the note must never use causal language."""
        import json

        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(
                project_id=project.id, title="causality check", expression="Y = a*X", known_inputs=["X"]
            ),
        )
        content = json.dumps([
            {"X": "1", "expected_Y": "1.0"},
            {"X": "2", "expected_Y": "2.0"},
        ]).encode()
        await service.import_test_cases(project.owner_id, created.id, content, "application/json")

        viz = await service.get_visualization_data(project.owner_id, created.id, "X", "Y")
        if viz.note:
            for forbidden in ("causes", "because", "results in", "leads to"):
                assert forbidden not in viz.note.lower()

    @pytest.mark.asyncio
    async def test_empty_test_cases_produce_empty_series_not_error(self, service, project):
        created = await service.create_from_equation(
            project.owner_id,
            ExperimentPlanCreateFromEquation(project_id=project.id, title="empty viz", expression="Y = a*X"),
        )
        viz = await service.get_visualization_data(project.owner_id, created.id, "X", "Y")
        assert viz.series[0].x == []
        assert viz.series[0].y == []
