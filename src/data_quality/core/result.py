"""Domain-agnostic validation result primitives.

``ValidationIssue`` subclasses ``str`` so callers can join, search, log or
serialise issue messages unchanged, while still carrying a machine-readable
``code`` and ``field``. ``ValidationResult`` accumulates issues for a single
validated item (a file, a record, a document).
"""

from __future__ import annotations

from typing import Any


class ValidationIssue(str):
    """An issue message that also carries a machine-readable code and field.

    Subclasses ``str`` so existing callers that join, search or serialise
    issue messages keep working unchanged.
    """

    code: str
    field: str

    def __new__(cls, message: str, code: str, field: str) -> ValidationIssue:
        issue = super().__new__(cls, message)
        issue.code = code
        issue.field = field
        return issue


class ValidationResult:
    """Result of validation for a single item.

    Attributes:
        passed: ``True`` until the first issue is added.
        issues: the list of :class:`ValidationIssue` recorded.
        fields: the extracted field values that were validated (optional).
    """

    def __init__(self) -> None:
        self.passed: bool = True
        self.issues: list[ValidationIssue] = []
        self.fields: dict[str, Any] = {}

    def add_issue(
        self,
        message: str,
        code: str = "error",
        field: str = "unknown",
    ) -> None:
        """Record an issue and mark the result as failed."""
        self.passed = False
        self.issues.append(ValidationIssue(message, code, field))

    def flagged_fields(self) -> set[str]:
        """Field names already reported by an explicit check.

        A single issue may name several comma-separated fields; each is
        returned individually so callers can avoid double-counting.
        """
        flagged: set[str] = set()
        for issue in self.issues:
            flagged.update(name.strip() for name in issue.field.split(","))
        return flagged

    def __bool__(self) -> bool:
        return self.passed
