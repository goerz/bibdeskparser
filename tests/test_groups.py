"""Tests for `bibdeskparser.groups`."""

from pathlib import Path

import pytest

from bibdeskparser.groups import (
    is_static_groups_comment,
    parse_static_groups,
    render_static_groups,
)

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"

GROUP_NAMES = [
    "My Papers",
    "OCT Software",
    "Preprints",
    "Superconducting Qubits",
]


@pytest.fixture
def refs_comment():
    """The `BibDesk Static Groups` comment body from `refs.bib`.

    This is the text between `@comment{` and the final `}` of the file,
    i.e. `BibDesk Static Groups{\\n<?xml ...</plist>\\n}`.
    """
    text = REFS_BIB.read_text(encoding="utf-8")
    start = text.rindex("BibDesk Static Groups{")
    end = text.rindex("}")  # the `}` closing the `@comment{`
    return text[start:end]


def test_parse_refs_comment(refs_comment):
    """Parsing the refs.bib comment gives the expected name -> keys
    mapping, in file order."""
    groups = parse_static_groups(refs_comment)
    assert isinstance(groups, dict)
    assert list(groups) == GROUP_NAMES
    assert all(isinstance(keys, tuple) for keys in groups.values())
    assert len(groups["My Papers"]) == 10
    assert "GoerzJPB2011" in groups["My Papers"]
    assert groups["Preprints"] == ("Aiello2605.00152",)
    assert groups["Superconducting Qubits"] == (
        "GoerzEPJQT2015",
        "GoerzNPJQI2017",
    )


def test_roundtrip_byte_exact(refs_comment):
    """Parsing the refs.bib comment and re-serializing is byte-exact."""
    groups = parse_static_groups(refs_comment)
    assert render_static_groups(groups) == refs_comment


def test_empty_group_roundtrip():
    """A group with no keys serializes as an empty `<string></string>`."""
    comment = render_static_groups({"Empty": ()})
    assert "<string>Empty</string>" in comment
    assert "<string></string>" in comment
    parsed = parse_static_groups(comment)
    assert parsed == {"Empty": ()}
    assert render_static_groups(parsed) == comment


def test_no_groups_roundtrip():
    """A mapping without any groups round-trips."""
    comment = render_static_groups({})
    assert is_static_groups_comment(comment)
    parsed = parse_static_groups(comment)
    assert parsed == {}
    assert render_static_groups(parsed) == comment


def test_key_order_preserved():
    """Both group order and the key order within each group survive a
    render/parse round trip."""
    groups = {
        "B Group": ("z", "a", "m"),
        "A Group": ("key2", "key1"),
    }
    parsed = parse_static_groups(render_static_groups(groups))
    assert list(parsed) == ["B Group", "A Group"]
    assert parsed["B Group"] == ("z", "a", "m")
    assert parsed["A Group"] == ("key2", "key1")


def test_is_static_groups_comment(refs_comment):
    """`is_static_groups_comment` detects static-groups comment bodies."""
    assert is_static_groups_comment(refs_comment)
    assert not is_static_groups_comment("some other comment")
    assert not is_static_groups_comment("")
    assert not is_static_groups_comment(42)
    assert not is_static_groups_comment(None)
