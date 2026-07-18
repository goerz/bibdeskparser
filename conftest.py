"""Shared pytest configuration for the entire test suite."""

import shutil
from pathlib import Path

import pytest

REFS_DIR = Path(__file__).parent / "tests" / "Refs"


@pytest.fixture(autouse=True)
def _isolate_user_config(monkeypatch):
    """Force `$BIBDESKPARSER_CONFIG` to an empty value for every test.

    An empty value disables the user-level (XDG) config-file location,
    so that a developer's personal `bibdeskparser.toml` cannot affect
    the test suite. Tests that exercise the environment variable or the
    XDG discovery step override or delete the variable themselves.
    """
    monkeypatch.setenv("BIBDESKPARSER_CONFIG", "")


@pytest.fixture(autouse=True)
def _doctest_refs_sandbox(request, tmp_path, monkeypatch):
    """Run every doctest from a sandbox copy of the example database.

    Doctests (in docstrings, in the documentation's Markdown files,
    and in `README.md`) use the example database via the relative path
    `tests/Refs/refs.bib`. This fixture makes that path work regardless
    of the directory pytest is invoked from, and makes it safe for a
    doctest to *write* to the database: the doctest runs with its
    working directory changed to a temporary directory holding a fresh
    copy of `tests/Refs`, so the repository files are never touched.

    Regular test functions are unaffected; they access the fixture at
    its true location via `Path(__file__)`-anchored paths.
    """
    if isinstance(request.node, pytest.DoctestItem):
        shutil.copytree(REFS_DIR, tmp_path / "tests" / "Refs")
        monkeypatch.chdir(tmp_path)
