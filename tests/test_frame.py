"""Integration tests for the optional pandas DataFrame adapter.

Requires the dev extra (pandas + pyarrow). These prove the exact same checks
run origin-independently (CSV-style dict, canonical identity frame, parquet
round-trip) and that per-source auto-skips/auto-excludes behave as described
in "DataFrame Adapter" in docs/architecture-checks-registry.md.
"""

import pandas as pd
import pytest

from data_quality.music_edm import (
    generate_filename,
    validate_frame,
)

VALID_ARTIST = "Artist"
VALID_TITLE = "Some Track (Extended Mix)"
VALID_ALBUM = "08B-CM"  # Camelot key "C"
VALID_BPM = 128
VALID_YEAR = 2020
VALID_FILENAME_STEM = generate_filename(VALID_ARTIST, VALID_TITLE)
VALID_SUBTITLE = (
    f"{VALID_ARTIST} - {VALID_TITLE} {VALID_ALBUM} {VALID_BPM} {VALID_YEAR}"
)


def _mp3tag_row(**overrides):
    """One fully valid mp3tag_csv-style raw row (raw column keys)."""
    row = {
        "MTG-Title": VALID_TITLE,
        "MTG-Subtitle": VALID_SUBTITLE,
        "MTG-Artist": VALID_ARTIST,
        "MTG-AlbumArtist": VALID_ARTIST,
        "MTG-Album": VALID_ALBUM,
        "MTG-Year": VALID_YEAR,
        "MTG-TrackNumber": VALID_BPM,
        "MTG-Publisher": "Label",
        "MTG-EncodedBy": "me",
        "MTG-GroupDescription": "Label",
        "MTG-InitialKey": "C",
        "MTG-BPM": VALID_BPM,
        "MTG-Filename": f"{VALID_FILENAME_STEM}.mp3",
    }
    row.update(overrides)
    return row


def test_mp3tag_frame_all_pass():
    df = pd.DataFrame([_mp3tag_row(), _mp3tag_row()])
    summary = validate_frame(df, source="mp3tag_csv")

    assert summary.total == 2
    assert summary.passed == 2
    assert summary.pass_rate == 1.0
    assert summary.issue_counts == {}
    assert list(summary.failures()) == []
    # mp3tag_csv carries no discogs column, so only discogs_missing skips.
    assert summary.skipped_checks == {"discogs_missing"}
    assert "missing_fields" in summary.checks_run
    assert len(summary.checks_selected) == 13


@pytest.mark.parametrize(
    ("column", "field"),
    [
        ("MTG-Title", "title"),
        ("MTG-Artist", "artist"),
        ("MTG-Album", "album"),
        ("MTG-InitialKey", "initialkey"),
        ("MTG-Year", "year"),
        ("MTG-EncodedBy", "encodedby"),
    ],
)
def test_mp3tag_blank_guard_field_reported(column, field):
    # mp3tag_csv lacks album_artist_sort; blank values in the guard fields it
    # does carry must still be reported.
    df = pd.DataFrame([_mp3tag_row(**{column: None})])
    summary = validate_frame(df, source="mp3tag_csv")
    missing = [i for i in summary.results[0].issues if i.code == "missing_fields"]
    assert [i.field for i in missing] == [field]


def test_mp3tag_frame_counts_issues_and_failures():
    good = _mp3tag_row()
    bad = _mp3tag_row(**{"MTG-BPM": 50, "MTG-TrackNumber": 50})  # out of range
    df = pd.DataFrame([good, bad], index=["ok", "oops"])
    summary = validate_frame(df, source="mp3tag_csv")

    assert summary.total == 2
    assert summary.passed == 1
    assert summary.pass_rate == 0.5
    assert summary.issue_counts["value_out_of_range"] == 1
    failures = list(summary.failures())
    assert len(failures) == 1
    assert failures[0][0] == "oops"  # original index preserved
    assert not failures[0][1].passed


def test_blank_int_cell_runs_check_not_skipped():
    # A blank BPM cell maps to None (present key, None value) -> bpm_range runs
    # and no-ops; it must NOT land in skipped_checks.
    df = pd.DataFrame([_mp3tag_row(**{"MTG-BPM": None, "MTG-TrackNumber": None})])
    summary = validate_frame(df, source="mp3tag_csv")
    assert "bpm_range" not in summary.skipped_checks


def test_empty_frame_edge_case():
    df = pd.DataFrame(columns=list(_mp3tag_row().keys()))
    summary = validate_frame(df, source="mp3tag_csv")
    assert summary.total == 0
    assert summary.passed == 0
    assert summary.pass_rate == 0.0
    assert summary.results == []
    assert summary.row_index == []
    assert summary.issue_counts == {}
    assert summary.skipped_checks == set()


def test_empty_include_raises_even_on_empty_frame():
    df = pd.DataFrame(columns=list(_mp3tag_row().keys()))
    with pytest.raises(ValueError, match="non-empty"):
        validate_frame(df, source="mp3tag_csv", include=[])


def test_blank_filename_cell_is_reported():
    # The source has a filename column, so a blank cell is a data problem.
    df = pd.DataFrame([_mp3tag_row(**{"MTG-Filename": None})])
    summary = validate_frame(df, source="mp3tag_csv")
    assert summary.issue_counts["filename_drift"] == 1


def test_empty_frame_with_typo_exclude_raises():
    df = pd.DataFrame(columns=list(_mp3tag_row().keys()))
    try:
        validate_frame(df, source="mp3tag_csv", exclude=["flie_size"])
    except ValueError as e:
        assert "flie_size" in str(e)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected ValueError for a typo'd exclude id")


def test_identity_frame_without_filename_stem_no_drift():
    # A canonical-name frame with artist+title but NO filename_stem column must
    # NOT emit filename_drift on any row.
    df = pd.DataFrame(
        [
            {"artist": VALID_ARTIST, "title": VALID_TITLE},
            {"artist": "Other", "title": "Thing (Mix)"},
        ]
    )
    summary = validate_frame(df)
    assert "filename_drift" not in summary.issue_counts
    # It could not run for lack of a column, so it is reported as skipped.
    assert "filename_drift" in summary.skipped_checks
    assert "filename_drift" not in summary.checks_run


def test_caller_excluded_check_is_not_reported_as_skipped():
    df = pd.DataFrame([{"artist": VALID_ARTIST, "title": VALID_TITLE}])
    summary = validate_frame(df, exclude=["filename_drift"])
    assert "filename_drift" not in summary.skipped_checks
    summary = validate_frame(df, include=["title_format"])
    assert summary.skipped_checks == set()
    assert summary.checks_run == {"title_format"}


def test_exclude_as_generator_is_honoured():
    # A one-shot iterator must not be consumed by the up-front id validation.
    df = pd.DataFrame([{"artist": VALID_ARTIST, "title": "No Parens"}])
    summary = validate_frame(df, exclude=(cid for cid in ["title_format"]))
    assert "title_format" not in summary.issue_counts


def test_full_identity_frame_without_filename_stem_passes():
    # Every canonical field present but no filename column: nothing may fail
    # on the absent filename.
    df = pd.DataFrame(
        [
            {
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
        ]
    )
    summary = validate_frame(df)
    assert summary.passed == 1, [str(i) for i in summary.results[0].issues]


def test_itunes_txt_frame_skips_and_coverage():
    df = pd.DataFrame(
        [
            {
                "Name": VALID_TITLE,
                "Artist": VALID_ARTIST,
                "Album": VALID_ALBUM,
                "Work": "Label",
                "Track Number": 1,
                "Year": VALID_YEAR,
                "Location": f"/music/{VALID_FILENAME_STEM}.mp3",
            }
        ]
    )
    summary = validate_frame(df, source="itunes_txt", exclude=["invalid_camelot"])

    # itunes_txt carries none of these fields, so their checks auto-skip.
    expected_skips = {
        "bpm_range",
        "bpm_track_mismatch",
        "corrupted_field",
        "key_album_mismatch",
        "subtitle_drift",
        "discogs_missing",
    }
    assert summary.skipped_checks == expected_skips
    # missing_fields runs on the guard fields iTunes carries.
    assert "missing_fields" in summary.checks_run
    # invalid_camelot was excluded by the caller, so it is in neither set.
    assert len(summary.checks_run) == 6
    assert len(summary.checks_selected) == 12


def test_itunes_windows_location_basename_on_any_os():
    # iTunes on Windows exports backslash paths; the stem must still be the
    # bare file name when this runs on Linux (e.g. CI).
    df = pd.DataFrame(
        [
            {
                "Name": VALID_TITLE,
                "Artist": VALID_ARTIST,
                "Location": f"C:\\Music\\Club\\{VALID_FILENAME_STEM}.mp3",
            }
        ]
    )
    summary = validate_frame(df, source="itunes_txt", include=["filename_drift"])
    assert summary.issue_counts == {}


def test_parquet_round_trip_origin_independent(tmp_path):
    df = pd.DataFrame([_mp3tag_row(), _mp3tag_row()])
    direct = validate_frame(df, source="mp3tag_csv")

    path = tmp_path / "rows.parquet"
    df.to_parquet(path)  # uses pyarrow
    df_read = pd.read_parquet(path)
    round_tripped = validate_frame(df_read, source="mp3tag_csv")

    assert round_tripped.total == direct.total
    assert round_tripped.passed == direct.passed
    assert round_tripped.pass_rate == direct.pass_rate
    assert round_tripped.skipped_checks == direct.skipped_checks


def test_dirty_int_cell_reported_and_frame_continues():
    df = pd.DataFrame([_mp3tag_row(**{"MTG-BPM": "128a"}), _mp3tag_row()])
    summary = validate_frame(df, source="mp3tag_csv")
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.issue_counts["pydantic_error"] == 1
    ((index, result),) = summary.failures()
    assert index == 0
    assert [i.field for i in result.issues] == ["bpm"]
