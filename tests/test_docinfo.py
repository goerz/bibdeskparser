"""Tests for BibDesk's document info (the `@bibdesk_info` block).

The block written by BibDesk (the key/value data of the "Document
Info" panel) must survive any operation and `Library.save`
byte-for-byte as long as `Library.info` is not modified, and must not
surface as an entry (its shape is that of an entry, but treating it as
one would date-stamp it and re-serialize it in entry layout, with the
closing brace fused onto the last field line instead of on its own
line). `Library.info` exposes the stored data as a read-write mapping;
a mutation regenerates the block in BibDesk's own layout.
"""

import warnings
from pathlib import Path

import pytest

from bibdeskparser import FormatConversionWarning, Library

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"

TOPICS = "Coherent Control, Numerics, OCT, Quantum Gates, Ultracold Atoms"

INFO_BLOCK = (
    "@bibdesk_info{document_info,\n" f"\tprimary_topics = {{{TOPICS}}}\n" "}"
)


@pytest.fixture(name="info_bib")
def fixture_info_bib(tmp_path):
    """A minimal database whose only BibDesk feature is a
    `@bibdesk_info` block (no header, no `@string` definitions)."""
    path = tmp_path / "info.bib"
    path.write_text(
        "@bibdesk_info{document_info,\n"
        "\tproject = {qdyn}\n"
        "}\n"
        "\n"
        "\n"
        "@article{K1,\n"
        "\tauthor = {Doe, John},\n"
        "\ttitle = {A Title},\n"
        "\tjournal = {Nature},\n"
        "\tyear = {2026}}\n",
        encoding="utf-8",
    )
    return path


# -- verbatim preservation ---------------------------------------------- #


def test_refs_bib_contains_document_info():
    """`refs.bib` holds a `@bibdesk_info` block (saved by BibDesk), so
    the tests here actually exercise document info. The block is not
    exposed as an entry."""
    assert INFO_BLOCK in REFS_BIB.read_text(encoding="utf-8")
    bib = Library(REFS_BIB)
    assert "document_info" not in bib.keys()


def test_pristine_save_preserves_document_info(tmp_path):
    """Saving an unmodified library keeps the `@bibdesk_info` block
    verbatim (the whole file is byte-exact, but assert the block
    explicitly, with its BibDesk layout and blank-line context)."""
    out = tmp_path / "out.bib"
    Library(REFS_BIB).save(out)
    text = out.read_text(encoding="utf-8")
    assert (
        "%% Saved with string encoding Unicode (UTF-8) \n\n"
        + INFO_BLOCK
        + "\n\n@string{atoms"
    ) in text


def test_document_info_survives_modification_roundtrip(tmp_path):
    """The `@bibdesk_info` block is still there, verbatim and in
    place, after a round trip in which an entry was modified (which
    rewrites the file)."""
    bib = Library(REFS_BIB)
    bib["GoerzJPB2011"]["note"] = "Some note."
    out = tmp_path / "out.bib"
    with pytest.warns(UserWarning, match="linked file does not exist"):
        bib.save(out)
    text = out.read_text(encoding="utf-8")
    assert (INFO_BLOCK + "\n\n@string{atoms") in text
    assert "note = {Some note.}" in text


def test_unusual_block_preserved_until_modified(tmp_path):
    """A hand-edited block (TeX-escaped values, entry-style layout) is
    written back verbatim as long as the info is not modified; the
    mapping still exposes the de-TeXified data. A mutation regenerates
    the block in BibDesk's layout, with plain-Unicode values."""
    block = '@bibdesk_info{document_info, topic = {Schr{\\"o}dinger}}'
    path = tmp_path / "info.bib"
    path.write_text(block + "\n", encoding="utf-8")
    bib = Library(path)
    assert dict(bib.info) == {"topic": "Schrödinger"}
    bib.save()  # pristine
    assert path.read_text(encoding="utf-8") == block + "\n"
    bib.info["project"] = "qdyn"
    bib.save()
    assert (
        "@bibdesk_info{document_info,\n"
        "\ttopic = {Schrödinger},\n"
        "\tproject = {qdyn}\n"
        "}"
    ) in path.read_text(encoding="utf-8")


def test_document_info_is_database_content(info_bib):
    """A file whose only BibDesk feature is a `@bibdesk_info` block is
    in the database format: entries get date stamps, and the block
    survives (one blank line below it, two above the first entry,
    where BibDesk puts it in a file without `@string` definitions)."""
    original = info_bib.read_text(encoding="utf-8")

    bib = Library(info_bib)
    assert "document_info" not in bib.keys()
    bib.save()  # pristine
    assert info_bib.read_text(encoding="utf-8") == original

    bib["K1"]["note"] = "Some note."  # database format: stamps dates
    bib.save()
    text = info_bib.read_text(encoding="utf-8")
    # The save synthesizes a BibDesk header; the info block sits one
    # blank line below it, in place, verbatim.
    assert "%% Saved with string encoding Unicode (UTF-8) \n\n" in text
    assert (
        "(UTF-8) \n\n"
        "@bibdesk_info{document_info,\n\tproject = {qdyn}\n}\n\n\n@article"
    ) in text
    assert "date-modified = " in text


# -- the Library.info mapping ------------------------------------------- #


def test_info_read():
    """`Library.info` exposes the stored key/value data; keys are
    matched case-insensitively but keep their stored spelling."""
    bib = Library(REFS_BIB)
    assert dict(bib.info) == {"primary_topics": TOPICS}
    assert list(bib.info) == ["primary_topics"]
    assert bib.info["primary_topics"] == TOPICS
    assert bib.info["Primary_Topics"] == TOPICS
    assert "PRIMARY_TOPICS" in bib.info
    assert "project" not in bib.info
    assert repr(bib.info) == repr({"primary_topics": TOPICS})
    with pytest.raises(KeyError):
        bib.info["project"]  # pylint: disable=pointless-statement
    with pytest.raises(KeyError):
        bib.info[42]  # pylint: disable=pointless-statement


def test_info_set_and_delete(tmp_path):
    """Assigning and deleting keys updates the block on save,
    preserving stored key order and appending new keys at the end."""
    path = tmp_path / "refs.bib"
    path.write_text(REFS_BIB.read_text(encoding="utf-8"), encoding="utf-8")
    bib = Library(path)
    bib.info["project"] = "qdyn"
    bib.save()
    assert (
        "@bibdesk_info{document_info,\n"
        f"\tprimary_topics = {{{TOPICS}}},\n"
        "\tproject = {qdyn}\n"
        "}"
    ) in path.read_text(encoding="utf-8")
    bib = Library(path)  # round-trips
    assert dict(bib.info) == {"primary_topics": TOPICS, "project": "qdyn"}
    del bib.info["project"]
    bib.save()
    text = path.read_text(encoding="utf-8")
    assert (INFO_BLOCK + "\n\n@string{atoms") in text


def test_info_update_preserves_stored_case(tmp_path):
    """Updating a key through a different spelling keeps the stored
    spelling (matching BibDesk's case-insensitive map)."""
    path = tmp_path / "info.bib"
    path.write_text(
        "@bibdesk_info{document_info,\n\tProject = {qdyn}\n}\n",
        encoding="utf-8",
    )
    bib = Library(path)
    bib.info["PROJECT"] = "krotov"
    assert dict(bib.info) == {"Project": "krotov"}
    bib.save()
    assert "\tProject = {krotov}\n}" in path.read_text(encoding="utf-8")


def test_info_unchanged_assignment_is_noop(tmp_path):
    """Re-assigning a key's current value does not mark the library
    modified (the file stays byte-identical, timestamp untouched)."""
    path = tmp_path / "refs.bib"
    original = REFS_BIB.read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    bib = Library(path)
    bib.info["Primary_Topics"] = TOPICS
    bib.save()
    assert path.read_text(encoding="utf-8") == original


def test_info_empty_value_allowed(tmp_path):
    """The empty string is a representable value (matching BibDesk,
    which stores one for a freshly added Document Info key)."""
    path = tmp_path / "new.bib"
    bib = Library()
    bib.info["project"] = ""
    bib.save(path)
    assert "@bibdesk_info{document_info,\n\tproject = {}\n}" in (
        path.read_text(encoding="utf-8")
    )
    assert dict(Library(path).info) == {"project": ""}


def test_deleting_last_key_removes_block(info_bib):
    """Deleting the last key removes the `@bibdesk_info` block from
    the file entirely (BibDesk writes no block for empty info)."""
    bib = Library(info_bib)
    del bib.info["project"]
    assert dict(bib.info) == {}
    bib.save()
    text = info_bib.read_text(encoding="utf-8")
    assert "bibdesk_info" not in text
    assert "@article{K1" in text


def test_info_block_created_between_header_and_strings(tmp_path):
    """Assigning the first key on a library without a `@bibdesk_info`
    block creates one, between the header and the `@string`
    definitions."""
    path = tmp_path / "refs.bib"
    text = REFS_BIB.read_text(encoding="utf-8").replace(
        INFO_BLOCK + "\n", "", 1
    )
    assert "bibdesk_info" not in text
    path.write_text(text, encoding="utf-8")
    bib = Library(path)
    bib.info["project"] = "qdyn"
    bib.save()
    assert (
        "(UTF-8) \n\n"
        "@bibdesk_info{document_info,\n\tproject = {qdyn}\n}"
        "\n\n@string{atoms"
    ) in path.read_text(encoding="utf-8")


def test_info_on_from_scratch_library(tmp_path):
    """A from-scratch library starts with empty info; assigned data is
    saved (below the synthesized header) and round-trips."""
    bib = Library(creator="Test User")
    assert dict(bib.info) == {}
    bib.info["project"] = "qdyn"
    bib.info["funding"] = "DFG"
    path = tmp_path / "new.bib"
    bib.save(path)
    assert (
        "@bibdesk_info{document_info,\n"
        "\tproject = {qdyn},\n"
        "\tfunding = {DFG}\n"
        "}"
    ) in path.read_text(encoding="utf-8")
    assert dict(Library(path).info) == {"project": "qdyn", "funding": "DFG"}


def test_info_mutation_does_not_touch_entries(tmp_path):
    """A document-info mutation rewrites the file (advancing the
    header timestamp) but touches no entry: everything from the first
    `@string` on is byte-identical (in particular, no `date-modified`
    stamping anywhere)."""
    bib = Library(REFS_BIB)
    bib.info["project"] = "qdyn"
    out = tmp_path / "out.bib"
    bib.save(out)
    original = REFS_BIB.read_text(encoding="utf-8")
    text = out.read_text(encoding="utf-8")
    marker = "@string{atoms"
    assert text[text.index(marker) :] == original[original.index(marker) :]


def test_invalid_info_key_rejected():
    """A key that is not a valid BibTeX field name is rejected (it
    would produce a file BibDesk cannot read back)."""
    bib = Library()
    for key in ("", "bad key", "2fast", "a{b}"):
        with pytest.raises(ValueError, match="invalid document-info key"):
            bib.info[key] = "value"
    with pytest.raises(TypeError, match="must be a str"):
        bib.info[42] = "value"
    assert dict(bib.info) == {}


def test_invalid_info_value_rejected(tmp_path):
    """Values must be plain strings with balanced braces (they are
    written brace-delimited); a value with balanced nested braces
    survives a save/reload round trip."""
    bib = Library()
    with pytest.raises(TypeError, match="must be a str"):
        bib.info["project"] = 42
    for value in ("{", "a}b", "}{"):
        with pytest.raises(ValueError, match="unbalanced braces"):
            bib.info["project"] = value
    bib.info["project"] = "a {braced} value"  # balanced braces are fine
    assert dict(bib.info) == {"project": "a {braced} value"}
    path = tmp_path / "new.bib"
    bib.save(path)
    assert dict(Library(path).info) == {"project": "a {braced} value"}


def test_info_assignment_converts_plain_format(tmp_path):
    """On a plain-format library, assigning a document-info key
    converts to the database format, with a warning."""
    path = tmp_path / "plain.bib"
    path.write_text(
        "@article{K1,\n"
        "\tauthor = {Doe, John},\n"
        "\ttitle = {A Title},\n"
        "\tjournal = {Nature},\n"
        "\tyear = {2026}}\n",
        encoding="utf-8",
    )
    bib = Library(path)
    with pytest.warns(FormatConversionWarning, match="document info"):
        bib.info["project"] = "qdyn"
    bib.save()
    text = path.read_text(encoding="utf-8")
    assert "@bibdesk_info{document_info,\n\tproject = {qdyn}\n}" in text
    assert "%% Created for " in text  # a header was synthesized


def test_multiple_info_blocks(tmp_path):
    """Several `@bibdesk_info` blocks load with a warning, the last
    one winning (as in BibDesk); a mutation collapses them into one."""
    path = tmp_path / "info.bib"
    path.write_text(
        "@bibdesk_info{document_info,\n\tproject = {old}\n}\n"
        "\n"
        "@bibdesk_info{document_info,\n\tproject = {new}\n}\n",
        encoding="utf-8",
    )
    with pytest.warns(UserWarning, match="2 @bibdesk_info blocks"):
        bib = Library(path)
    assert dict(bib.info) == {"project": "new"}
    bib.save()  # pristine: both blocks round-trip verbatim
    assert path.read_text(encoding="utf-8").count("@bibdesk_info") == 2
    bib.info["project"] = "qdyn"
    bib.save()
    text = path.read_text(encoding="utf-8")
    assert text.count("@bibdesk_info") == 1
    assert "\tproject = {qdyn}\n}" in text


def test_info_feeds_format_specifiers(info_bib):
    """The `%i{Key}` specifier reads the library's document info,
    case-insensitively."""
    bib = Library(info_bib)
    assert bib.eval_format_spec("K1", "%a1-%i{Project}%u0") == "Doe-qdyn"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # linked-file warnings
        bib.rekey("K1", format_spec="%i{project}:%a1%u0")
    assert "qdyn:Doe" in bib.keys()
