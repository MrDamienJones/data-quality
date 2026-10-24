"""Music metadata data quality checks.

Public API:

- Filenames: ``generate_filename``.
- Checks: ``validate_metadata`` (the full suite on an extracted dict) and
  ``categorize_issue``.
- Constants: ranges, Camelot maps, enums and the check-type map.
"""

from ..core.result import ValidationIssue, ValidationResult
from .checks import EXPECTED_FIELDS, categorize_issue, validate_metadata
from .constants import (
    BPM_MAX,
    BPM_MIN,
    CAMELOT_KEYS,
    CAMELOT_NOTATIONS,
    CHARACTER_REPLACEMENTS,
    CHECK_TYPES,
    INITIALKEY_NOTATIONS,
    YEAR_MIN,
    AudioFormat,
    MetadataField,
)
from .field_maps import SourceMap, itunes_txt, mp3tag_csv
from .filenames import generate_filename
from .frame import FrameValidationSummary, validate_frame
from .reconcile import FieldMismatch, ReconcileSummary, reconcile_frames
from .registry import CHECK_REGISTRY, Check, list_checks, validate_row

__all__ = [
    # checks
    "validate_metadata",
    "categorize_issue",
    "EXPECTED_FIELDS",
    # registry / row runner
    "validate_row",
    "list_checks",
    "Check",
    "CHECK_REGISTRY",
    # pandas adapter (optional; pandas imported lazily at call time)
    "validate_frame",
    "FrameValidationSummary",
    # cross-source reconciliation (optional; pandas imported lazily)
    "reconcile_frames",
    "ReconcileSummary",
    "FieldMismatch",
    # field maps
    "SourceMap",
    "mp3tag_csv",
    "itunes_txt",
    # results (re-exported for convenience)
    "ValidationIssue",
    "ValidationResult",
    # filenames
    "generate_filename",
    # constants
    "AudioFormat",
    "MetadataField",
    "BPM_MIN",
    "BPM_MAX",
    "YEAR_MIN",
    "CAMELOT_NOTATIONS",
    "INITIALKEY_NOTATIONS",
    "CAMELOT_KEYS",
    "CHARACTER_REPLACEMENTS",
    "CHECK_TYPES",
]
