"""Tests for `bibdeskparser.names`."""

import pytest

from bibdeskparser.names import structured_names


def test_three_authors():
    """A comma-joined author string with three names splits correctly."""
    names = structured_names(
        "Goerz, Michael H and Calarco, Tommaso and Koch, Christiane P"
    )
    assert len(names) == 3
    goerz, calarco, koch = names
    assert goerz.last == ["Goerz"]
    assert goerz.first == ["Michael", "H"]
    assert calarco.last == ["Calarco"]
    assert calarco.first == ["Tommaso"]
    assert koch.last == ["Koch"]
    assert koch.first == ["Christiane", "P"]


def test_von_name():
    """A "von" name part is recognized."""
    (name,) = structured_names("Ludwig van Beethoven")
    assert name.first == ["Ludwig"]
    assert name.von == ["van"]
    assert name.last == ["Beethoven"]
    assert name.jr == []


def test_jr_name():
    """A generational suffix ("Jr.") is recognized."""
    (name,) = structured_names("Ford, Jr., Henry")
    assert name.first == ["Henry"]
    assert name.von == []
    assert name.last == ["Ford"]
    assert name.jr == ["Jr."]


def test_braced_value():
    """A value with enclosing braces is stripped before parsing."""
    names = structured_names("{Goerz, Michael H}")
    assert len(names) == 1
    assert names[0].last == ["Goerz"]
    assert names[0].first == ["Michael", "H"]


def test_empty_string():
    """An empty field value yields an empty list."""
    assert structured_names("") == []


def test_none_value():
    """A missing field value (`None`) yields an empty list."""
    assert structured_names(None) == []


def test_single_name():
    """A single "Last, First" name parses correctly."""
    (name,) = structured_names("Einstein, Albert")
    assert name.last == ["Einstein"]
    assert name.first == ["Albert"]


def test_unparseable_name():
    """An unparseable value raises a descriptive `ValueError`
    (`bibtexparser`'s `InvalidNameError`)."""
    with pytest.raises(ValueError, match="Too many commas"):
        structured_names("Doe, John, Jr, X, Y")
    with pytest.raises(ValueError, match="Unterminated opening brace"):
        structured_names("Bad {Name")
