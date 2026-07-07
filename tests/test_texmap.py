"""Tests for `bibdeskparser.texmap`."""

import re
from pathlib import Path

from bibdeskparser import texmap
from bibdeskparser.texmap import detexify, skip_texify, texify

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"


def test_texify_table_roundtrip():
    """Every entry in the TEXIFY table converts forward; bidirectional
    entries also convert back."""
    for char, tex in texmap._TEXIFY.items():
        assert texify(char) == tex
        if texmap._DETEXIFY.get(tex) == char and "{\\" in tex:
            # bidirectional mapping
            assert detexify(tex) == char
        else:
            # one-way mapping (e.g. "–" -> "--", "ﬁ" -> "fi", and
            # "¡" -> "{!'}", which detexify cannot see since it only
            # scans for "{\\"): the TeX form must survive detexify
            assert detexify(tex) == tex


def test_detexify_table():
    """Every scannable entry in the DETEXIFY table converts back."""
    for tex, char in texmap._DETEXIFY.items():
        if "{\\" in tex:
            assert detexify(tex) == char


def test_detexify_accent_composition():
    """TeX accent tokens compose to single Unicode characters."""
    # direct table hits
    assert detexify('{\\"a}') == "ä"
    assert detexify(r"{\'e}") == "é"
    assert detexify(r"{\v c}") == "č"
    assert detexify(r"{\'\i}") == "í"  # dotless i
    # not in the direct table: composed via the accent algorithm
    assert detexify(r"{\'y}") == "ý"
    assert detexify(r"{\'n}") == "ń"
    assert detexify(r"{\u g}") == "ğ"
    assert detexify(r"{\v R}") == "Ř"
    assert detexify(r"{\~\i}") == "ĩ"  # dotless i, accent algorithm


def test_texify_accent_fallback():
    """Composed characters not in the TEXIFY table are converted via
    `_char_to_tex_accent`."""
    assert texify("ý") == r"{\'y}"
    assert texify("ń") == r"{\'n}"
    assert texify("ğ") == r"{\u g}"
    assert texify("Ř") == r"{\v R}"
    assert texify("ĩ") == r"{\~\i}"  # dotless i
    # and back through the accent algorithm
    for char in "ýńğŘĩ":
        assert detexify(texify(char)) == char


def test_idempotency():
    """Both conversions are idempotent."""
    strings = [
        "Universität Tübingen",
        'Universit{\\"a}t T{\\"u}bingen',
        "plain ASCII, nothing to convert",
        "20ℏk π/2 ~10¹⁶",
        "ǧ ý Ř — “quotes” … ﬁ",
    ]
    for s in strings:
        assert texify(texify(s)) == texify(s)
        assert detexify(detexify(s)) == detexify(s)


def test_mixed_string_roundtrip():
    """A mixed TeX/ASCII string converts and round-trips byte-exactly."""
    tex = 'Universit{\\"a}t T{\\"u}bingen'
    uni = "Universität Tübingen"
    assert detexify(tex) == uni
    assert texify(uni) == tex
    assert texify(detexify(tex)) == tex
    assert detexify(texify(uni)) == uni


def test_untexifiable_passthrough():
    """Characters BibDesk cannot express in TeX pass through unchanged."""
    s = "20ℏk π/2 ~10¹⁶"
    assert texify(s) == s
    assert detexify(s) == s
    s = "H₂O and π ≈ 3.14159…?"
    assert texify(s) == "H₂O and π ≈ 3.14159{\\ldots}?"


def test_detexify_noop():
    """Input without convertible sequences passes through unchanged."""
    s = "no tex here, just {braces} and \\commands"
    assert detexify(s) == s
    s = r"{\rm S}"  # contains "{\" but nothing convertible
    assert detexify(s) == s
    s = r"{$\sqrt{i{\rm{S}}WAP}$}"
    assert detexify(s) == s


def test_skip_texify():
    """URL and bdsk-file fields are excluded from conversion."""
    assert skip_texify("bdsk-file-1")
    assert skip_texify("url")
    assert skip_texify("bdsk-url-1")
    assert skip_texify("Bdsk-File-2")
    assert not skip_texify("author")
    assert not skip_texify("title")


def test_real_values_roundtrip():
    """Field values quoted from refs.bib survive detexify -> texify."""
    values = [
        'Freie Universit{\\"a}t Berlin',
        'Universit{\\"a}t Kassel',
        "Goerz, Michael H. and Carrasco, Sebasti{\\'a}n C. and "
        "Malinovsky, Vladimir S.",
        "a {$\\sqrt{i{\\rm{S}}WAP}$} gate with superconducting qubits",
    ]
    for tex in values:
        assert texify(detexify(tex)) == tex
    assert detexify(values[0]) == "Freie Universität Berlin"
    assert detexify(values[1]) == "Universität Kassel"
    assert "Sebastián" in detexify(values[2])


def test_refs_bib_roundtrip():
    """Every (single-line) field value in refs.bib survives
    detexify -> texify byte-exactly."""
    rx = re.compile(r"^\t([\w-]+) = \{(.*)\},$")
    text = REFS_BIB.read_text(encoding="utf-8")
    values = []
    for line in text.splitlines():
        match = rx.match(line)
        if match and not skip_texify(match.group(1)):
            values.append(match.group(2))
    assert len(values) > 100
    assert any("{\\" in value for value in values)
    for value in values:
        assert texify(detexify(value)) == value
