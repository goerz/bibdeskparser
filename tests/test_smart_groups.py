"""Tests that `BibDesk Smart Groups` comments are preserved verbatim.

`bibdeskparser` does not interpret smart groups (saved searches); the
`@comment{BibDesk Smart Groups{...}}` block written by BibDesk must
survive any operation and `Library.save` byte-for-byte. On save, the
block must also stay where BibDesk would put it: after all entries,
and after the static-groups block.
"""

from pathlib import Path

import pytest

from bibdeskparser import Entry, Library

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"

SMART_GROUPS_HEAD = "@comment{BibDesk Smart Groups{"
STATIC_GROUPS_HEAD = "@comment{BibDesk Static Groups{"


def _smart_groups_block(text):
    """The verbatim `@comment{BibDesk Smart Groups{...}}` block in
    `text` (which must contain exactly one)."""
    assert text.count(SMART_GROUPS_HEAD) == 1
    start = text.index(SMART_GROUPS_HEAD)
    end = text.index("</plist>\n}}", start) + len("</plist>\n}}")
    return text[start:end]


@pytest.fixture(scope="module", name="refs_smart_block")
def fixture_refs_smart_block():
    """The verbatim smart-groups `@comment` block from `refs.bib`."""
    return _smart_groups_block(REFS_BIB.read_text(encoding="utf-8"))


def test_refs_bib_contains_smart_group(refs_smart_block):
    """`refs.bib` holds smart groups "Missing DOI" and "Preprints"
    (saved by BibDesk), so the tests here actually exercise smart
    groups."""
    assert "<string>Missing DOI</string>" in refs_smart_block
    assert "<string>Preprints</string>" in refs_smart_block
    # ... which are saved searches, not static groups:
    bib = Library(REFS_BIB)
    assert "Missing DOI" not in bib.groups
    assert "Preprints" not in bib.groups


def test_pristine_save_preserves_smart_groups(tmp_path, refs_smart_block):
    """Saving an unmodified library keeps the smart-groups block
    verbatim (the whole file is byte-exact, but assert the block
    explicitly)."""
    out = tmp_path / "out.bib"
    Library(REFS_BIB).save(out)
    text = out.read_text(encoding="utf-8")
    assert _smart_groups_block(text) == refs_smart_block


def test_smart_group_survives_modification_roundtrip(
    tmp_path, refs_smart_block
):
    """The "Missing DOI" smart group exists in `refs.bib` and is
    still there, verbatim, after a round trip in which entries were
    modified, added, deleted, and renamed (plus static-group
    mutations)."""
    assert "<string>Missing DOI</string>" in refs_smart_block

    bib = Library(REFS_BIB)
    bib["GoerzJPB2011"]["note"] = "Some note."
    bib["GoerzNJP2014"]["title"] = "A Changed Title"
    bib.groups["New Group"] = ("GoerzJPB2011",)
    bib.add_to_group("Diploma", "GoerzNJP2014")
    bib.rekey("GoerzQ2022", "GoerzQuantum2022")
    del bib["GoerzDiploma2010"]
    bib["New2026"] = Entry(
        "article",
        "New2026",
        fields={
            "author": "Doe, John",
            "title": "A New Paper",
            "journal": "Nature",
            "year": "2026",
        },
    )

    out = tmp_path / "out.bib"
    with pytest.warns(UserWarning, match="linked file does not exist"):
        bib.save(out)
    text = out.read_text(encoding="utf-8")
    assert _smart_groups_block(text) == refs_smart_block
    assert "<string>Missing DOI</string>" in _smart_groups_block(text)

    # ... and it is still intact after a reload/save cycle
    out2 = tmp_path / "out2.bib"
    with pytest.warns(UserWarning, match="linked file does not exist"):
        Library(out).save(out2)
    assert (
        _smart_groups_block(out2.read_text(encoding="utf-8"))
        == refs_smart_block
    )


def test_new_blocks_go_above_the_group_comments(tmp_path):
    """New entries and `@string` macros are written where BibDesk
    would put them, not after the group `@comment` blocks at the end
    of the file."""
    bib = Library(REFS_BIB)
    bib["New2026"] = Entry(
        "article",
        "New2026",
        fields={
            "author": "Doe, John",
            "title": "A New Paper",
            "journal": "nature",
            "year": "2026",
        },
    )
    bib.strings["nature"] = "Nature"

    out = tmp_path / "out.bib"
    with pytest.warns(UserWarning, match="linked file does not exist"):
        bib.save(out)
    text = out.read_text(encoding="utf-8")
    # entries above the group comments; static groups above smart groups
    assert (
        text.index("@article{New2026")
        < text.index(STATIC_GROUPS_HEAD)
        < text.index(SMART_GROUPS_HEAD)
    )
    # the new macro in the (sorted) `@string` run, above all entries
    strings = [
        line.split("{")[1].split(" ")[0]
        for line in text.splitlines()
        if line.startswith("@string{")
    ]
    assert strings == sorted(strings)
    assert "nature" in strings
    assert text.rindex("@string{") < text.index("@mastersthesis{")


def test_smart_groups_without_static_groups(tmp_path, refs_smart_block):
    """In a file with a smart-groups block but no static-groups block,
    the smart groups survive both a pristine save and the synthesis of
    a new static-groups block (which goes *above* the smart groups,
    where BibDesk writes it)."""
    path = tmp_path / "smart.bib"
    path.write_text(
        "@article{K1,\n"
        "\tauthor = {Doe, John},\n"
        "\ttitle = {A Title},\n"
        "\tyear = {2026}}\n"
        "\n" + refs_smart_block + "\n",
        encoding="utf-8",
    )
    original = path.read_text(encoding="utf-8")

    bib = Library(path)
    assert bib.groups == {}
    bib.save()  # pristine
    assert path.read_text(encoding="utf-8") == original

    bib.groups["My Group"] = ("K1",)
    bib.save()
    text = path.read_text(encoding="utf-8")
    assert _smart_groups_block(text) == refs_smart_block
    assert text.index(STATIC_GROUPS_HEAD) < text.index(SMART_GROUPS_HEAD)

    reloaded = Library(path)
    assert reloaded.groups == {"My Group": ("K1",)}
    reloaded.save()  # pristine save of the reloaded file is stable
    assert path.read_text(encoding="utf-8") == text
