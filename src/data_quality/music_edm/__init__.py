"""Music metadata data quality checks.

Public API:

- Models: ``AudioMetadata``, ``Config``, ``MetadataMapping``, ``PathConfig``,
  ``ValidationConfig``, ``AudioFormatEnum``, and ``generate_filename``.
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
    MIN_FILE_SIZE_BYTES,
    YEAR_MIN,
    AudioFormat,
    MetadataField,
)
from .field_maps import SourceMap, itunes_txt, mp3tag_csv
from .models import (
    AudioFormatEnum,
    AudioMetadata,
    Config,
    MetadataMapping,
    PathConfig,
    ValidationConfig,
    generate_filename,
)
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
    # field maps
    "SourceMap",
    "mp3tag_csv",
    "itunes_txt",
    # results (re-exported for convenience)
    "ValidationIssue",
    "ValidationResult",
    # models
    "AudioMetadata",
    "Config",
    "MetadataMapping",
    "PathConfig",
    "ValidationConfig",
    "AudioFormatEnum",
    "generate_filename",
    # constants
    "AudioFormat",
    "MetadataField",
    "BPM_MIN",
    "BPM_MAX",
    "YEAR_MIN",
    "MIN_FILE_SIZE_BYTES",
    "CAMELOT_NOTATIONS",
    "INITIALKEY_NOTATIONS",
    "CAMELOT_KEYS",
    "CHARACTER_REPLACEMENTS",
    "CHECK_TYPES",
]
