"""Pydantic v2 models for music metadata validation.

Ported from the music pipeline. ``AudioMetadata`` carries the field-level and
cross-field validators; the config models describe how a consumer maps raw tag
names to canonical fields per audio format.
"""

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .constants import (
    BPM_MAX,
    BPM_MIN,
    CAMELOT_KEYS,
    CAMELOT_NOTATIONS,
    CHARACTER_REPLACEMENTS,
    INITIALKEY_NOTATIONS,
    YEAR_MIN,
)


class AudioFormatEnum(str, Enum):  # noqa: UP042 (keep str+Enum to match source behavior)
    """Supported audio formats."""

    MP3 = "mp3"
    FLAC = "flac"
    WAV = "wav"


def generate_filename(artist: str, title: str) -> str:
    """Generate a filename from artist and title following the pipeline rules."""

    def process_field(field: str) -> str:
        for old_char, new_char in CHARACTER_REPLACEMENTS.items():
            field = field.replace(old_char, new_char)
        # Remove hyphens from within the field
        field = field.replace("-", "")
        return field

    artist = process_field(artist)
    title = process_field(title)

    filename = f"{artist} - {title}"

    # Handle brackets: replace last ( with -, remove all other ( and )
    if "(" in filename:
        last_paren = filename.rfind("(")
        if last_paren != -1:
            filename = filename[:last_paren] + "-" + filename[last_paren + 1 :]
        filename = filename.replace("(", "").replace(")", "")

    filename = filename.replace(" ", "")

    dash_count = filename.count("-")
    if dash_count > 2:
        raise ValueError(f"Filename has {dash_count} dashes, maximum allowed is 2")

    return filename


class AudioMetadata(BaseModel):
    """Validated audio metadata."""

    bpm: int | None = Field(default=None, ge=BPM_MIN, le=BPM_MAX)
    track_number: int | None = Field(default=None, ge=BPM_MIN, le=BPM_MAX)
    publisher: str | None = None
    grouping: str | None = None
    discogs_id: int = Field(ge=0)
    year: int = Field(ge=YEAR_MIN, le=datetime.now().year)
    title: str = Field(min_length=1)
    album: str = Field(min_length=1)
    initialkey: str = Field(min_length=1)
    encodedby: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    album_artist: str = Field(min_length=1)
    album_artist_sort: str = Field(min_length=1)
    subtitle: str = Field(min_length=1)
    filename: str = Field(min_length=1)

    @field_validator("track_number")
    @classmethod
    def validate_bpm_track_match(cls, v, info):
        """Validate BPM and track number match when both are present."""
        if "bpm" in info.data and info.data["bpm"] and v and info.data["bpm"] != v:
            raise ValueError("BPM and track number must match")
        return v

    @field_validator("title")
    @classmethod
    def validate_title_format(cls, v: str) -> str:
        """Validate title contains at least one ( and )."""
        if "(" not in v or ")" not in v:
            raise ValueError("Title must contain at least one ( and )")
        return v

    @field_validator("album")
    @classmethod
    def validate_album_camelot(cls, v: str) -> str:
        """Validate album is valid Camelot notation."""
        if v not in CAMELOT_NOTATIONS:
            raise ValueError("Album must be valid Camelot notation")
        return v

    @field_validator("initialkey")
    @classmethod
    def validate_initialkey_matches_album(cls, v: str, info) -> str:
        """Validate initialkey is valid notation and matches album."""
        if v not in INITIALKEY_NOTATIONS:
            raise ValueError("Initial key must be valid notation")
        if "album" in info.data and info.data["album"]:
            expected_key = CAMELOT_KEYS.get(info.data["album"])
            if expected_key and v != expected_key:
                raise ValueError(
                    f"Initial key must be {expected_key} for album {info.data['album']}"
                )
        return v

    @field_validator("subtitle")
    @classmethod
    def validate_subtitle_format(cls, v: str, info) -> str:
        """Validate subtitle matches 'Artist - Title Album BPM Year' format."""
        if not all(
            field in info.data for field in ["artist", "title", "album", "bpm", "year"]
        ):
            return v  # Skip validation if required fields missing

        expected = (
            f"{info.data['artist']} - {info.data['title']} "
            f"{info.data['album']} {info.data['bpm']} {info.data['year']}"
        )
        if v != expected:
            raise ValueError(f"Subtitle must be: {expected}")
        return v

    @field_validator("filename")
    @classmethod
    def validate_filename_format(cls, v: str, info) -> str:
        """Validate filename matches the generated Artist - Title form."""
        if not all(field in info.data for field in ["artist", "title"]):
            return v  # Skip validation if required fields missing

        try:
            expected = generate_filename(info.data["artist"], info.data["title"])
            if v != expected:
                raise ValueError(f"Filename must be: {expected}")
        except ValueError as e:
            raise ValueError(str(e)) from e
        return v

    @field_validator("album_artist", "album_artist_sort")
    @classmethod
    def validate_artist_fields_match(cls, v: str, info) -> str:
        """Validate album_artist and album_artist_sort match artist."""
        if "artist" in info.data and info.data["artist"]:
            if v != info.data["artist"]:
                raise ValueError(
                    f"Album artist fields must match artist: {info.data['artist']}"
                )
        return v


class MetadataMapping(BaseModel):
    """Metadata field mapping for an audio format.

    Maps canonical field names to the raw tag keys used by a given format.
    """

    bpm: str
    key: str
    discogs_id: str | None = None
    title: str | None = None
    artist: str | None = None
    album_artist: str | None = None
    album_artist_sort: str | None = None
    subtitle: str | None = None
    publisher: str | None = None
    grouping: str | None = None
    track_number: str | None = None
    encoded_by: str | None = None
    year: str | None = None
    album: str | None = None
    initialkey: str | None = None
    encodedby: str | None = None


class PathConfig(BaseModel):
    """Pipeline stage paths (consumer-specific, optional to use)."""

    stage1_input: Path
    stage2_input: Path
    stage3_input: Path | None = None
    stage4_input: Path | None = None


class ValidationConfig(BaseModel):
    """Validation rules."""

    bpm_range: list[int] = Field(default=[BPM_MIN, BPM_MAX], min_length=2, max_length=2)

    @field_validator("bpm_range")
    @classmethod
    def validate_bpm_range(cls, v):
        """Validate BPM range has min < max."""
        if v[0] >= v[1]:
            raise ValueError("BPM range minimum must be less than maximum")
        return v


class Config(BaseModel):
    """Main configuration model."""

    paths: PathConfig
    supported_extensions: list[str] = Field(min_length=1)
    metadata_fields: dict[AudioFormatEnum, MetadataMapping]
    validation: ValidationConfig | None = ValidationConfig()

    @field_validator("supported_extensions")
    @classmethod
    def validate_extensions(cls, v):
        """Validate extensions start with a dot."""
        for ext in v:
            if not ext.startswith("."):
                raise ValueError(f"Extension must start with dot: {ext}")
        return v
