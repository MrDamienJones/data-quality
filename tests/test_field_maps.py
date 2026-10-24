"""Tests for the ready-made source field maps and the resolver (no pandas)."""

import pytest

from data_quality.music_edm import SourceMap, itunes_txt, mp3tag_csv
from data_quality.music_edm.field_maps import resolve_source_map


def test_mp3tag_csv_structure():
    assert mp3tag_csv.name == "mp3tag_csv"
    assert mp3tag_csv.columns["MTG-BPM"] == "bpm"
    assert mp3tag_csv.columns["MTG-Title"] == "title"
    assert mp3tag_csv.filename_from == "MTG-Filename"
    assert mp3tag_csv.filename_strip_suffix == ".mp3"
    assert mp3tag_csv.filename_basename is False
    assert mp3tag_csv.path_from == "MTG-Path"
    # Carries no album_artist_sort column and no discogs column.
    assert "album_artist_sort" not in mp3tag_csv.columns.values()
    assert "discogs_id" not in mp3tag_csv.columns.values()


def test_itunes_txt_structure():
    assert itunes_txt.name == "itunes_txt"
    assert itunes_txt.columns["Name"] == "title"
    assert itunes_txt.columns["Track Number"] == "track_number"
    assert itunes_txt.filename_from == "Location"
    assert itunes_txt.filename_basename is True
    assert itunes_txt.path_from == "Location"
    # iTunes shows the content-group tag as "Work", not "Grouping".
    assert itunes_txt.columns["Work"] == "grouping"
    assert "Grouping" not in itunes_txt.columns


def test_resolve_identity_sets_path_from_when_present():
    assert resolve_source_map(columns=["title", "path"]).path_from == "path"
    assert resolve_source_map(columns=["title"]).path_from is None


def test_resolve_source_only_returns_map_as_is():
    assert resolve_source_map(source="mp3tag_csv") is mp3tag_csv


def test_resolve_unknown_source_raises():
    with pytest.raises(ValueError, match="itunes_txt"):
        resolve_source_map(source="nope")


def test_resolve_identity_without_structural_columns():
    resolved = resolve_source_map(columns=["title", "artist"])
    assert resolved.name == "identity"
    assert resolved.columns["title"] == "title"
    assert resolved.filename_from is None
    assert resolved.path_from is None


def test_resolve_identity_sets_structural_columns_when_present():
    resolved = resolve_source_map(columns=["title", "filename_stem", "path"])
    assert resolved.filename_from == "filename_stem"
    assert resolved.path_from == "path"


def test_resolve_plain_dict_field_map_only():
    resolved = resolve_source_map(field_map={"Col-A": "title"})
    assert resolved.name == "custom"
    assert resolved.columns == {"Col-A": "title"}
    assert resolved.filename_from is None


def test_resolve_sourcemap_field_map_replaces_base():
    custom = SourceMap(name="power", columns={"X": "bpm"}, path_from="P")
    assert resolve_source_map(source="mp3tag_csv", field_map=custom) is custom


def test_resolve_source_plus_dict_merges_columns_and_inherits_structure():
    resolved = resolve_source_map(source="mp3tag_csv", field_map={"My-Title": "title"})
    # Override added, base columns retained, structural fields inherited.
    assert resolved.columns["My-Title"] == "title"
    assert resolved.columns["MTG-BPM"] == "bpm"
    assert resolved.filename_from == "MTG-Filename"
    assert resolved.path_from == "MTG-Path"
    # Base map is unchanged (frozen; merge returns a new instance).
    assert "My-Title" not in mp3tag_csv.columns
