"""Tests for `bibdeskparser` package."""

from packaging.version import parse as parse_version

import bibdeskparser


def test_valid_version():
    """Check that the package defines a valid ``__version__``."""
    v_curr = parse_version(bibdeskparser.__version__)
    v_orig = parse_version("0.1.0-dev")
    assert v_curr >= v_orig


def test_hello_world():
    """Check the example ``hello_world`` function."""
    assert bibdeskparser.hello_world("Alice") == "Hello, Alice!"
