"""Tests for the ported music data quality checks.

A known-good field set passes every check; individual mutations prove each
check fires with the expected issue code.
"""

import pytest

from data_quality.music_edm import (
    CHECK_TYPES,
    AudioFormat,
    categorize_issue,
    generate_filename,
    validate_metadata,
    validate_row,
)

# A fully valid field set.
#   album "08B-CM" -> Camelot key "C", so initialkey must be "C".
#   title has parentheses; filename is the generated stem; subtitle matches
#   "Artist - Title Album BPM Year"; album_artist* equal artist; bpm == track.
VALID_ARTIST = "Artist"
VALID_TITLE = "Some Track (Extended Mix)"
VALID_ALBUM = "08B-CM"
VALID_BPM = 128
VALID_YEAR = 2020
VALID_FILENAME_STEM = generate_filename(VALID_ARTIST, VALID_TITLE)
VALID_SUBTITLE = (
    f"{VALID_ARTIST} - {VALID_TITLE} {VALID_ALBUM} {VALID_BPM} {VALID_YEAR}"
)


def valid_fields() -> dict:
    return {
        "bpm": VALID_BPM,
        "track_number": VALID_BPM,
        "title": VALID_TITLE,
        "artist": VALID_ARTIST,
        "album": VALID_ALBUM,
        "initialkey": "C",
        "encodedby": "me",
        "album_artist": VALID_ARTIST,
        "album_artist_sort": VALID_ARTIST,
        "subtitle": VALID_SUBTITLE,
        "publisher": "Label",
        "grouping": "Label",
        "year": VALID_YEAR,
        "discogs_id": 12345,
    }


def test_valid_fields_pass():
    result = validate_metadata(valid_fields(), filename_stem=VALID_FILENAME_STEM)
    assert result.passed, [str(i) for i in result.issues]
    assert result.issues == []
    assert bool(result) is True


def codes(result) -> set:
    return {issue.code for issue in result.issues}


def test_missing_required_fields():
    fields = valid_fields()
    fields["title"] = None
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert not result.passed
    assert "missing_fields" in codes(result)


def test_bpm_out_of_range():
    fields = valid_fields()
    fields["bpm"] = 50
    fields["track_number"] = 50
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "value_out_of_range" in codes(result)


def test_year_out_of_range():
    fields = valid_fields()
    fields["year"] = 1900
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "value_out_of_range" in codes(result)


def test_bpm_track_mismatch():
    fields = valid_fields()
    fields["track_number"] = 130
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "bpm_track_mismatch" in codes(result)


def test_invalid_camelot_album():
    fields = valid_fields()
    fields["album"] = "ZZ9-Plural"
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "invalid_camelot" in codes(result)


def test_corrupted_initialkey():
    fields = valid_fields()
    fields["initialkey"] = "C/\x00"
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "corrupted_field" in codes(result)


def test_key_album_mismatch():
    fields = valid_fields()
    fields["initialkey"] = "Am"  # valid notation but wrong for 08B-CM (expects C)
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "key_album_mismatch" in codes(result)


def test_subtitle_drift():
    fields = valid_fields()
    fields["subtitle"] = "wrong subtitle"
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "subtitle_drift" in codes(result)


def test_filename_drift():
    fields = valid_fields()
    result = validate_metadata(fields, "WrongName")
    assert "filename_drift" in codes(result)


def test_filename_case_drift_has_its_own_code():
    fields = valid_fields()
    result = validate_metadata(fields, VALID_FILENAME_STEM.lower())
    assert codes(result) == {"filename_case_drift"}


def test_filename_content_drift_is_not_case_drift():
    fields = valid_fields()
    result = validate_metadata(fields, "WrongName")
    assert "filename_case_drift" not in codes(result)


def test_artist_field_mismatch():
    fields = valid_fields()
    fields["album_artist"] = "Someone Else"
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "artist_field_mismatch" in codes(result)


def test_title_missing_parentheses():
    fields = valid_fields()
    # keep filename/subtitle consistent with the new title so only the
    # parentheses check fires for the title_format code
    fields["title"] = "No Parens Title"
    fields["subtitle"] = (
        f"{VALID_ARTIST} - No Parens Title {VALID_ALBUM} {VALID_BPM} {VALID_YEAR}"
    )
    stem = generate_filename(VALID_ARTIST, "No Parens Title")
    result = validate_metadata(fields, stem)
    assert "title_format" in codes(result)


def test_publisher_grouping_mismatch():
    fields = valid_fields()
    fields["grouping"] = "Different"
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "publisher_grouping" in codes(result)


def test_publisher_bracketed_numbers():
    fields = valid_fields()
    fields["publisher"] = "Label (123)"
    fields["grouping"] = "Label (123)"
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "publisher_grouping" in codes(result)


def test_discogs_missing():
    fields = valid_fields()
    fields["discogs_id"] = 0
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert "discogs_missing" in codes(result)


def test_int_fields_as_strings_pass():
    # Tags read from disk are often text; integer strings must validate.
    fields = valid_fields()
    for name in ("bpm", "track_number", "year", "discogs_id"):
        fields[name] = str(fields[name])
    result = validate_metadata(fields, VALID_FILENAME_STEM)
    assert result.passed, [str(i) for i in result.issues]


# Track data that contains the words a keyword matcher would trip on.
TRICKY_TITLE = "Missing Camelot Key (Publisher Mix)"
TRICKY_ARTIST = "Discogs Range"


def _one_issue_per_message_kind():
    """Every kind of issue message the checks emit, from tricky track data."""
    stem = generate_filename(TRICKY_ARTIST, TRICKY_TITLE)
    subtitle = f"{TRICKY_ARTIST} - {TRICKY_TITLE} 08B-CM 128 2020"
    cases = [
        ({"title": None, "artist": TRICKY_ARTIST, "year": None}, {}),
        ({"bpm": 50}, {}),
        ({"year": 1900}, {}),
        ({"discogs_id": None}, {}),
        ({"discogs_id": -1}, {}),
        ({"bpm": 128, "track_number": 130}, {}),
        ({"album": "Missing Key"}, {}),
        ({"initialkey": "C/"}, {}),
        ({"initialkey": "Xm"}, {}),
        ({"initialkey": "Am", "album": "08B-CM"}, {}),
        (
            {
                "artist": TRICKY_ARTIST,
                "title": TRICKY_TITLE,
                "album": "08B-CM",
                "bpm": 128,
                "year": 2020,
                "subtitle": subtitle + " x",
            },
            {"filename_stem": stem},
        ),
        ({"artist": TRICKY_ARTIST, "title": TRICKY_TITLE}, {"filename_stem": "x"}),
        (
            {"artist": TRICKY_ARTIST, "title": TRICKY_TITLE},
            {"filename_stem": stem.lower()},
        ),
        ({"artist": TRICKY_ARTIST, "album_artist": "Missing Key"}, {}),
        ({"artist": TRICKY_ARTIST, "album_artist_sort": "Missing Key"}, {}),
        ({"title": "Missing Key Camelot"}, {}),
        ({"publisher": "Missing Key", "grouping": "Camelot"}, {}),
        ({"publisher": "Label (12)"}, {}),
        ({"grouping": "Label [12]"}, {}),
        ({"bpm": "12x"}, {}),
    ]
    issues = []
    for fields, kwargs in cases:
        issues.extend(validate_row(fields, **kwargs).issues)
    return issues


def test_every_check_message_is_produced():
    codes_seen = {issue.code for issue in _one_issue_per_message_kind()}
    # Every code in CHECK_TYPES except the consumer-side and reconcile codes.
    other = {"unreadable", "unmatched", "duplicate_key", "missing_key"}
    other.add("cross_source_mismatch")
    assert codes_seen == set(CHECK_TYPES) - other


def test_plain_string_round_trips_to_code_and_field():
    # A plain copy of each message must classify to the issue's own code and
    # field, even though the track data contains misleading keywords.
    for issue in _one_issue_per_message_kind():
        assert categorize_issue(str(issue)) == (issue.code, issue.field), str(issue)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Could not read metadata", ("unreadable", "file")),
        ("Something nobody emits", ("pydantic_error", "unknown")),
        ("Pydantic: year", ("pydantic_error", "unknown")),
    ],
)
def test_categorize_other_strings(message, expected):
    assert categorize_issue(message) == expected


def test_missing_keys_treated_as_none():
    # A sparse dict must not raise; missing keys become None.
    result = validate_metadata({}, filename_stem="whatever")
    assert not result.passed
    assert "missing_fields" in codes(result)


class TestGenerateFilename:
    def test_basic(self):
        assert generate_filename("Artist", "Title (Mix)") == "Artist-Title-Mix"

    def test_accents_replaced(self):
        assert generate_filename("Beyoncé", "Déjà (Vu)") == "Beyonce-Deja-Vu"

    def test_two_dashes_allowed(self):
        # Separator dash + the dash from the final "(" is the 2-dash maximum
        # reachable through the public function (internal hyphens are stripped,
        # so the ">2 dashes" guard is defensive and not exercised here).
        assert generate_filename("A (b) (c)", "T (d) (e)") == "Abc-Td-e"

    def test_unicode_hyphen_normalized_like_ascii(self):
        # U+2010 (HYPHEN), seen in the real iTunes export, must behave exactly
        # like a normal ASCII hyphen: stripped from within a field.
        assert generate_filename("Above And Beyond", "Tri\u2010State") == (
            generate_filename("Above And Beyond", "Tri-State")
        )
        assert generate_filename("Above And Beyond", "Tri\u2010State") == (
            "AboveAndBeyond-TriState"
        )

    @pytest.mark.parametrize(
        "dash",
        [
            "\u00ad",
            "\u2010",
            "\u2011",
            "\u2012",
            "\u2013",
            "\u2014",
            "\u2015",
            "\u2212",
            "\ufe58",
            "\ufe63",
            "\uff0d",
        ],
    )
    def test_all_dash_lookalikes_normalized(self, dash):
        assert generate_filename("Artist", f"Tri{dash}State") == "Artist-TriState"

    @pytest.mark.parametrize("quote", ["'", "‘", "’", "´"])
    def test_apostrophe_lookalikes_removed(self, quote):
        # U+2019 and U+00B4 both appear as apostrophes in the real mp3tag export.
        assert generate_filename("Armin", f"Armin{quote}s (Mix)") == "Armin-Armins-Mix"

    def test_double_quote_lookalikes_removed(self):
        assert generate_filename("A", "“Q” (Mix)") == "A-Q-Mix"


@pytest.mark.parametrize("ext", ["mp3", ".MP3", ".flac", "wav"])
def test_audio_format_from_extension(ext):
    assert AudioFormat.from_extension(ext).value == ext.lower().removeprefix(".")


def test_audio_format_unsupported_extension_raises():
    with pytest.raises(ValueError, match="Unsupported format: ogg"):
        AudioFormat.from_extension(".ogg")
