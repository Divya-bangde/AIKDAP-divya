"""Equation parsing and constraint derivation (Sprint 16 Phase 6, Part E/F).

All SymPy, no LLM -- deterministic and no DB required.
"""

import pytest

from app.agents.planner.experiment import (
    EquationParseError,
    build_variables_from_equation,
    check_all_constraints,
    parse_equation,
    validate_numeric_constraint,
)
from app.modules.research.experiment_schemas import (
    ConstraintSource,
    MutabilityStatus,
    VariableRole,
)


class TestSimpleEquation:
    def test_output_and_symbols_identified(self):
        result = parse_equation("Y = a*X + b")
        assert result.output_name == "Y"
        assert sorted(result.parameter_symbols) == ["X", "a", "b"]

    def test_no_denominator_means_no_mathematical_constraint(self):
        result = parse_equation("Y = a*X + b")
        assert result.constraints == []


class TestMultiVariableEquation:
    """The Part E worked example: Y = (aX + b) / (cX + d)."""

    def test_scenario_1_equation(self):
        result = parse_equation("Y = (aX + b) / (cX + d)")
        assert result.output_name == "Y"
        assert sorted(result.parameter_symbols) == ["X", "a", "b", "c", "d"]

    def test_denominator_constraint_derived(self):
        result = parse_equation("Y = (aX + b) / (cX + d)")
        assert len(result.constraints) == 1
        constraint = result.constraints[0]
        assert constraint.source == ConstraintSource.MATHEMATICAL_CONSTRAINT
        assert "!= 0" in constraint.expression

    def test_scenario_1_known_input_classification(self):
        result = parse_equation("Y = (aX + b) / (cX + d)")
        variables, output, inputs = build_variables_from_equation(result, known_inputs=["X"])
        assert output.name == "Y"
        assert [i.name for i in inputs] == ["X"]
        names = {v.name for v in variables}
        assert names == {"a", "b", "c", "d"}

    def test_scenario_1_parameters_not_auto_mutable(self):
        """Part E: 'DO NOT automatically declare all parameters
        mutable' -- with no research/workspace evidence, a,b,c,d must
        be UNKNOWN, not MUTABLE."""
        result = parse_equation("Y = (aX + b) / (cX + d)")
        variables, _, _ = build_variables_from_equation(result, known_inputs=["X"])
        for var in variables:
            assert var.mutable == MutabilityStatus.UNKNOWN
            assert var.role == VariableRole.UNKNOWN
            assert var.mutability_reason  # never blank


class TestInvalidEquation:
    def test_empty_expression_rejected(self):
        with pytest.raises(EquationParseError):
            parse_equation("")

    def test_malformed_syntax_rejected(self):
        with pytest.raises(EquationParseError):
            parse_equation("Y = a * / X")

    def test_output_on_both_sides_rejected(self):
        with pytest.raises(EquationParseError):
            parse_equation("Y = Y + 1")


class TestConstraintValidation:
    def test_derived_constraint_holds(self):
        assert validate_numeric_constraint("c*X + d != 0", {"c": 1.0, "X": 2.0, "d": -3.0}) is True

    def test_derived_constraint_violated(self):
        assert validate_numeric_constraint("c*X + d != 0", {"c": 1.0, "X": 2.0, "d": -2.0}) is False

    def test_hyperparameter_constraint_rejects_negative_learning_rate(self):
        """The exact Part W example."""
        assert validate_numeric_constraint("learning_rate > 0", {"learning_rate": -0.1}) is False
        assert validate_numeric_constraint("learning_rate > 0", {"learning_rate": 0.01}) is True

    def test_range_constraint(self):
        assert validate_numeric_constraint("0 <= threshold", {"threshold": 0.5}) is True
        assert validate_numeric_constraint("threshold <= 1", {"threshold": 1.5}) is False

    def test_missing_variable_raises(self):
        with pytest.raises(EquationParseError):
            validate_numeric_constraint("learning_rate > 0", {})

    def test_malformed_constraint_raises(self):
        with pytest.raises(EquationParseError):
            validate_numeric_constraint("learning_rate >> 0", {"learning_rate": 1.0})


class TestCheckAllConstraints:
    """The whole-plan gate the service calls on every create/update."""

    def _var(self, name, value):
        from app.modules.research.experiment_schemas import ExperimentVariable, MutabilityEvidenceSource
        return ExperimentVariable(
            name=name, role=VariableRole.PARAMETER, mutable=MutabilityStatus.MUTABLE,
            mutability_reason="test", mutability_evidence=MutabilityEvidenceSource.USER_OVERRIDE,
            current_value=str(value),
        )

    def _constraint(self, expression, description="test constraint"):
        from app.modules.research.experiment_schemas import ExperimentConstraint
        return ExperimentConstraint(
            expression=expression, description=description, source=ConstraintSource.USER_CONSTRAINT
        )

    def test_no_violations_when_satisfied(self):
        violations = check_all_constraints(
            [self._var("learning_rate", 0.01)], [self._constraint("learning_rate > 0")]
        )
        assert violations == []

    def test_violation_reported(self):
        violations = check_all_constraints(
            [self._var("learning_rate", -0.1)], [self._constraint("learning_rate > 0")]
        )
        assert len(violations) == 1
        assert "learning_rate > 0" in violations[0]

    def test_constraint_over_unset_variable_is_skipped_not_failed(self):
        """A constraint mentioning a variable with no current_value yet
        cannot be evaluated -- that is not the same as being violated."""
        violations = check_all_constraints([], [self._constraint("batch_size > 0")])
        assert violations == []

    def test_multiple_variables_multiple_constraints(self):
        violations = check_all_constraints(
            [self._var("a", 1.0), self._var("b", -5.0)],
            [self._constraint("a > 0"), self._constraint("b > 0")],
        )
        assert len(violations) == 1
        assert "b > 0" in violations[0]
