"""Tests for the check registry and the ``validate_row`` runner (no pandas)."""

import pytest

from data_quality.music_edm import list_checks, validate_row

EXPECTED_IDS = [
    "missing_fields",
    "bpm_range",
    "year_range",
    "bpm_track_mismatch",
    "invalid_camelot",
    "corrupted_field",
    "key_album_mismatch",
    "subtitle_drift",
    "filename_drift",
    "artist_field_mismatch",
    "title_format",
    "publisher_grouping",
    "discogs_missing",
    "file_size",
    "pydantic_fallback",
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


def test_empty_required_checks_never_skip():
    # publisher_grouping and file_size have empty required sets, so they always
    # run and never land in skipped regardless of the input dict.
    result = validate_row({})
    assert "publisher_grouping" not in result.skipped
    assert "file_size" not in result.skipped


def test_result_fields_is_always_full_canonical_shape():
    result = validate_row({"bpm": 128})
    # Every canonical field key is present even when the source supplied none.
    for name in ("title", "artist", "album", "discogs_id", "year"):
        assert name in result.fields
