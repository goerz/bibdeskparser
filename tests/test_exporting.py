"""Tests for `bibdeskparser.exporting`."""

from pathlib import Path

import bibtexparser
import pytest

from bibdeskparser.entry import Entry
from bibdeskparser.exporting import export_entries
from bibdeskparser.middleware import parse_stack

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"


@pytest.fixture(scope="module")
def refs_library():
    """`refs.bib` parsed through the full `parse_stack()`."""
    text = REFS_BIB.read_text(encoding="utf-8")
    return bibtexparser.parse_string(text, parse_stack=parse_stack())


@pytest.fixture
def jpb_entry(refs_library):
    """`GoerzJPB2011`: article with a bare `journal` macro, one
    `bdsk-file-1`, one `bdsk-url-1`."""
    return Entry._wrap(refs_library.entries_dict["GoerzJPB2011"])


@pytest.fixture
def nc_entry(refs_library):
    """`KatrukhaNC2017`: article carrying every field of the "minimal"
    `article` whitelist, including `number`."""
    return Entry._wrap(refs_library.entries_dict["KatrukhaNC2017"])


@pytest.fixture
def diploma_entry(refs_library):
    """`GoerzDiploma2010`: mastersthesis whose `school` field has a
    stored TeX accent (`Universit{\\"a}t`)."""
    return Entry._wrap(refs_library.entries_dict["GoerzDiploma2010"])


@pytest.fixture
def phd_entry(refs_library):
    """`GoerzPhd2015`: phdthesis."""
    return Entry._wrap(refs_library.entries_dict["GoerzPhd2015"])


@pytest.fixture(scope="module")
def raw_library():
    """`refs.bib` parsed with NO middleware (`parse_stack=[]`), so
    field values keep their literal, TeX-encoded form exactly as
    stored on disk (`DeTeXifyMiddleware`, part of `parse_stack()`, is
    what normally converts them to Unicode at parse time)."""
    text = REFS_BIB.read_text(encoding="utf-8")
    return bibtexparser.parse_string(text, parse_stack=[])


@pytest.fixture
def raw_diploma_entry(raw_library):
    """`GoerzDiploma2010`, parsed without `DeTeXifyMiddleware`: its
    `school` field's stored value is literal TeX-encoded text
    (`Universit{\\"a}t`), unlike `diploma_entry` above."""
    return Entry._wrap(raw_library.entries_dict["GoerzDiploma2010"])


# -- "default" format -------------------------------------------------- #


def test_default_field_order(jpb_entry):
    """Normal fields come first (alphabetical), then bdsk-* fields.

    The exported normal fields are exactly the entry's dict interface
    (which now includes the readable-but-not-writable `keywords`
    field).
    """
    text = export_entries([jpb_entry], format="default")
    names = [
        line.split(" = ", 1)[0].strip() for line in text.splitlines()[1:-1]
    ]
    assert "keywords" in jpb_entry.keys()
    expected = sorted(jpb_entry.keys(), key=str.lower) + [
        "bdsk-file-1",
        "bdsk-url-1",
    ]
    assert names == expected


def test_keywords_exported(jpb_entry):
    """The `keywords` field is exported in the "default" and "raw"
    formats, and is readable (but not writable) through the `Entry`
    dict interface."""
    line = "\tkeywords = {OCT, Quantum Gates, "
    assert line in export_entries([jpb_entry], format="default")
    assert line in export_entries([jpb_entry], format="raw")
    assert jpb_entry["keywords"].startswith("OCT, Quantum Gates")


def test_one_word_keyword_never_a_macro():
    """A single-word keyword that would pass as a macro name is
    exported braced, and never pulls in an `@string` definition."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry._set_keywords(("alpha",))
    text = export_entries([entry], strings={"alpha": "Some Value"})
    assert "\tkeywords = {alpha}" in text
    assert "@string" not in text


def test_default_bare_macro_field(jpb_entry):
    """A bare macro reference is written unbraced."""
    text = export_entries([jpb_entry], format="default")
    assert "\tjournal = jpb,\n" in text


def test_default_unicode_no_stray_tex(jpb_entry):
    """Text fields are Unicode, without stray TeX escapes."""
    text = export_entries([jpb_entry], format="default")
    title = jpb_entry["title"]
    assert "{\\" not in title
    assert f"\ttitle = {{{title}}},\n" in text


def test_default_excludes_dates(jpb_entry):
    """`date-added`/`date-modified` are never included."""
    text = export_entries([jpb_entry], format="default")
    assert "date-added" not in text
    assert "date-modified" not in text


def test_default_bdsk_file_plain_path(jpb_entry):
    """`bdsk-file-1` is rendered as a plain relative path, not base64."""
    text = export_entries([jpb_entry], format="default")
    path = jpb_entry.files[0]
    assert path.endswith(".pdf")
    assert f"\tbdsk-file-1 = {{{path}}},\n" in text
    assert "YnBsaXN0" not in text


def test_default_bdsk_url(jpb_entry):
    """`bdsk-url-1` is rendered as the plain URL (last field, no
    trailing comma, closing brace on its own line)."""
    text = export_entries([jpb_entry], format="default")
    url = jpb_entry.urls[0]
    assert f"\tbdsk-url-1 = {{{url}}}\n}}\n" in text


# -- "raw" format, contrasted against "default" ------------------------- #


def test_raw_field_order_matches_default(jpb_entry):
    """`raw` uses the same field order as `default`."""
    default_text = export_entries([jpb_entry], format="default")
    raw_text = export_entries([jpb_entry], format="raw")

    def names(text):
        return [
            line.split(" = ", 1)[0].strip() for line in text.splitlines()[1:-1]
        ]

    assert names(raw_text) == names(default_text)


def test_raw_bdsk_file_plain_path(jpb_entry):
    """`raw` also shows the plain relative path for `bdsk-file-N`."""
    text = export_entries([jpb_entry], format="raw")
    path = jpb_entry.files[0]
    assert f"\tbdsk-file-1 = {{{path}}},\n" in text
    assert "YnBsaXN0" not in text


def test_raw_vs_default_texify_contrast(raw_diploma_entry):
    """`raw` shows the stored TeX-escaped value; `default` shows the
    decoded Unicode value -- for the same field.

    Uses `raw_diploma_entry` (parsed without `DeTeXifyMiddleware`)
    rather than the usual `diploma_entry` fixture: entries loaded
    through the normal `parse_stack()` are already detexified to
    Unicode at parse time (matching how `Library` keeps its in-memory
    model), so their stored field values would *not* show a TeX
    contrast here -- that only happens at write time. `raw_diploma_entry`
    isolates the "value literally as stored" case that `format="raw"`
    is defined against.
    """
    diploma_entry = raw_diploma_entry
    raw_school = next(
        field.value
        for field in diploma_entry._entry.fields
        if field.key.lower() == "school"
    )
    assert '\\"' in raw_school  # sanity check: the fixture has a TeX accent

    default_text = export_entries([diploma_entry], format="default")
    raw_text = export_entries([diploma_entry], format="raw")

    unicode_school = diploma_entry["school"]
    assert "Universität" in unicode_school

    # default: decoded Unicode value, braced
    assert f"\tschool = {{{unicode_school}}},\n" in default_text
    assert raw_school not in default_text
    assert unicode_school not in raw_text

    # raw: literal stored (TeX-escaped) value, verbatim
    assert f"\tschool = {raw_school},\n" in raw_text


# -- "minimal" format ---------------------------------------------------- #


def _minimal_body_lines(text):
    """The body lines (without header/closing brace) of a minimal-format
    single-entry export."""
    lines = text.splitlines(keepends=True)
    assert lines[-1] == "}\n"
    return lines[1:-1]


def test_minimal_article_whitelist(nc_entry):
    """`article` whitelist, in order, 4-space indent, Title-case names,
    trailing comma on every field including the last, bare macro."""
    text = export_entries([nc_entry], format="minimal")
    assert text.splitlines(keepends=True)[0] == (
        f"@{nc_entry.entry_type}{{{nc_entry.key},\n"
    )
    expected_fields = [
        "author",
        "title",
        "journal",
        "year",
        "doi",
        "pages",
        "volume",
        "number",
    ]
    body_lines = _minimal_body_lines(text)
    assert len(body_lines) == len(expected_fields)
    for line, name in zip(body_lines, expected_fields):
        value = nc_entry[name]
        if name == "journal":
            assert line == f"    Journal = {value},\n"
        else:
            assert line == f"    {name.capitalize()} = {{{value}}},\n"


def test_minimal_mastersthesis_whitelist(diploma_entry):
    """`mastersthesis` whitelist: author, title, school, year."""
    text = export_entries([diploma_entry], format="minimal")
    expected_fields = ["author", "title", "school", "year"]
    body_lines = _minimal_body_lines(text)
    assert len(body_lines) == len(expected_fields)
    for line, name in zip(body_lines, expected_fields):
        value = diploma_entry[name]
        assert line == f"    {name.capitalize()} = {{{value}}},\n"


def test_minimal_phdthesis_whitelist(phd_entry):
    """`phdthesis` whitelist: author, title, school, year."""
    text = export_entries([phd_entry], format="minimal")
    expected_fields = ["author", "title", "school", "year"]
    body_lines = _minimal_body_lines(text)
    assert len(body_lines) == len(expected_fields)
    for line, name in zip(body_lines, expected_fields):
        value = phd_entry[name]
        assert line == f"    {name.capitalize()} = {{{value}}},\n"


def test_minimal_fallback_whitelist():
    """An entry type not covered by getbibtex or the thesis extension
    falls back to `author, title, year`."""
    entry = Entry(
        "misc",
        "X2026",
        fields={"title": "T", "author": "A. One", "year": "2026"},
    )
    text = export_entries([entry], format="minimal")
    assert text == (
        "@misc{X2026,\n"
        "    Author = {A. One},\n"
        "    Title = {T},\n"
        "    Year = {2026},\n"
        "}\n"
    )


def test_minimal_skips_missing_fields():
    """A whitelisted field that is absent is silently skipped."""
    entry = Entry("article", "K2026", fields={"title": "T", "year": "2026"})
    text = export_entries([entry], format="minimal")
    assert "Author" not in text
    assert "Doi" not in text
    assert "Title = {T}," in text


# -- @string macro definitions -------------------------------------------- #


def test_string_block_only_for_referenced_macros(jpb_entry):
    """Only macros actually referenced by an entry are emitted, sorted
    by name."""
    text = export_entries(
        [jpb_entry],
        strings={"jpb": "J. Phys. B", "unused": "Nope"},
        format="default",
    )
    assert "@string{jpb = {J. Phys. B}}\n" in text
    assert "unused" not in text
    assert "Nope" not in text


def test_string_block_blank_line_before_entry(jpb_entry):
    """A blank line separates the `@string` block from the first
    entry."""
    text = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. B"}, format="default"
    )
    assert "@string{jpb = {J. Phys. B}}\n\n@article{" in text


def test_no_string_block_without_strings(jpb_entry):
    """Without `strings`, no `@string` block is emitted, but the bare
    macro field is still written."""
    text = export_entries([jpb_entry], format="default")
    assert "@string" not in text
    assert "\tjournal = jpb,\n" in text


def test_string_block_raw_format(jpb_entry):
    """`@string` definitions are also supported for `raw`."""
    text = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. B"}, format="raw"
    )
    assert "@string{jpb = {J. Phys. B}}\n" in text


def test_minimal_never_emits_string_block(jpb_entry):
    """`minimal` never emits `@string` definitions."""
    text = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. B"}, format="minimal"
    )
    assert "@string" not in text


# -- outfile --------------------------------------------------------------- #


def test_outfile_path(tmp_path, jpb_entry):
    """Writing to a path returns `None` and writes the same text as
    returning it."""
    path = tmp_path / "out.bib"
    result = export_entries([jpb_entry], outfile=path)
    assert result is None
    assert path.read_text(encoding="utf-8") == export_entries([jpb_entry])


def test_outfile_open_file_not_closed(tmp_path, jpb_entry):
    """Writing to an already-open file object does not close it."""
    path = tmp_path / "out2.bib"
    with open(path, "w", encoding="utf-8") as fh:
        result = export_entries([jpb_entry], outfile=fh)
        assert result is None
        assert not fh.closed
        fh.write("EXTRA")
    assert path.read_text(encoding="utf-8").endswith("EXTRA")


# -- multiple entries -------------------------------------------------- #


def test_multiple_entries_single_blank_line(diploma_entry, phd_entry):
    """Entries are separated by exactly one blank line, with a single
    final trailing newline."""
    text = export_entries([diploma_entry, phd_entry], format="minimal")
    assert "}\n\n@phdthesis{" in text
    assert "}\n\n\n@phdthesis{" not in text
    assert text.endswith("}\n")
    assert not text.endswith("}\n\n")


# -- validation -------------------------------------------------------- #


def test_invalid_format_raises():
    """An unknown `format` raises `ValueError`."""
    with pytest.raises(ValueError, match="format"):
        export_entries([], format="bogus")
