"""The garmin and pdf subpackages are placeholders.

These tests just assert they import cleanly and expose an (empty) ``__all__``,
so the package structure stays importable as domains are added later.
"""

import importlib

import pytest


@pytest.mark.parametrize("name", ["data_quality.garmin", "data_quality.pdf"])
def test_placeholder_imports(name):
    module = importlib.import_module(name)
    assert hasattr(module, "__all__")
    assert module.__all__ == []
