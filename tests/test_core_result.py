"""Tests for the domain-agnostic result primitives."""

from data_quality.core import ValidationIssue, ValidationResult


class TestValidationIssue:
    def test_is_a_string(self):
        issue = ValidationIssue("bad value", code="my_code", field="my_field")
        assert isinstance(issue, str)
        assert str(issue) == "bad value"
        assert issue == "bad value"  # string equality still works

    def test_carries_code_and_field(self):
        issue = ValidationIssue("bad value", code="my_code", field="my_field")
        assert issue.code == "my_code"
        assert issue.field == "my_field"

    def test_usable_in_string_operations(self):
        issue = ValidationIssue("x", code="c", field="f")
        assert ", ".join([issue, "y"]) == "x, y"
        assert issue.upper() == "X"


class TestValidationResult:
    def test_starts_passing_and_empty(self):
        result = ValidationResult()
        assert result.passed is True
        assert result.issues == []
        assert bool(result) is True

    def test_add_issue_marks_failed(self):
        result = ValidationResult()
        result.add_issue("something wrong", code="my_code", field="my_field")
        assert result.passed is False
        assert bool(result) is False
        assert len(result.issues) == 1
        assert result.issues[0].code == "my_code"
        assert result.issues[0].field == "my_field"

    def test_default_code_and_field(self):
        result = ValidationResult()
        result.add_issue("no metadata provided")
        assert result.issues[0].code == "error"
        assert result.issues[0].field == "unknown"

    def test_flagged_fields_splits_comma_separated(self):
        result = ValidationResult()
        result.add_issue("missing", code="missing_fields", field="title, artist")
        result.add_issue("bad bpm", code="value_out_of_range", field="bpm")
        assert result.flagged_fields() == {"title", "artist", "bpm"}

    def test_fields_dict_is_available(self):
        result = ValidationResult()
        result.fields = {"bpm": 128}
        assert result.fields["bpm"] == 128
