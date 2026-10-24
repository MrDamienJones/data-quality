"""Domain-agnostic data quality primitives.

These types are shared by every domain subpackage.
They carry no domain knowledge and no I/O dependencies.
"""

from .result import ValidationIssue, ValidationResult

__all__ = ["ValidationIssue", "ValidationResult"]
