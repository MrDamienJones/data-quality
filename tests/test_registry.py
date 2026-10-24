"""Tests for the check registry and the ``validate_row`` runner (no pandas)."""

import pytest

from data_quality.music_edm import list_checks, validate_row

EXPECTED_IDS = [
    "missing_fields",
    "bpm_range",
    "track_number_range",
    "year_range",
    "bpm_track_mismatch",
    "invalid_camelot",
    "corrupted_field",
    "invalid_key",
    "key_album_mismatch",
    "subtitle_drift",
    "filename_drift",
    "artist_field_mismatch",
    "title_format",
    "publisher_grouping",
    "bracketed_numbers",
    "discogs_missing",
]


def test_list_checks_is_the_stable_ordered_id_list():
    assert list_checks() == EXPECTED_IDS


def test_include_runs_only_selected_in_registry_order():
    # Only bpm_range selected; bpm out of range -> one issue, nothing skipped
    # other than deselected checks (which are not recorded in skipped).
    result = validate_row({"bpm": 999}, include=["bpm_range"])
    assert [issue.code for issue in result.issues] == ["value_out_of_range"]
    assert result.skipped == []


def test_exclude_removes_a_check():
    result = validate_row({"bpm": 999}, include=["bpm_range"], exclude=["bpm_range"])
    assert result.issues == []


def test_exclude_wins_over_include():
    # year_range would fire, but exclude takes it out even though included.
    result = validate_row(
        {"year": 1800},
        include=["bpm_range", "year_range"],
        exclude=["year_range"],
    )
    assert result.issues == []


def test_unknown_include_id_raises_value_error():
    with pytest.raises(ValueError, match="list_checks"):
        validate_row({"bpm": 128}, include=["not_a_check"])


def test_unknown_exclude_id_raises_value_error():
    with pytest.raises(ValueError, match="list_checks"):
        validate_row({"bpm": 128}, exclude=["flie_size"])


def test_empty_include_raises_value_error():
    with pytest.raises(ValueError, match="non-empty"):
        validate_row({"bpm": 128}, include=[])


def test_empty_exclude_is_benign():
    result = validate_row({"bpm": 128}, include=["bpm_range"], exclude=[])
    assert result.issues == []


def test_auto_skip_when_required_field_absent():
    # bpm key absent entirely -> bpm_range skips (its required field is absent).
    result = validate_row({"year": 2000})
    assert "bpm_range" in result.skipped


def test_present_but_none_runs_and_does_not_skip():
    # bpm key present with value None -> bpm_range runs, no issue, not skipped.
    result = validate_row({"bpm": None})
    assert "bpm_range" not in result.skipped
    assert all(issue.code != "value_out_of_range" for issue in result.issues)


def test_out_of_range_value_fires():
    result = validate_row({"bpm": 10}, include=["bpm_range"])
    assert [issue.code for issue in result.issues] == ["value_out_of_range"]


def test_empty_row_runs_no_check():
    # Every check needs at least one field, so an empty row skips them all.
    result = validate_row({})
    assert result.ran == []
    assert result.skipped == EXPECTED_IDS


def test_track_number_range_only_when_bpm_blank():
    absent = validate_row({"track_number": 50})
    blank = validate_row({"track_number": 50, "bpm": None})
    present = validate_row({"track_number": 50, "bpm": 128})
    assert ("value_out_of_range", "track_number") in {
        (i.code, i.field) for i in absent.issues
    }
    assert ("value_out_of_range", "track_number") in {
        (i.code, i.field) for i in blank.issues
    }
    # With a BPM present, bpm_track_mismatch reports it instead.
    assert [i.code for i in present.issues] == ["bpm_track_mismatch"]


def test_split_key_checks_skip_independently():
    # A key with no album column: invalid_key runs, key_album_mismatch skips.
    result = validate_row({"initialkey": "Xm"})
    assert "invalid_key" in result.ran
    assert "key_album_mismatch" in result.skipped
    assert [i.code for i in result.issues] == ["invalid_key"]


def test_split_publisher_checks_skip_independently():
    # A grouping with no publisher column (as in iTunes exports).
    result = validate_row({"grouping": "Label (12)"})
    assert "publisher_grouping" in result.skipped
    assert "bracketed_numbers" in result.ran
    assert [(i.code, i.field) for i in result.issues] == [
        ("bracketed_numbers", "grouping")
    ]


def test_missing_fields_checks_only_guard_fields_present():
    # album_artist_sort etc. absent: only the carried guard fields are checked.
    result = validate_row(
        {"title": None, "artist": "A", "year": 2020}, include=["missing_fields"]
    )
    assert [(i.code, i.field) for i in result.issues] == [("missing_fields", "title")]
    assert result.ran == ["missing_fields"]


def test_missing_fields_skips_when_no_guard_field_present():
    result = validate_row({"bpm": 128}, include=["missing_fields"])
    assert result.skipped == ["missing_fields"]
    assert result.ran == []


def test_ran_lists_checks_in_registry_order():
    result = validate_row({"year": 2000}, include=["year_range", "missing_fields"])
    assert result.ran == ["missing_fields", "year_range"]


def test_negative_discogs_id_out_of_range():
    result = validate_row({"discogs_id": -5}, include=["discogs_missing"])
    assert [(i.code, i.field) for i in result.issues] == [
        ("value_out_of_range", "discogs_id")
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("128", 128), (" 128 ", 128), (128.0, 128), ("", None), (None, None)],
)
def test_int_fields_coerced(raw, expected):
    result = validate_row({"bpm": raw}, include=["bpm_range"])
    assert result.fields["bpm"] == expected
    assert result.issues == []


def test_int_string_still_range_checked():
    result = validate_row({"bpm": "50"}, include=["bpm_range"])
    assert [issue.code for issue in result.issues] == ["value_out_of_range"]


@pytest.mark.parametrize("raw", ["128a", 128.5, float("inf"), True])
def test_unparseable_int_field_is_reported_not_raised(raw):
    result = validate_row({"bpm": raw}, include=["bpm_range"])
    assert result.fields["bpm"] is None
    assert [(i.code, i.field) for i in result.issues] == [("pydantic_error", "bpm")]
    assert result.issues[0].startswith("Pydantic: bpm: Input should be")


def test_unparseable_year_not_also_reported_missing():
    # Every guard field present so missing_fields runs; only year is bad.
    fields = dict.fromkeys(
        (
            "title",
            "artist",
            "album",
            "initialkey",
            "encodedby",
            "album_artist",
            "album_artist_sort",
            "subtitle",
        ),
        "x",
    )
    fields["year"] = "20x0"
    result = validate_row(fields, include=["missing_fields"])
    assert [(i.code, i.field) for i in result.issues] == [("pydantic_error", "year")]


def test_unparseable_discogs_id_not_also_reported_missing():
    result = validate_row({"discogs_id": "abc"}, include=["discogs_missing"])
    assert [i.code for i in result.issues] == ["pydantic_error"]


def test_result_fields_is_always_full_canonical_shape():
    result = validate_row({"bpm": 128})
    # Every canonical field key is present even when the source supplied none.
    for name in ("title", "artist", "album", "discogs_id", "year"):
        assert name in result.fields


def _issues(fields):
    return [(i.code, i.field) for i in validate_row(fields).issues]


def test_corrupted_key_reported_once():
    # invalid_key and key_album_mismatch leave a corrupted key to corrupted_field.
    assert _issues({"initialkey": "C/", "album": "08B-CM"}) == [
        ("corrupted_field", "initialkey")
    ]


@pytest.mark.parametrize(
    ("track", "reported"), [(99, True), (100, False), (200, False), (201, True)]
)
def test_track_number_range_boundaries(track, reported):
    issue = ("value_out_of_range", "track_number")
    assert (issue in _issues({"track_number": track})) is reported


def test_unparseable_bpm_counts_as_blank_for_track_number():
    # The bad BPM is reported, and the track number is still range-checked.
    assert _issues({"track_number": 250, "bpm": "12x"}) == [
        ("pydantic_error", "bpm"),
        ("value_out_of_range", "track_number"),
    ]


def test_bracketed_numbers_reports_each_field():
    assert _issues({"publisher": "Label (1)", "grouping": "Label (1)"}) == [
        ("bracketed_numbers", "publisher"),
        ("bracketed_numbers", "grouping"),
    ]
