"""Tests for `bibdeskparser.macros`."""

import pytest

from bibdeskparser.macros import (
    _MACRO_NAME_CHARS,
    STANDARD_MACROS,
    is_valid_macro_name,
    normalize_macro_name,
)

#: The characters BibDesk removes from printable ASCII 32..125.
EXCLUDED_CHARS = sorted(" '\"@,\\#}{~%()=")

#: Punctuation characters that remain in the allowed set.
ACCEPTED_PUNCTUATION = sorted("-_.:+!?;$^&*[]|<>/")


def test_char_set_definition():
    """The allowed set is printable ASCII 32..125 minus the excluded
    characters."""
    expected = {chr(c) for c in range(32, 126) if chr(c) not in EXCLUDED_CHARS}
    assert _MACRO_NAME_CHARS == expected


@pytest.mark.parametrize("char", EXCLUDED_CHARS)
def test_excluded_char_rejected(char):
    """Each individually excluded character invalidates a name."""
    assert char not in _MACRO_NAME_CHARS
    assert not is_valid_macro_name("abc" + char)
    assert not is_valid_macro_name("abc" + char, normalized=False)


@pytest.mark.parametrize("char", ACCEPTED_PUNCTUATION)
def test_accepted_punctuation(char):
    """Punctuation in the allowed set is accepted anywhere in a name."""
    assert char in _MACRO_NAME_CHARS
    assert is_valid_macro_name("abc" + char)
    assert is_valid_macro_name("abc" + char + "def")


def test_non_ascii_rejected():
    """Non-ASCII characters are always invalid."""
    assert not is_valid_macro_name("jörg")
    assert not is_valid_macro_name("jörg", normalized=False)
    assert not is_valid_macro_name("naïve")
    assert not is_valid_macro_name("名前")


@pytest.mark.parametrize("char", ["\x00", "\t", "\n", "\r", "\x1f", "\x7f"])
def test_control_chars_rejected(char):
    """Control characters (below 32) and DEL are invalid."""
    assert not is_valid_macro_name("abc" + char)
    assert not is_valid_macro_name("abc" + char, normalized=False)


def test_leading_digit():
    """A name must not begin with a decimal digit, but digits are allowed
    elsewhere."""
    assert not is_valid_macro_name("2pac")
    assert not is_valid_macro_name("2pac", normalized=False)
    assert is_valid_macro_name("pra2")
    assert is_valid_macro_name("pra2", normalized=False)


def test_empty_string():
    """The empty string is only permitted as an in-progress edit."""
    assert not is_valid_macro_name("")
    assert is_valid_macro_name("", normalized=False)


def test_case():
    """A normalized name must be lowercase; unnormalized input may not
    be."""
    assert not is_valid_macro_name("PRL")
    assert is_valid_macro_name("PRL", normalized=False)
    assert is_valid_macro_name("prl")
    assert is_valid_macro_name("prl", normalized=False)


def test_normalize_macro_name():
    """Normalization lowercases valid names and is idempotent."""
    assert normalize_macro_name("PRL") == "prl"
    assert normalize_macro_name("prl") == "prl"
    assert normalize_macro_name(normalize_macro_name("PRL")) == "prl"


def test_normalize_macro_name_invalid():
    """Normalization rejects empty and invalid names."""
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_macro_name("")
    with pytest.raises(ValueError, match="invalid BibDesk macro name"):
        normalize_macro_name("bad name")
    with pytest.raises(ValueError, match="invalid BibDesk macro name"):
        normalize_macro_name("a{b")


def test_standard_macros():
    """The standard macros are exactly the twelve BibTeX month macros
    (as in BibDesk's `BDSKMacroResolver`), with valid normalized names
    and full English month names as values."""
    assert len(STANDARD_MACROS) == 12
    assert STANDARD_MACROS["jan"] == "January"
    assert STANDARD_MACROS["dec"] == "December"
    for name, value in STANDARD_MACROS.items():
        assert is_valid_macro_name(name)
        assert value.capitalize() == value
        assert value.lower().startswith(name)
