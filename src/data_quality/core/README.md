# data_quality.core

Domain-agnostic primitives shared by every domain subpackage (music, garmin,
pdf, ...). No domain knowledge, no I/O dependencies.

```python
from data_quality.core import ValidationIssue, ValidationResult
```

## `ValidationIssue`

A `str` subclass that also carries a machine-readable `code` and `field`.
Because it is a real string, existing code that joins, searches, logs or
serialises issue messages keeps working unchanged, while new code can branch on
`issue.code` / `issue.field`.

```python
issue = ValidationIssue("BPM out of range: 50", code="value_out_of_range", field="bpm")
str(issue)  # "BPM out of range: 50"
issue.code  # "value_out_of_range"
issue.field  # "bpm"
```

## `ValidationResult`

Accumulates issues for a single validated item.

```python
result = ValidationResult()
result.add_issue("something wrong", code="my_code", field="my_field")

result.passed  # False once any issue is added
result.issues  # list[ValidationIssue]
result.fields  # dict of the values that were validated (optional)
result.flagged_fields()  # set of field names already reported
bool(result)  # same as result.passed
```

`flagged_fields()` splits comma-separated field names so a later pass (e.g. full
model validation) can skip fields an explicit check already reported, avoiding
double-counting.

## Writing a new domain

A domain's `validate_*` function builds a `ValidationResult`, calls `add_issue`
for each problem it finds, and returns it. See `data_quality.music.checks` for a
worked example.
