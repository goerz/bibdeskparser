"""Tests for `bibdeskparser.middleware`."""

import base64
import plistlib

import bibtexparser
import pytest

from bibdeskparser.bdskfile import BibDeskFile
from bibdeskparser.groups import render_static_groups
from bibdeskparser.middleware import (
    BibDeskFileMiddleware,
    DeTeXifyMiddleware,
    TeXifyMiddleware,
    parse_stack,
)

#: A minimal `bdsk-file-1` value ({base64 of a binary plist}).
BDSK_FILE_VALUE = (
    "{"
    + base64.b64encode(
        plistlib.dumps({"relativePath": "file.pdf"}, fmt=plistlib.FMT_BINARY)
    ).decode("ascii")
    + "}"
)

#: A `BibDesk Static Groups` comment body.
STATIC_GROUPS_COMMENT = render_static_groups({"My Group": ("key1",)})

SOURCE = "\n".join(
    [
        r"@string{jrnl = {Zeitschrift f{\"u}r Physik}}",
        "",
        "@article{key1,",
        "\t" + r"author = {Gr{\"u}n, Anna and D{\'\i}az, Jos{\'e}},",
        "\t" + r"title = {Some Title},",
        "\t" + r"url = {http://example.org/{\"u}},",
        "\tbdsk-file-1 = " + BDSK_FILE_VALUE + ",",
        "\t" + r"bdsk-url-1 = {http://example.org/gr{\"u}n}}",
        "",
        "@comment{a plain comment}",
        "",
        "@comment{" + STATIC_GROUPS_COMMENT + "}",
        "",
    ]
)


@pytest.fixture(name="bib")
def fixture_library():
    """`SOURCE` parsed through the full `parse_stack()`."""
    return bibtexparser.parse_string(SOURCE, parse_stack=parse_stack())


def test_parse_stack_returns_fresh_instances():
    """`parse_stack` returns new instances of the read middlewares."""
    stack1 = parse_stack()
    stack2 = parse_stack()
    assert [type(mw) for mw in stack1] == [
        DeTeXifyMiddleware,
        BibDeskFileMiddleware,
    ]
    for mw1, mw2 in zip(stack1, stack2):
        assert mw1 is not mw2


def test_detexify_entry_fields(bib):
    """TeX accents in entry fields are decoded to Unicode on read."""
    entry = bib.entries[0]
    assert entry["author"] == "{Grün, Anna and Díaz, José}"
    assert entry["title"] == "{Some Title}"


def test_detexify_string_value(bib):
    """TeX accents in `@string` values are decoded to Unicode."""
    string = bib.strings[0]
    assert string.key == "jrnl"
    assert string.value == "{Zeitschrift für Physik}"


def test_url_fields_untouched(bib):
    """URL fields keep their TeX markup verbatim on read."""
    entry = bib.entries[0]
    assert entry["url"] == r"{http://example.org/{\"u}}"
    assert entry["bdsk-url-1"] == r"{http://example.org/gr{\"u}n}"


def test_bdsk_file_field_decoded(bib):
    """`bdsk-file-N` values become `BibDeskFile` instances on read."""
    value = bib.entries[0].fields_dict["bdsk-file-1"].value
    assert isinstance(value, BibDeskFile)
    assert value.relative_path == "file.pdf"


def test_static_groups_comment_stays_str(bib):
    """The static-groups comment is *not* decoded by the middleware
    stack: it stays a verbatim string (`Library` parses it itself)."""
    groups_comments = [
        block.comment
        for block in bib.comments
        if block.comment == STATIC_GROUPS_COMMENT
    ]
    assert len(groups_comments) == 1
    assert isinstance(groups_comments[0], str)


def test_plain_comment_stays_str(bib):
    """An ordinary `@comment` block keeps its string value."""
    assert all(isinstance(block.comment, str) for block in bib.comments)
    assert "a plain comment" in [block.comment for block in bib.comments]


def test_texify_middleware(bib):
    """`TeXifyMiddleware` re-encodes Unicode as TeX for writing."""
    texified = TeXifyMiddleware(allow_inplace_modification=False).transform(
        bib
    )
    entry = texified.entries[0]
    assert entry["author"] == r"{Gr{\"u}n, Anna and D{\'\i}az, Jos{\'e}}"
    assert texified.strings[0].value == r"{Zeitschrift f{\"u}r Physik}"


def test_texify_skips_url_fields(bib):
    """`TeXifyMiddleware` leaves URL fields alone."""
    texified = TeXifyMiddleware(allow_inplace_modification=False).transform(
        bib
    )
    entry = texified.entries[0]
    assert entry["url"] == r"{http://example.org/{\"u}}"
    assert entry["bdsk-url-1"] == r"{http://example.org/gr{\"u}n}"


def test_texify_skips_non_str_values(bib):
    """`TeXifyMiddleware` passes `BibDeskFile` values through."""
    texified = TeXifyMiddleware(allow_inplace_modification=False).transform(
        bib
    )
    value = texified.entries[0].fields_dict["bdsk-file-1"].value
    assert isinstance(value, BibDeskFile)
    assert value.to_field_value() == BDSK_FILE_VALUE


def test_texify_no_inplace_modification(bib):
    """With `allow_inplace_modification=False`, the original library
    is unmodified."""
    TeXifyMiddleware(allow_inplace_modification=False).transform(bib)
    entry = bib.entries[0]
    assert entry["author"] == "{Grün, Anna and Díaz, José}"
    assert bib.strings[0].value == "{Zeitschrift für Physik}"


def test_detexify_skips_non_str_values(bib):
    """`DeTeXifyMiddleware` passes non-string values through (e.g.,
    when re-reading a library whose file fields are already decoded)."""
    transformed = DeTeXifyMiddleware(
        allow_inplace_modification=False
    ).transform(bib)
    value = transformed.entries[0].fields_dict["bdsk-file-1"].value
    assert isinstance(value, BibDeskFile)
