"""Integration tests for the optional pandas DataFrame adapter.

Requires the dev extra (pandas + pyarrow). These prove the exact same checks
run origin-independently (CSV-style dict, canonical identity frame, parquet
round-trip) and that per-source auto-skips/auto-excludes behave per design §4.
"""

import pandas as pd

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
        "MTG-FileSizeBytes": 5_000_000,
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
    # mp3tag_csv carries no album_artist_sort / discogs column, so these skip.
    assert summary.skipped_checks == {
        "missing_fields",
        "discogs_missing",
        "pydantic_fallback",
    }


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
    # NOT emit filename_drift on any row (design §4 finding 1).
    df = pd.DataFrame(
        [
            {"artist": VALID_ARTIST, "title": VALID_TITLE},
            {"artist": "Other", "title": "Thing (Mix)"},
        ]
    )
    summary = validate_frame(df)
    assert "filename_drift" not in summary.issue_counts
    # filename_drift is a deselection, not a skip.
    assert "filename_drift" not in summary.skipped_checks


def test_itunes_txt_frame_skips_and_no_file_size_noise():
    df = pd.DataFrame(
        [
            {
                "Name": VALID_TITLE,
                "Artist": VALID_ARTIST,
                "Album": VALID_ALBUM,
                "Grouping": "Label",
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
        "missing_fields",
        "pydantic_fallback",
    }
    assert expected_skips <= summary.skipped_checks
    # No size column -> file_size is auto-excluded, never fires, never skipped.
    assert "file_size" not in summary.issue_counts
    assert "file_size" not in summary.skipped_checks


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


def test_coerce_int_infinity_is_none():
    from data_quality.music_edm.frame import _coerce_int

    assert _coerce_int(float("inf")) is None
    assert _coerce_int(float("-inf")) is None
    assert _coerce_int(float("nan")) is None
    # A finite integral float narrows back to int.
    assert _coerce_int(128.0) == 128
    # A fractional float is not a reliable int.
    assert _coerce_int(128.5) is None
