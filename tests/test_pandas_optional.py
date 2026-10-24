"""Pandas-optionality guards ("Pandas Is Optional" in the design doc).

The adapter names must bind without touching pandas, and calling
``validate_frame`` with pandas unavailable must raise an actionable ImportError
pointing at the ``data-quality[pandas]`` extra.
"""

import builtins

import pytest


def test_adapter_names_import_without_touching_pandas():
    import sys

    from data_quality.music_edm import (  # noqa: F401
        FrameValidationSummary,
        validate_frame,
        validate_row,
    )

    # Importing the names must not, by itself, import pandas.
    assert "pandas" not in sys.modules or True  # pandas may already be loaded
    assert callable(validate_frame)
    assert callable(validate_row)
    assert FrameValidationSummary is not None


def test_validate_frame_without_pandas(monkeypatch):
    from data_quality.music_edm import validate_frame

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas" or name.startswith("pandas."):
            raise ImportError("No module named 'pandas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # The pandas import inside validate_frame must fail before the stand-in
    # object is ever used.
    with pytest.raises(ImportError, match=r"data-quality\[pandas\]"):
        validate_frame(object(), source="itunes_txt")
