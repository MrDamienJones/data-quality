"""Tests for the cross-source reconciliation (requires the dev extra)."""

import builtins

import pandas as pd
import pytest

from data_quality.music_edm import CHECK_TYPES, reconcile_frames

DIR = "C:\\Music\\Club\\"


def _itunes(*rows):
    """iTunes-style frame: rows are (stem, title, year, work)."""
    return pd.DataFrame(
        [
            {
                "Location": f"{DIR}{stem}.mp3",
                "Name": title,
                "Artist": "A",
                "Year": year,
                "Work": work,
            }
            for stem, title, year, work in rows
        ]
    )


def _mp3tag(*rows):
    """mp3tag-style frame: rows are (stem, title, year, group)."""
    return pd.DataFrame(
        [
            {
                "MTG-Path": f"{DIR}{stem}.mp3",
                "MTG-Filename": f"{stem}.mp3",
                "MTG-Title": title,
                "MTG-Artist": "A",
                "MTG-Year": year,
                "MTG-GroupDescription": group,
            }
            for stem, title, year, group in rows
        ]
    )


def _reconcile(left, right, **kwargs):
    return reconcile_frames(
        left, right, left_source="itunes_txt", right_source="mp3tag_csv", **kwargs
    )


def test_identical_sources_pass():
    s = _reconcile(
        _itunes(("A-T1", "T1 (Mix)", "2020", "L")),
        _mp3tag(("A-T1", "T1 (Mix)", "2020", "L")),
    )
    assert s.passed
    assert s.matched == 1
    assert s.issue_counts == {}
    assert s.fields_compared == ["title", "artist", "grouping", "year"]
    assert list(s.records()) == []


def test_unmatched_tracks_reported_per_side():
    s = _reconcile(
        _itunes(("A-T1", "T", "2020", "L"), ("A-OnlyIt", "T", "2020", "L")),
        _mp3tag(("A-T1", "T", "2020", "L"), ("A-OnlyMp", "T", "2020", "L")),
    )
    assert s.matched == 1
    assert s.only_left == [f"{DIR}A-OnlyIt.mp3"]
    assert s.only_right == [f"{DIR}A-OnlyMp.mp3"]
    assert s.issue_counts == {"unmatched": 2}
    sources = {r["source"] for r in s.records()}
    assert sources == {"itunes_txt", "mp3tag_csv"}


def test_path_match_ignores_case_and_slash_direction():
    left = _itunes(("A-T1", "T", "2020", "L"))
    right = _mp3tag(("A-T1", "T", "2020", "L"))
    right["MTG-Path"] = "c:/music/club/a-t1.MP3"
    s = _reconcile(left, right)
    assert s.matched == 1
    assert s.passed


def test_field_mismatch_reported_with_both_values():
    s = _reconcile(
        _itunes(("A-T1", "T (Mix)", "2020", None)),
        _mp3tag(("A-T1", "T (Edit)", "2020", "Label")),
    )
    assert s.mismatch_counts == {"title": 1, "grouping": 1}
    by_field = {m.field: m for m in s.mismatches}
    assert by_field["title"].left == "T (Mix)"
    assert by_field["title"].right == "T (Edit)"
    # One side blank is a mismatch: the label is missing from iTunes.
    assert by_field["grouping"].left is None
    assert by_field["grouping"].right == "Label"
    assert s.issue_counts == {"cross_source_mismatch": 2}


def test_records_include_mismatch_values():
    s = _reconcile(
        _itunes(("A-T1", "T", "2020", None)), _mp3tag(("A-T1", "T", "2020", "L"))
    )
    assert list(s.records()) == [
        {
            "code": "cross_source_mismatch",
            "key": f"{DIR}A-T1.mp3",
            "field": "grouping",
            "source": None,
            "left": None,
            "right": "L",
        }
    ]


def test_blank_text_in_int_field_is_blank():
    s = _reconcile(_itunes(("A-T1", "T", "  ", "L")), _mp3tag(("A-T1", "T", None, "L")))
    assert s.passed


def test_int_fields_compare_as_numbers():
    left = _itunes(("A-T1", "T", "2020", "L"))
    left["Year"] = 2020.0
    s = _reconcile(left, _mp3tag(("A-T1", "T", " 2020 ", "L")))
    assert s.passed


def test_unparseable_int_still_differs():
    s = _reconcile(
        _itunes(("A-T1", "T", "20x0", "L")), _mp3tag(("A-T1", "T", "2020", "L"))
    )
    assert [(m.field, m.left, m.right) for m in s.mismatches] == [
        ("year", "20x0", 2020)
    ]


def test_both_blank_is_not_a_mismatch():
    s = _reconcile(
        _itunes(("A-T1", "T", "2020", None)), _mp3tag(("A-T1", "T", "2020", ""))
    )
    assert s.passed


def test_duplicate_keys_reported_and_first_row_compared():
    s = _reconcile(
        _itunes(("A-T1", "T", "2020", "L"), ("A-T1", "Other", "1999", "X")),
        _mp3tag(("A-T1", "T", "2020", "L")),
    )
    assert s.duplicate_left == [f"{DIR}A-T1.mp3"]
    assert s.mismatches == []
    assert s.issue_counts == {"duplicate_key": 1}


def test_blank_key_reported_as_missing_key():
    left = _itunes(("A-T1", "T", "2020", "L"), ("A-T2", "T", "2020", "L"))
    left.loc[1, "Location"] = None
    s = _reconcile(left, _mp3tag(("A-T1", "T", "2020", "L")))
    assert s.missing_key_left == [1]
    assert s.issue_counts == {"missing_key": 1}


def test_join_on_filename():
    left = _itunes(("A-T1", "T", "2020", "L"))
    right = _mp3tag(("A-T1", "T", "2020", "L"))
    right["MTG-Path"] = "D:\\Elsewhere\\A-T1.mp3"  # different folder
    assert _reconcile(left, right).matched == 0
    s = _reconcile(left, right, on="filename")
    assert s.matched == 1
    assert s.passed


def test_explicit_fields():
    s = _reconcile(
        _itunes(("A-T1", "T1", "2020", "L")),
        _mp3tag(("A-T1", "T2", "2020", "L")),
        fields=["year"],
    )
    assert s.fields_compared == ["year"]
    assert s.passed


@pytest.mark.parametrize(
    ("fields", "match"),
    [(["nope"], "Unknown canonical"), (["bpm"], "not carried by both")],
)
def test_bad_fields_raise(fields, match):
    with pytest.raises(ValueError, match=match):
        row = ("A-T1", "T", "2020", "L")
        _reconcile(_itunes(row), _mp3tag(row), fields=fields)


def test_bad_on_raises():
    with pytest.raises(ValueError, match="on must be"):
        _reconcile(_itunes(), _mp3tag(), on="title")


def test_source_without_key_column_raises():
    right = _mp3tag(("A-T1", "T", "2020", "L")).drop(columns=["MTG-Path"])
    with pytest.raises(ValueError, match="no usable path column"):
        _reconcile(_itunes(("A-T1", "T", "2020", "L")), right)


def test_issue_codes_have_check_types():
    for code in ("unmatched", "duplicate_key", "missing_key", "cross_source_mismatch"):
        assert code in CHECK_TYPES


def test_reconcile_without_pandas(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas" or name.startswith("pandas."):
            raise ImportError("No module named 'pandas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"data-quality\[pandas\]"):
        reconcile_frames(object(), object())
