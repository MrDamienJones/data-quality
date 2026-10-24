"""Smoke test for an installed data-quality wheel, without pandas.

CI builds the wheel, installs it into a clean virtual environment with no
extras, and runs this script there in isolated mode, so it imports the
installed package and not the source tree::

    python -I scripts/smoke_test.py

It proves that the wheel holds a working package, that the base install needs
no pandas, and that the pandas-only functions fail with the install hint.
"""

import importlib.util

import data_quality
from data_quality.music_edm import (
    generate_filename,
    list_checks,
    reconcile_frames,
    validate_frame,
    validate_metadata,
)


def main() -> None:
    assert importlib.util.find_spec("pandas") is None, "pandas must not be installed"
    assert "site-packages" in data_quality.__file__, data_quality.__file__

    artist, title = "Artist", "Some Track (Extended Mix)"
    fields = {
        "bpm": "128",
        "track_number": 128,
        "title": title,
        "artist": artist,
        "album": "08B-CM",
        "initialkey": "C",
        "encodedby": "me",
        "album_artist": artist,
        "album_artist_sort": artist,
        "subtitle": f"{artist} - {title} 08B-CM 128 2020",
        "publisher": "Label",
        "grouping": "Label",
        "year": "2020",
        "discogs_id": 12345,
    }
    result = validate_metadata(fields, generate_filename(artist, title))
    assert result.passed, [str(issue) for issue in result.issues]

    for function, args in (
        (validate_frame, (object(),)),
        (reconcile_frames, (object(), object())),
    ):
        try:
            function(*args)
        except ImportError as error:
            assert "data-quality[pandas]" in str(error), error
        else:
            raise AssertionError(f"{function.__name__} ran without pandas")

    version, checks = data_quality.__version__, len(list_checks())
    print(f"smoke test passed: data-quality {version}, {checks} checks")


if __name__ == "__main__":
    main()
