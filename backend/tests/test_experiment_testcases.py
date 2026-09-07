"""Test-case import: JSON / CSV / XLSX (Sprint 16 Phase 6, Part G).

Deterministic parsing -- no DB, no LLM. Expected vs. observed outputs
must never be mixed (Part Y.6).
"""

import io
import json

import pydantic
import pytest
from openpyxl import Workbook

from app.agents.planner.experiment import parse_test_cases, parse_test_cases_json
from app.modules.research.experiment_schemas import ExperimentOutputValue, ExperimentTestCase, OutputKind


class TestJsonImport:
    def test_list_of_objects(self):
        content = json.dumps([
            {"X": "1", "expected_Y": "2.5"},
            {"X": "2", "expected_Y": "5.0"},
        ]).encode()
        imported, rejected = parse_test_cases_json(content)
        assert len(imported) == 2
        assert rejected == []
        assert imported[0].inputs == {"X": "1"}
        assert imported[0].expected_outputs[0].output_name == "Y"
        assert imported[0].expected_outputs[0].value == "2.5"
        assert imported[0].expected_outputs[0].kind == OutputKind.EXPECTED

    def test_single_object_wrapped(self):
        content = json.dumps({"X": "1", "expected_Y": "2.5"}).encode()
        imported, _ = parse_test_cases_json(content)
        assert len(imported) == 1

    def test_malformed_json_rejected(self):
        imported, rejected = parse_test_cases_json(b"{not valid json")
        assert imported == []
        assert len(rejected) == 1

    def test_non_object_row_rejected(self):
        content = json.dumps([{"X": "1"}, "not an object", {"X": "2"}]).encode()
        imported, rejected = parse_test_cases_json(content)
        assert len(imported) == 2
        assert len(rejected) == 1

    def test_via_mime_dispatch(self):
        content = json.dumps([{"X": "1"}]).encode()
        imported, _ = parse_test_cases(content, "application/json")
        assert len(imported) == 1


class TestCsvImport:
    def test_basic_csv(self):
        content = b"X,expected_Y\n1,2.5\n2,5.0\n"
        imported, rejected = parse_test_cases(content, "text/csv")
        assert len(imported) == 2
        assert rejected == []
        assert imported[0].inputs["X"] == "1"
        assert imported[0].expected_outputs[0].value == "2.5"

    def test_empty_row_rejected(self):
        content = b"X,expected_Y\n1,2.5\n,\n"
        imported, rejected = parse_test_cases(content, "text/csv")
        assert len(imported) == 1
        assert len(rejected) == 1

    def test_missing_value_not_fabricated(self):
        content = b"X,expected_Y\n1,\n"
        imported, _ = parse_test_cases(content, "text/csv")
        assert len(imported) == 1
        # An empty expected_Y cell is never synthesized into a fabricated value.
        assert imported[0].expected_outputs == [] or imported[0].expected_outputs[0].value == ""

    def test_invalid_utf8_never_raises(self):
        content = b"\xff\xfe\x00\x01"
        imported, rejected = parse_test_cases(content, "text/csv")
        assert isinstance(imported, list)
        assert isinstance(rejected, list)


class TestXlsxImport:
    def _make_xlsx(self, headers, rows) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_basic_xlsx(self):
        content = self._make_xlsx(["X", "expected_Y"], [[1, 2.5], [2, 5.0]])
        imported, rejected = parse_test_cases(
            content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert len(imported) == 2
        assert rejected == []
        assert imported[0].inputs["X"] == "1"

    def test_empty_row_rejected(self):
        content = self._make_xlsx(["X", "expected_Y"], [[1, 2.5], [None, None]])
        imported, rejected = parse_test_cases(
            content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert len(imported) == 1
        assert len(rejected) == 1

    def test_malformed_xlsx_rejected(self):
        imported, rejected = parse_test_cases(
            b"not a real xlsx file", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert imported == []
        assert len(rejected) == 1


class TestExpectedVsObservedSeparation:
    """Part Y.6: never mix expected and observed outputs."""

    def test_expected_outputs_field_rejects_observed_kind(self):
        with pytest.raises(pydantic.ValidationError):
            ExperimentTestCase(
                id="c1",
                inputs={"X": "1"},
                expected_outputs=[
                    ExperimentOutputValue(output_name="Y", value="1", kind=OutputKind.OBSERVED)
                ],
            )

    def test_observed_outputs_field_rejects_expected_kind(self):
        with pytest.raises(pydantic.ValidationError):
            ExperimentTestCase(
                id="c1",
                inputs={"X": "1"},
                observed_outputs=[
                    ExperimentOutputValue(output_name="Y", value="1", kind=OutputKind.EXPECTED)
                ],
            )

    def test_a_case_can_hold_both_kinds_in_their_own_lists(self):
        case = ExperimentTestCase(
            id="c1",
            inputs={"X": "1"},
            expected_outputs=[ExperimentOutputValue(output_name="Y", value="2.5", kind=OutputKind.EXPECTED)],
            observed_outputs=[ExperimentOutputValue(output_name="Y", value="2.4", kind=OutputKind.OBSERVED)],
        )
        assert case.expected_outputs[0].value == "2.5"
        assert case.observed_outputs[0].value == "2.4"
        assert case.expected_outputs[0].value != case.observed_outputs[0].value
