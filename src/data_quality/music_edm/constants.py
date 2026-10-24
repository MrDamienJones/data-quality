"""Constants and enums for music data quality checks.

Single source of truth for validation ranges, Camelot key maps and the
filename character-replacement table. Ported from the music pipeline and kept
free of pipeline-specific logging/error-message constants.
"""

from enum import Enum


class AudioFormat(Enum):
    """Supported audio formats."""

    MP3 = "mp3"
    FLAC = "flac"
    WAV = "wav"

    @classmethod
    def from_extension(cls, extension: str) -> "AudioFormat":
        """Get format from a file extension (with or without leading dot)."""
        ext = extension.lower().removeprefix(".")
        try:
            return cls(ext)
        except ValueError as exc:
            raise ValueError(f"Unsupported format: {ext}") from exc


class MetadataField(Enum):
    """Metadata field types."""

    BPM = "bpm"
    KEY = "key"
    DISCOGS_ID = "discogs_id"
    TITLE = "title"
    ARTIST = "artist"
    ALBUM_ARTIST = "album_artist"
    ALBUM_ARTIST_SORT = "album_artist_sort"
    SUBTITLE = "subtitle"
    PUBLISHER = "publisher"
    GROUPING = "grouping"
    TRACK_NUMBER = "track_number"
    ENCODED_BY = "encoded_by"
    YEAR = "year"


# Validation ranges (single source of truth for every validator)
BPM_MIN = 100
BPM_MAX = 200
YEAR_MIN = 1970

# Canonical fields whose values validate_row parses to ``int | None`` rather
# than ``str | None``.
INT_FIELDS: frozenset[str] = frozenset({"year", "track_number", "bpm", "discogs_id"})

# Music key constants
CAMELOT_NOTATIONS = {
    "01A-Abm",
    "01B-BM",
    "02A-Ebm",
    "02B-GbM",
    "03A-Bbm",
    "03B-DbM",
    "04A-Fm",
    "04B-AbM",
    "05A-Cm",
    "05B-EbM",
    "06A-Gm",
    "06B-BbM",
    "07A-Dm",
    "07B-FM",
    "08A-Am",
    "08B-CM",
    "09A-Em",
    "09B-GM",
    "10A-Bm",
    "10B-DM",
    "11A-Gbm",
    "11B-AM",
    "12A-Dbm",
    "12B-EM",
}

INITIALKEY_NOTATIONS = {
    "Abm",
    "B",
    "Ebm",
    "Gb",
    "Bbm",
    "Db",
    "Fm",
    "Ab",
    "Cm",
    "Eb",
    "Gm",
    "Bb",
    "Dm",
    "F",
    "Am",
    "C",
    "Em",
    "G",
    "Bm",
    "D",
    "Gbm",
    "A",
    "Dbm",
    "E",
}

CAMELOT_KEYS = {
    "01A-Abm": "Abm",
    "01B-BM": "B",
    "02A-Ebm": "Ebm",
    "02B-GbM": "Gb",
    "03A-Bbm": "Bbm",
    "03B-DbM": "Db",
    "04A-Fm": "Fm",
    "04B-AbM": "Ab",
    "05A-Cm": "Cm",
    "05B-EbM": "Eb",
    "06A-Gm": "Gm",
    "06B-BbM": "Bb",
    "07A-Dm": "Dm",
    "07B-FM": "F",
    "08A-Am": "Am",
    "08B-CM": "C",
    "09A-Em": "Em",
    "09B-GM": "G",
    "10A-Bm": "Bm",
    "10B-DM": "D",
    "11A-Gbm": "Gbm",
    "11B-AM": "A",
    "12A-Dbm": "Dbm",
    "12B-EM": "E",
}

# Character replacement for filename generation
CHARACTER_REPLACEMENTS = {
    "á": "a",
    "à": "a",
    "ä": "a",
    "â": "a",
    "ã": "a",
    "å": "a",
    "æ": "ae",
    "Á": "A",
    "À": "A",
    "Ä": "A",
    "Â": "A",
    "Ã": "A",
    "Å": "A",
    "Æ": "AE",
    "é": "e",
    "è": "e",
    "ë": "e",
    "ê": "e",
    "É": "E",
    "È": "E",
    "Ë": "E",
    "Ê": "E",
    "í": "i",
    "ì": "i",
    "ï": "i",
    "î": "i",
    "Í": "I",
    "Ì": "I",
    "Ï": "I",
    "Î": "I",
    "ó": "o",
    "ò": "o",
    "ö": "o",
    "ô": "o",
    "õ": "o",
    "ø": "o",
    "Ó": "O",
    "Ò": "O",
    "Ö": "O",
    "Ô": "O",
    "Õ": "O",
    "Ø": "O",
    "ú": "u",
    "ù": "u",
    "ü": "u",
    "û": "u",
    "Ú": "U",
    "Ù": "U",
    "Ü": "U",
    "Û": "U",
    "ñ": "n",
    "Ñ": "N",
    "ç": "c",
    "Ç": "C",
    # Unicode dash/hyphen lookalikes -> ASCII hyphen. Mapped before the
    # internal "-" strip in generate_filename, so they are treated exactly
    # like a normal hyphen (U+002D) rather than drifting the filename.
    "\u00ad": "-",  # SOFT HYPHEN
    "\u2010": "-",  # HYPHEN
    "\u2011": "-",  # NON-BREAKING HYPHEN
    "\u2012": "-",  # FIGURE DASH
    "\u2013": "-",  # EN DASH
    "\u2014": "-",  # EM DASH
    "\u2015": "-",  # HORIZONTAL BAR
    "\u2212": "-",  # MINUS SIGN
    "\ufe58": "-",  # SMALL EM DASH
    "\ufe63": "-",  # SMALL HYPHEN-MINUS
    "\uff0d": "-",  # FULLWIDTH HYPHEN-MINUS
    # Typographic quote/apostrophe lookalikes, removed like their ASCII forms.
    "\u2018": "",  # LEFT SINGLE QUOTATION MARK
    "\u2019": "",  # RIGHT SINGLE QUOTATION MARK
    "\u00b4": "",  # ACUTE ACCENT (used as an apostrophe)
    "\u201c": "",  # LEFT DOUBLE QUOTATION MARK
    "\u201d": "",  # RIGHT DOUBLE QUOTATION MARK
    "&": "And",
    "!": "",
    '"': "",
    "£": "",
    "$": "",
    "%": "",
    "^": "",
    "*": "",
    "@": "At",
    "#": "",
    "~": "",
    "`": "",
    "|": "",
    "\\": "",
    "/": "",
    ":": "",
    "<": "",
    ">": "",
    "?": "",
    "+": "And",
    "=": "",
    "{": "",
    "}": "",
    "[": "",
    "]": "",
    ",": "",
    ".": "",
    "'": "",
}

# Issue code -> dashboard check type
CHECK_TYPES = {
    "unreadable": "file",
    "missing_fields": "field_presence",
    "discogs_missing": "field_presence",
    "value_out_of_range": "value_validity",
    "invalid_camelot": "value_validity",
    "invalid_key": "value_validity",
    "corrupted_field": "value_validity",
    "title_format": "value_validity",
    "bpm_track_mismatch": "cross_field",
    "key_album_mismatch": "cross_field",
    "subtitle_drift": "cross_field",
    "filename_drift": "cross_field",
    "filename_case_drift": "cross_field",
    "artist_field_mismatch": "cross_field",
    "publisher_grouping": "cross_field",
    "bracketed_numbers": "value_validity",
    "pydantic_error": "pydantic",
    # reconcile_frames (cross-source) codes
    "unmatched": "join",
    "duplicate_key": "join",
    "missing_key": "join",
    "cross_source_mismatch": "cross_source",
}
