"""Shared pytest configuration for the entire test suite."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_config(monkeypatch):
    """Force `$BIBDESKPARSER_CONFIG` to an empty value for every test.

    An empty value disables the user-level (XDG) config-file location,
    so that a developer's personal `bibdeskparser.toml` cannot affect
    the test suite. Tests that exercise the environment variable or the
    XDG discovery step override or delete the variable themselves.
    """
    monkeypatch.setenv("BIBDESKPARSER_CONFIG", "")
