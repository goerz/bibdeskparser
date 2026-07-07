"""Set up the environment for doctests

This file is automatically evaluated by py.test. It ensures that we can write
doctests without distracting import statements in the doctest.
"""

import pytest

import bibdeskparser


@pytest.fixture(autouse=True)
def set_doctest_env(doctest_namespace):
    """Inject the package itself into the doctest namespace."""
    doctest_namespace["bibdeskparser"] = bibdeskparser
