"""Tests for the ported music data quality checks.

A known-good field set passes every check; individual mutations prove each
check fires with the expected issue code.
"""

import pytest

from data_quality.music_edm import (
    AudioMetadata,
    generate_filename,
    validate_metadata,
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
    result = validate_metadata(
        valid_fields(), filename_stem=VALID_FILENAME_STEM, file_size_bytes=5_000_000
    )
    assert result.passed, [str(i) for i in result.issues]
    assert result.issues == []
    assert bool(result) is True


def codes(result) -> set:
    return {issue.code for issue in result.issues}


def test_missing_required_fields():
    fields = valid_fields()
    fields["title"] = None
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert not result.passed
    assert "missing_fields" in codes(result)


def test_bpm_out_of_range():
    fields = valid_fields()
    fields["bpm"] = 50
    fields["track_number"] = 50
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "value_out_of_range" in codes(result)


def test_year_out_of_range():
    fields = valid_fields()
    fields["year"] = 1900
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "value_out_of_range" in codes(result)


def test_bpm_track_mismatch():
    fields = valid_fields()
    fields["track_number"] = 130
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "bpm_track_mismatch" in codes(result)


def test_invalid_camelot_album():
    fields = valid_fields()
    fields["album"] = "ZZ9-Plural"
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "invalid_camelot" in codes(result)


def test_corrupted_initialkey():
    fields = valid_fields()
    fields["initialkey"] = "C/\x00"
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "corrupted_field" in codes(result)


def test_key_album_mismatch():
    fields = valid_fields()
    fields["initialkey"] = "Am"  # valid notation but wrong for 08B-CM (expects C)
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "key_album_mismatch" in codes(result)


def test_subtitle_drift():
    fields = valid_fields()
    fields["subtitle"] = "wrong subtitle"
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "subtitle_drift" in codes(result)


def test_filename_drift():
    fields = valid_fields()
    result = validate_metadata(fields, "WrongName", 5_000_000)
    assert "filename_drift" in codes(result)


def test_artist_field_mismatch():
    fields = valid_fields()
    fields["album_artist"] = "Someone Else"
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
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
    result = validate_metadata(fields, stem, 5_000_000)
    assert "title_format" in codes(result)


def test_publisher_grouping_mismatch():
    fields = valid_fields()
    fields["grouping"] = "Different"
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "publisher_grouping" in codes(result)


def test_publisher_bracketed_numbers():
    fields = valid_fields()
    fields["publisher"] = "Label (123)"
    fields["grouping"] = "Label (123)"
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "publisher_grouping" in codes(result)


def test_discogs_missing():
    fields = valid_fields()
    fields["discogs_id"] = 0
    result = validate_metadata(fields, VALID_FILENAME_STEM, 5_000_000)
    assert "discogs_missing" in codes(result)


def test_file_too_small():
    fields = valid_fields()
    result = validate_metadata(fields, VALID_FILENAME_STEM, file_size_bytes=10)
    assert "file_size" in codes(result)


def test_file_size_unknown():
    fields = valid_fields()
    result = validate_metadata(fields, VALID_FILENAME_STEM, file_size_bytes=None)
    assert "file_size" in codes(result)


def test_missing_keys_treated_as_none():
    # A sparse dict must not raise; missing keys become None.
    result = validate_metadata({}, filename_stem="whatever", file_size_bytes=None)
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
        ],
    )
    def test_all_dash_lookalikes_normalized(self, dash):
        assert generate_filename("Artist", f"Tri{dash}State") == "Artist-TriState"


class TestAudioMetadataModel:
    def test_valid_model_constructs(self):
        model = AudioMetadata(
            bpm=VALID_BPM,
            track_number=VALID_BPM,
            discogs_id=12345,
            year=VALID_YEAR,
            title=VALID_TITLE,
            album=VALID_ALBUM,
            initialkey="C",
            encodedby="me",
            artist=VALID_ARTIST,
            album_artist=VALID_ARTIST,
            album_artist_sort=VALID_ARTIST,
            subtitle=VALID_SUBTITLE,
            filename=VALID_FILENAME_STEM,
        )
        assert model.album == VALID_ALBUM

    def test_invalid_camelot_album_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AudioMetadata(
                bpm=VALID_BPM,
                track_number=VALID_BPM,
                discogs_id=12345,
                year=VALID_YEAR,
                title=VALID_TITLE,
                album="not-a-key",
                initialkey="C",
                encodedby="me",
                artist=VALID_ARTIST,
                album_artist=VALID_ARTIST,
                album_artist_sort=VALID_ARTIST,
                subtitle=VALID_SUBTITLE,
                filename=VALID_FILENAME_STEM,
            )
