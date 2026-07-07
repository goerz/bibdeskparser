"""Tests for `bibdeskparser.writer`."""

from pathlib import Path

import bibtexparser
import pytest
from bibtexparser.model import (
    Entry,
    ExplicitComment,
    Field,
    ImplicitComment,
    Preamble,
    String,
)

from bibdeskparser.groups import render_static_groups
from bibdeskparser.middleware import parse_stack
from bibdeskparser.writer import (
    bibdesk_field_order,
    render_library,
    separator,
    serialize_block,
)

REFS = Path(__file__).parent / "Refs" / "refs.bib"

DUPLICATE_SOURCE = (
    "@article{key1,\n"
    "\ttitle = {First}}\n"
    "\n"
    "@article{key1,\n"
    "\ttitle = {Second}}\n"
)


@pytest.fixture(scope="module", name="refs_text")
def fixture_refs_text():
    """The verbatim text of `refs.bib`."""
    return REFS.read_text(encoding="utf-8")


@pytest.fixture(scope="module", name="refs_library")
def fixture_refs_library(refs_text):
    """`refs.bib` parsed through the full `parse_stack()`."""
    return bibtexparser.parse_string(refs_text, parse_stack=parse_stack())


@pytest.fixture(scope="module", name="duplicate_block")
def fixture_duplicate_block():
    """A `DuplicateBlockKeyBlock` wrapping an `Entry`."""
    bib = bibtexparser.parse_string(DUPLICATE_SOURCE, parse_stack=[])
    (block,) = bib.failed_blocks
    return block


def test_roundtrip_byte_exact(refs_text, refs_library):
    """THE BASELINE: rendering the parsed `refs.bib` reproduces the
    input byte-for-byte, and does not modify the library (rendering
    again gives the same result)."""
    assert render_library(refs_library) == refs_text
    assert render_library(refs_library) == refs_text


def test_serialize_entry():
    """An entry is one tab-indented line per field, with the closing
    brace fused onto the last field line."""
    entry = Entry(
        entry_type="article",
        key="key1",
        fields=[
            Field(key="author", value="{Goerz, Michael}"),
            Field(key="year", value="{2026}"),
        ],
    )
    assert serialize_block(entry) == (
        "@article{key1,\n" "\tauthor = {Goerz, Michael},\n" "\tyear = {2026}}"
    )


def test_serialize_string():
    """`@string` definitions are written on a single line."""
    string = String(key="jpb", value="{J. Phys. B}")
    assert serialize_block(string) == "@string{jpb = {J. Phys. B}}"


def test_serialize_explicit_comment():
    """A plain `@comment` block wraps its body verbatim."""
    comment = ExplicitComment("BibDesk metadata")
    assert serialize_block(comment) == "@comment{BibDesk metadata}"


def test_serialize_static_groups_comment():
    """A static-groups comment body (a plain string) is wrapped in
    `@comment{...}` verbatim, like any other explicit comment."""
    body = render_static_groups({"My Group": ("key1",)})
    comment = ExplicitComment(body)
    assert serialize_block(comment) == f"@comment{{{body}}}"


def test_serialize_implicit_comment():
    """An `ImplicitComment` passes through verbatim."""
    assert serialize_block(ImplicitComment("%% a note")) == "%% a note"


def test_serialize_header_comment(refs_library, refs_text):
    """The BibDesk header gets its rstripped trailing space back."""
    header_block = refs_library.blocks[0]
    assert isinstance(header_block, ImplicitComment)
    assert not header_block.comment.endswith(" ")
    header_lines = refs_text.split("\n")[:8]
    assert serialize_block(header_block) == "\n".join(header_lines)
    assert serialize_block(header_block).endswith("(UTF-8) ")


def test_serialize_failed_block(duplicate_block):
    """A failed (duplicate-key) block re-emits its raw source."""
    assert serialize_block(duplicate_block) == (
        "@article{key1,\n\ttitle = {Second}}"
    )


def test_serialize_unhandled_block():
    """Unhandled block types raise `TypeError`."""
    with pytest.raises(TypeError, match="Unhandled block type"):
        serialize_block(Preamble("preamble"))


def test_separator_matrix(duplicate_block):
    """Two blank lines before the `@string` section and before the
    entries section; one blank line everywhere else."""
    comment = ImplicitComment("%% header")
    string = String(key="jpb", value="{J. Phys. B}")
    entry = Entry(entry_type="article", key="key1", fields=[])
    explicit = ExplicitComment("meta")
    # The four section transitions in a BibDesk file:
    assert separator(comment, string) == "\n\n\n"
    assert separator(string, entry) == "\n\n\n"
    assert separator(string, string) == "\n\n"
    assert separator(entry, explicit) == "\n\n"
    # Other transitions get a single blank line:
    assert separator(entry, entry) == "\n\n"
    assert separator(comment, entry) == "\n\n"
    assert separator(entry, string) == "\n\n"
    assert separator(explicit, explicit) == "\n\n"
    # A failed block wrapping an entry counts as an entry:
    assert separator(string, duplicate_block) == "\n\n\n"
    assert separator(entry, duplicate_block) == "\n\n"
    assert separator(duplicate_block, explicit) == "\n\n"


def test_duplicate_key_roundtrip():
    """A library with duplicate entry keys renders back verbatim,
    including the duplicate."""
    bib = bibtexparser.parse_string(
        DUPLICATE_SOURCE, parse_stack=parse_stack()
    )
    assert len(bib.entries) == 1
    assert len(bib.failed_blocks) == 1
    assert render_library(bib) == DUPLICATE_SOURCE


def test_bibdesk_field_order_refs(refs_library):
    """The fields of `GoerzJPB2011` are already in BibDesk order."""
    entry = refs_library.entries_dict["GoerzJPB2011"]
    keys = [field.key for field in entry.fields]
    assert keys == [
        "abstract",
        "archiveprefix",
        "author",
        "date-added",
        "date-modified",
        "doi",
        "eprint",
        "journal",
        "keywords",
        "number",
        "pages",
        "title",
        "volume",
        "year",
        "bdsk-file-1",
        "bdsk-url-1",
    ]
    ordered = bibdesk_field_order(entry.fields)
    assert [field.key for field in ordered] == keys


def test_bibdesk_field_order_shuffled():
    """`bdsk-*` fields sort after all others; both groups
    alphabetical."""
    fields = [
        Field(key=key, value="{x}")
        for key in ["bdsk-url-1", "bdsk-file-2", "year", "author"]
    ]
    ordered = bibdesk_field_order(fields)
    assert [field.key for field in ordered] == [
        "author",
        "year",
        "bdsk-file-2",
        "bdsk-url-1",
    ]


def test_bibdesk_field_order_case_insensitive():
    """Sorting compares keys case-insensitively."""
    fields = [
        Field(key=key, value="{x}") for key in ["Year", "author", "Title"]
    ]
    ordered = bibdesk_field_order(fields)
    assert [field.key for field in ordered] == ["author", "Title", "Year"]


def test_bibdesk_field_order_numbers_lexical():
    """Numbered `bdsk-*` fields sort lexically: `bdsk-file-10` comes
    before `bdsk-file-2`."""
    fields = [
        Field(key=key, value="{x}")
        for key in ["bdsk-file-2", "bdsk-file-10", "bdsk-file-1"]
    ]
    ordered = bibdesk_field_order(fields)
    assert [field.key for field in ordered] == [
        "bdsk-file-1",
        "bdsk-file-10",
        "bdsk-file-2",
    ]
