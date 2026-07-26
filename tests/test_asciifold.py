"""Tests for `bibdeskparser.asciifold` (rendering Latin text as
ASCII)."""

import pytest

from bibdeskparser.asciifold import fold_to_ascii
from bibdeskparser.specifiers import _COMPOSED_MAP


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # accented letters (base letter plus a combining mark)
        ("Müller", "Muller"),
        ("Ağanoğlu", "Aganoglu"),
        ("Řezáč", "Rezac"),
        ("Kołodyński", "Kolodynski"),
        # letters carrying their modification in the glyph, which no
        # decomposition splits
        ("Kılıç", "Kilic"),
        ("Işık", "Isik"),
        ("Masłowski", "Maslowski"),
        ("Mølmer", "Molmer"),
        ("Đurić", "Duric"),
        ("Ħabib", "Habib"),
        ("Guðmundsdóttir", "Gudmundsdottir"),
        ("Coŀlell", "Collell"),
        ("Aĸigssiaĸ", "Akigssiak"),
        # letters whose Unicode name carries no base letter
        ("Sáraŋ", "Sarang"),
        ("Əliyev", "Eliyev"),
        # ligatures and digraphs
        ("Weiß", "Weiss"),
        ("Æbelholt", "AEbelholt"),
        ("Œuvre", "OEuvre"),
        ("Þórsson", "THorsson"),
        ("ǆungla", "dzungla"),
        ("Ǉubav", "LJubav"),
        ("ĳsvogel", "ijsvogel"),
        ("eﬃcient", "efficient"),
    ],
)
def test_fold_to_ascii(text, expected):
    assert fold_to_ascii(text) == expected


def test_ascii_text_is_returned_unchanged():
    text = "Goerz, Michael H."
    assert fold_to_ascii(text) is text


def test_unrenderable_characters_are_kept():
    """A character with no ASCII rendering survives, so a value in a
    non-Latin script still matches itself after folding."""
    assert fold_to_ascii("Иванов") == "Иванов"
    assert fold_to_ascii("Ωmega") == "Ωmega"
    assert fold_to_ascii("Mølmer 東京") == "Molmer 東京"


def test_case_is_preserved():
    assert fold_to_ascii("ŁÓDŹ łódź") == "LODZ lodz"


def test_covers_bibdesks_own_table():
    """Every letter BibDesk spells out by hand folds here too.

    The key path applies `_COMPOSED_MAP` before this fold, so a letter
    missing here still keys correctly and the gap would surface only
    on the search and preprint-matching paths, which do not consult
    that table."""
    unfolded = [
        char
        for char in map(chr, _COMPOSED_MAP)
        if not fold_to_ascii(char).isascii()
    ]
    assert unfolded == []
