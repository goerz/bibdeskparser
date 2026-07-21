"""Tests for `bibdeskparser.exporting`."""

from pathlib import Path

import bibtexparser
import pytest

import bibdeskparser.config as config
from bibdeskparser.entry import Entry
from bibdeskparser.exporting import export_entries
from bibdeskparser.macros import ValueString
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


def _capitalized(name):
    """`name` capitalized the way exports capitalize field names."""
    return "-".join(part.capitalize() for part in name.split("-"))


def _body_lines(text):
    """The body lines (without header/closing brace) of a single-entry
    export."""
    lines = text.splitlines(keepends=True)
    assert lines[-1] == "}\n"
    return lines[1:-1]


# -- default parameters -------------------------------------------------- #


def test_default_field_order(jpb_entry):
    """Normal fields come first (alphabetical), then bdsk-* fields,
    all with capitalized names.

    The exported normal fields are exactly the entry's dict interface
    (which includes the readable-but-not-writable `keywords` field).
    """
    text = export_entries([jpb_entry])
    names = [
        line.split(" = ", 1)[0].strip() for line in text.splitlines()[1:-1]
    ]
    assert "keywords" in jpb_entry.keys()
    expected = [
        _capitalized(name) for name in sorted(jpb_entry.keys(), key=str.lower)
    ] + ["Bdsk-File-1", "Bdsk-Url-1"]
    assert names == expected


def test_layout(jpb_entry):
    """The export layout: 4-space indent, capitalized field names, a
    comma after every field, and the closing brace on its own line."""
    text = export_entries([jpb_entry])
    lines = _body_lines(text)
    for line in lines:
        assert line.startswith("    ")
        assert line.endswith(",\n")
        name = line.split(" = ", 1)[0].strip()
        assert name == _capitalized(name)


def test_keywords_exported(jpb_entry):
    """The `keywords` field is exported (braced) both as Unicode and
    as stored, and is readable (but not writable) through the `Entry`
    dict interface."""
    line = "    Keywords = {OCT, Quantum Gates, "
    assert line in export_entries([jpb_entry])
    assert line in export_entries([jpb_entry], unicode=False)
    assert jpb_entry["keywords"].startswith("OCT, Quantum Gates")


def test_one_word_keyword_never_a_macro():
    """A single-word keyword that would pass as a macro name is
    exported braced, never pulls in an `@string` definition, and is
    never expanded."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry._set_keywords(("alpha",))
    text = export_entries([entry], strings={"alpha": "Some Value"})
    assert "    Keywords = {alpha},\n" in text
    assert "@string" not in text
    expanded = export_entries(
        [entry], strings={"alpha": "Some Value"}, expand_strings=True
    )
    assert "    Keywords = {alpha},\n" in expanded


def test_default_bare_macro_field(jpb_entry):
    """A bare macro reference is written unbraced."""
    text = export_entries([jpb_entry])
    assert "    Journal = jpb,\n" in text


def test_default_unicode_no_stray_tex(jpb_entry):
    """Text fields are Unicode, without stray TeX escapes."""
    text = export_entries([jpb_entry])
    title = jpb_entry["title"]
    assert "{\\" not in title
    assert f"    Title = {{{title}}},\n" in text


def test_default_excludes_dates(jpb_entry):
    """`date-added`/`date-modified` are not part of `fields="full"`."""
    text = export_entries([jpb_entry])
    assert "date-added" not in text.lower()
    assert "date-modified" not in text.lower()


def test_default_bdsk_file_plain_path(jpb_entry):
    """`bdsk-file-1` is rendered as a plain relative path, not base64."""
    text = export_entries([jpb_entry])
    path = jpb_entry.files[0]
    assert path.endswith(".pdf")
    assert f"    Bdsk-File-1 = {{{path}}},\n" in text
    assert "YnBsaXN0" not in text


def test_default_bdsk_url(jpb_entry):
    """`bdsk-url-1` is rendered as the plain URL (last field, with a
    trailing comma, closing brace on its own line)."""
    text = export_entries([jpb_entry])
    url = jpb_entry.urls[0]
    assert f"    Bdsk-Url-1 = {{{url}}},\n}}\n" in text


def test_value_string_literal_stays_braced():
    """A literal value that happens to look like a macro name
    (`ValueString`) is exported braced, not as a bare reference."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["journal"] = ValueString("prl")
    text = export_entries([entry], strings={"prl": "Phys. Rev. Lett."})
    assert "    Journal = {prl},\n" in text
    assert "@string" not in text


# -- unicode=False (stored TeX-encoded values) --------------------------- #


def test_no_unicode_field_order_matches_default(jpb_entry):
    """`unicode=False` uses the same field order as the default."""
    default_text = export_entries([jpb_entry])
    raw_text = export_entries([jpb_entry], unicode=False)

    def names(text):
        return [
            line.split(" = ", 1)[0].strip() for line in text.splitlines()[1:-1]
        ]

    assert names(raw_text) == names(default_text)


def test_no_unicode_bdsk_file_plain_path(jpb_entry):
    """`unicode=False` also shows the plain relative path for
    `bdsk-file-N`."""
    text = export_entries([jpb_entry], unicode=False)
    path = jpb_entry.files[0]
    assert f"    Bdsk-File-1 = {{{path}}},\n" in text
    assert "YnBsaXN0" not in text


def test_no_unicode_vs_default_texify_contrast(diploma_entry):
    """`unicode=False` shows the TeX-encoded value exactly as it
    would be written to the `.bib` file; the default shows the
    decoded Unicode value -- for the same field. The result does not
    depend on whether the in-memory value happens to be stored as
    Unicode (file-loaded) or TeX-encoded (assigned)."""
    default_text = export_entries([diploma_entry])
    raw_text = export_entries([diploma_entry], unicode=False)

    unicode_school = diploma_entry["school"]
    assert "Universität" in unicode_school
    tex_school = 'Freie Universit{\\"a}t Berlin'

    # default: decoded Unicode value, braced
    assert f"    School = {{{unicode_school}}},\n" in default_text
    assert tex_school not in default_text
    assert unicode_school not in raw_text

    # unicode=False: TeX-encoded value, braced
    assert f"    School = {{{tex_school}}},\n" in raw_text


# -- expand_strings ------------------------------------------------------ #


def test_expand_strings_replaces_reference(jpb_entry):
    """`expand_strings=True` replaces a bare macro reference by its
    braced value and emits no `@string` definitions."""
    text = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. B"}, expand_strings=True
    )
    assert "    Journal = {J. Phys. B},\n" in text
    assert "@string" not in text


def test_expand_strings_month_macro():
    """The standard month macros resolve without any `strings`."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["month"] = "jan"
    text = export_entries([entry], expand_strings=True)
    assert "    Month = {January},\n" in text


def test_expand_strings_undefined_macro_warns():
    """An undefined macro stays a bare reference, with a warning."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["journal"] = "nope"
    with pytest.warns(UserWarning, match="'nope' is undefined"):
        text = export_entries([entry], expand_strings=True)
    assert "    Journal = nope,\n" in text


def test_expand_strings_texified():
    """With `unicode=False`, an expanded macro value is TeX-encoded."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["journal"] = "zfk"
    text = export_entries(
        [entry],
        strings={"zfk": "Z. f. Kernphysik München"},
        unicode=False,
        expand_strings=True,
    )
    assert '    Journal = {Z. f. Kernphysik M{\\"u}nchen},\n' in text


# -- fields selection ---------------------------------------------------- #


def test_minimal_article_whitelist(nc_entry):
    """`fields="minimal"`: `article` whitelist, in order."""
    text = export_entries([nc_entry], fields="minimal")
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
        "eprint",
        "archiveprefix",
    ]
    body_lines = _body_lines(text)
    # the synthesized `archive` link base (bioRxiv eprint) is appended
    assert len(body_lines) == len(expected_fields) + 1
    assert body_lines[-1] == (
        "    Archive = {https://www.biorxiv.org/content/10.1101},\n"
    )
    for line, name in zip(body_lines, expected_fields):
        value = nc_entry[name]
        if name == "journal":
            assert line == f"    Journal = {value},\n"
        else:
            assert line == f"    {name.capitalize()} = {{{value}}},\n"


def test_minimal_mastersthesis_whitelist(diploma_entry):
    """`mastersthesis` whitelist: author, title, school, year."""
    text = export_entries([diploma_entry], fields="minimal")
    expected_fields = ["author", "title", "school", "year"]
    body_lines = _body_lines(text)
    assert len(body_lines) == len(expected_fields)
    for line, name in zip(body_lines, expected_fields):
        value = diploma_entry[name]
        assert line == f"    {name.capitalize()} = {{{value}}},\n"


def test_minimal_phdthesis_whitelist(phd_entry):
    """`phdthesis` whitelist: author, title, school, year."""
    text = export_entries([phd_entry], fields="minimal")
    expected_fields = ["author", "title", "school", "year"]
    body_lines = _body_lines(text)
    assert len(body_lines) == len(expected_fields)
    for line, name in zip(body_lines, expected_fields):
        value = phd_entry[name]
        assert line == f"    {name.capitalize()} = {{{value}}},\n"


def test_minimal_fallback_whitelist():
    """An entry type without a dedicated whitelist falls back to
    `author, title, year`."""
    entry = Entry(
        "misc",
        "X2026",
        fields={"title": "T", "author": "A. One", "year": "2026"},
    )
    text = export_entries([entry], fields="minimal")
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
    text = export_entries([entry], fields="minimal")
    assert "Author" not in text
    assert "Doi" not in text
    assert "Title = {T}," in text


def test_fields_list(nc_entry):
    """An explicit field list selects those fields, in the given
    order, matching case-insensitively."""
    text = export_entries([nc_entry], fields=["YEAR", "author"])
    body_lines = _body_lines(text)
    assert body_lines == [
        f"    Year = {{{nc_entry['year']}}},\n",
        f"    Author = {{{nc_entry['author']}}},\n",
    ]


def test_fields_list_missing_omitted():
    """A listed field not defined on an entry is silently omitted."""
    entry = Entry("article", "K2026", fields={"title": "T"})
    text = export_entries([entry], fields=["doi", "title"])
    assert _body_lines(text) == ["    Title = {T},\n"]


def test_fields_list_bdsk(jpb_entry):
    """An explicitly listed `bdsk-file-N` field renders as its plain
    relative path."""
    text = export_entries([jpb_entry], fields=["bdsk-file-1"])
    path = jpb_entry.files[0]
    assert _body_lines(text) == [f"    Bdsk-File-1 = {{{path}}},\n"]


def test_fields_list_string_block(jpb_entry):
    """The `@string` block covers only macros referenced by the
    *selected* fields."""
    with_journal = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. B"}, fields=["journal"]
    )
    assert "@string{jpb = {J. Phys. B}}\n" in with_journal
    without_journal = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. B"}, fields=["title"]
    )
    assert "@string" not in without_journal


# -- @string macro definitions ------------------------------------------- #


def test_string_block_only_for_referenced_macros(jpb_entry):
    """Only macros actually referenced by an entry are emitted, sorted
    by name."""
    text = export_entries(
        [jpb_entry],
        strings={"jpb": "J. Phys. B", "unused": "Nope"},
    )
    assert "@string{jpb = {J. Phys. B}}\n" in text
    assert "unused" not in text
    assert "Nope" not in text


def test_string_block_blank_line_before_entry(jpb_entry):
    """A blank line separates the `@string` block from the first
    entry."""
    text = export_entries([jpb_entry], strings={"jpb": "J. Phys. B"})
    assert "@string{jpb = {J. Phys. B}}\n\n@article{" in text


def test_no_string_block_without_strings(jpb_entry):
    """Without `strings`, no `@string` block is emitted, but the bare
    macro field is still written."""
    text = export_entries([jpb_entry])
    assert "@string" not in text
    assert "    Journal = jpb,\n" in text


def test_string_block_texified_when_not_unicode(jpb_entry):
    """With `unicode=False`, `@string` values are TeX-encoded."""
    text = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. Bü"}, unicode=False
    )
    assert '@string{jpb = {J. Phys. B{\\"u}}}\n' in text


def test_minimal_emits_string_block(jpb_entry):
    """`fields="minimal"` includes the `@string` definitions needed by
    the selected fields (unless `expand_strings=True`)."""
    text = export_entries(
        [jpb_entry], strings={"jpb": "J. Phys. B"}, fields="minimal"
    )
    assert "@string{jpb = {J. Phys. B}}\n" in text
    expanded = export_entries(
        [jpb_entry],
        strings={"jpb": "J. Phys. B"},
        fields="minimal",
        expand_strings=True,
    )
    assert "@string" not in expanded


def test_month_macro_not_in_string_block():
    """A referenced standard month macro does not produce an `@string`
    definition (BibTeX defines the months natively)."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["month"] = "jan"
    text = export_entries([entry], strings={"unrelated": "X"})
    assert "    Month = jan,\n" in text
    assert "@string" not in text


def test_custom_month_macro_in_string_block():
    """A custom `@string` definition overriding a standard month macro
    is emitted like any other referenced macro, and takes precedence
    over the built-in value in expansion."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["month"] = "jan"
    text = export_entries([entry], strings={"jan": "Januar"})
    assert "@string{jan = {Januar}}\n" in text
    assert "    Month = jan,\n" in text
    expanded = export_entries(
        [entry], strings={"jan": "Januar"}, expand_strings=True
    )
    assert "    Month = {Januar},\n" in expanded
    assert "@string" not in expanded


# -- outfile -------------------------------------------------------------- #


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


# -- multiple entries ---------------------------------------------------- #


def test_multiple_entries_single_blank_line(diploma_entry, phd_entry):
    """Entries are separated by exactly one blank line, with a single
    final trailing newline."""
    text = export_entries([diploma_entry, phd_entry], fields="minimal")
    assert "}\n\n@phdthesis{" in text
    assert "}\n\n\n@phdthesis{" not in text
    assert text.endswith("}\n")
    assert not text.endswith("}\n\n")


# -- validation ----------------------------------------------------------- #


def test_invalid_fields_raises():
    """An unknown `fields` string, or a list with a non-string item,
    raises `ValueError`."""
    with pytest.raises(ValueError, match="fields"):
        export_entries([], fields="bogus")
    with pytest.raises(ValueError, match="field name"):
        export_entries([], fields=["title", 42])
    with pytest.raises(ValueError, match="fields"):
        export_entries([], fields=17)


# -- preprint-only entries ------------------------------------------------ #


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the process-global configuration around every test
    (exports read the `preprint_archives` and `preprint_export`
    settings)."""
    config.active.reset()
    yield
    config.active.reset()


@pytest.fixture
def arxiv_entry(refs_library):
    """`Wilhelm2003.10132`: preprint-only `@unpublished`
    (pseudo-journal `arXiv:2003.10132`, matching
    `eprint`/`archiveprefix`, a DOI, and a status note)."""
    return Entry._wrap(refs_library.entries_dict["Wilhelm2003.10132"])


@pytest.fixture
def hal_entry(refs_library):
    """`TuriniciHAL00640217`: preprint-only `@unpublished`
    (pseudo-journal `HAL:hal-00640217`, `eprint`/`archiveprefix`, a
    `url` and a status note, but no `doi`)."""
    return Entry._wrap(refs_library.entries_dict["TuriniciHAL00640217"])


def test_minimal_unpublished_export(arxiv_entry):
    """The default (`preprint="unpublished"`) minimal export: the
    structured eprint form with the stored status note, no
    pseudo-journal, no `archive` (arXiv is the styles' default)."""
    text = export_entries([arxiv_entry], fields="minimal")
    assert text.startswith("@unpublished{Wilhelm2003.10132,\n")
    assert "Eprint = {2003.10132}" in text
    assert "Archiveprefix = {arXiv}" in text
    assert "Doi = {10.48550/arxiv.2003.10132}" in text
    assert "Note = {preprint only}" in text
    assert "Journal" not in text
    assert "Archive =" not in text


def test_minimal_unpublished_export_hal(hal_entry):
    """The default minimal export of a HAL entry emits the `archive`
    link base (REVTeX's eprint links point at arxiv.org without
    it)."""
    text = export_entries([hal_entry], fields="minimal")
    assert text.startswith("@unpublished{TuriniciHAL00640217,\n")
    assert "Eprint = {hal-00640217}" in text
    assert "Archiveprefix = {HAL}" in text
    assert "Archive = {https://hal.science}" in text
    assert "Url = {https://hal.science/hal-00640217}" in text
    assert "Note = {lecture notes}" in text
    assert "Journal" not in text


def test_unpublished_export_synthesizes_note():
    """A minimal `preprint="unpublished"` export synthesizes the
    required `note` as "preprint" for an entry without one; a full
    export never does (it must not round-trip a synthesized note
    into a library)."""
    entry = Entry(
        "unpublished",
        "k",
        fields={
            "author": "Doe, Jane",
            "title": "A Title",
            "journal": "arXiv:1234.5678",
            "eprint": "1234.5678",
            "archiveprefix": "arXiv",
            "year": "2024",
        },
    )
    text = export_entries([entry], fields="minimal")
    assert text.startswith("@unpublished{k,\n")
    assert "Note = {preprint}" in text
    text = export_entries([entry])
    assert text.startswith("@unpublished{k,\n")
    assert "Note" not in text
    assert "Journal = {arXiv:1234.5678}" in text  # full keeps stored


def test_minimal_misc_export(arxiv_entry):
    """`preprint="misc"`: the same structured form as `@misc` (the
    stored note is kept, but never synthesized)."""
    text = export_entries([arxiv_entry], fields="minimal", preprint="misc")
    assert text.startswith("@misc{Wilhelm2003.10132,\n")
    assert "Eprint = {2003.10132}" in text
    assert "Archiveprefix = {arXiv}" in text
    assert "Doi = {10.48550/arxiv.2003.10132}" in text
    assert "Note = {preprint only}" in text  # stored
    assert "Journal" not in text


def test_minimal_article_export(arxiv_entry):
    """`preprint="article"`: the pseudo-journal form, hyperlinked via
    the DOI-resolver `url`; no eprint/doi fields."""
    text = export_entries([arxiv_entry], fields="minimal", preprint="article")
    assert text.startswith("@article{Wilhelm2003.10132,\n")
    assert "Journal = {arXiv:2003.10132}" in text
    assert "Url = {https://doi.org/10.48550/arxiv.2003.10132}" in text
    assert "Eprint" not in text
    assert "Archiveprefix" not in text
    assert "Doi" not in text


def test_minimal_article_export_stored_url(hal_entry):
    """`preprint="article"` without a DOI: the stored `url` links the
    pseudo-journal."""
    text = export_entries([hal_entry], fields="minimal", preprint="article")
    assert text.startswith("@article{TuriniciHAL00640217,\n")
    assert "Journal = {HAL:hal-00640217}" in text
    assert "Url = {https://hal.science/hal-00640217}" in text


def test_full_unpublished_export(arxiv_entry):
    """The default full export keeps all stored fields (including the
    pseudo-journal, which BibTeX ignores on `@unpublished`)."""
    text = export_entries([arxiv_entry])
    assert text.startswith("@unpublished{Wilhelm2003.10132,\n")
    assert "Journal = {arXiv:2003.10132}" in text
    assert "Eprint = {2003.10132}" in text
    assert "Note = {preprint only}" in text
    assert "Abstract = " in text
    assert "Bdsk-File-1 = " in text


def test_full_export_emits_archive(hal_entry):
    """A full export of a non-arXiv preprint-only entry also ensures
    `eprint`/`archiveprefix` and the `archive` link base."""
    text = export_entries([hal_entry])
    assert text.startswith("@unpublished{TuriniciHAL00640217,\n")
    assert "Eprint = {hal-00640217}" in text
    assert "Archiveprefix = {HAL}" in text
    assert "Archive = {https://hal.science}" in text
    assert "Journal = {HAL:hal-00640217}" in text


def test_full_export_of_legacy_article():
    """A full export converts the legacy `@article` form and
    synthesizes the missing eprint fields."""
    entry = Entry(
        "article",
        "k",
        fields={
            "author": "Doe, Jane",
            "title": "A Title",
            "journal": "arXiv:1234.5678v2",
            "year": "2024",
        },
    )
    text = export_entries([entry])
    assert text.startswith("@unpublished{k,\n")
    assert "Journal = {arXiv:1234.5678v2}" in text
    assert "Eprint = {1234.5678}" in text  # version stripped
    assert "Archiveprefix = {arXiv}" in text


def test_full_article_export(arxiv_entry):
    """A full `preprint="article"` export drops the eprint/doi fields
    in favor of the pseudo-journal and the DOI-resolver `url`, and
    keeps all other stored fields."""
    text = export_entries([arxiv_entry], preprint="article")
    assert text.startswith("@article{Wilhelm2003.10132,\n")
    assert "Journal = {arXiv:2003.10132}" in text
    assert "Url = {https://doi.org/10.48550/arxiv.2003.10132}" in text
    assert "Eprint" not in text
    assert "Doi" not in text
    assert "Abstract = " in text
    assert "Bdsk-File-1 = " in text


def test_stored_export(arxiv_entry):
    """`preprint="stored"` exports the entry exactly as stored (used
    by `Library.edit` for its editor buffer)."""
    text = export_entries([arxiv_entry], preprint="stored")
    assert text.startswith("@unpublished{Wilhelm2003.10132,\n")
    assert "Journal = {arXiv:2003.10132}" in text
    assert "Eprint = {2003.10132}" in text
    assert "Doi = {10.48550/arxiv.2003.10132}" in text
    assert "Archive =" not in text


def test_stored_archive_field_respected():
    """A stored `archive` field is written as-is, never overwritten
    or duplicated."""
    entry = Entry(
        "unpublished",
        "k",
        fields={
            "author": "Doe, Jane",
            "title": "A Title",
            "eprint": ValueString("hal-00640217"),
            "archiveprefix": ValueString("HAL"),
            "archive": ValueString("https://hal.archives-ouvertes.fr"),
            "year": "2012",
        },
    )
    text = export_entries([entry], fields="minimal")
    assert text.count("Archive =") == 1
    assert "Archive = {https://hal.archives-ouvertes.fr}" in text


def test_preprint_export_from_config(arxiv_entry):
    """The `preprint_export` configuration provides the default for
    the `preprint` parameter."""
    config.active.preprint_export = "article"
    text = export_entries([arxiv_entry], fields="minimal")
    assert text.startswith("@article{Wilhelm2003.10132,\n")


def test_invalid_preprint_raises(arxiv_entry):
    with pytest.raises(ValueError, match="preprint must be"):
        export_entries([arxiv_entry], preprint="bogus")


def test_explicit_fields_export_stored(arxiv_entry):
    """An explicit field list always exports the stored fields, with
    the stored entry type."""
    text = export_entries([arxiv_entry], fields=["journal", "eprint", "doi"])
    assert text.startswith("@unpublished{Wilhelm2003.10132,\n")
    assert "Journal = {arXiv:2003.10132}" in text
    assert "Eprint = {2003.10132}" in text
    assert "Doi = {10.48550/arxiv.2003.10132}" in text


def test_full_export_published_keeps_eprint(jpb_entry):
    """A published article (journal macro) is not preprint-only: it
    keeps its type and its `eprint`/`archiveprefix` fields."""
    text = export_entries([jpb_entry])
    assert text.startswith("@article{GoerzJPB2011,\n")
    assert "Eprint = {1103.6050}" in text
    assert "Archiveprefix = {arXiv}" in text


def test_export_published_hal_archive():
    """A full or minimal export of a *published* article whose eprint
    names a non-arXiv archive appends the `archive` link base (in
    field order for full exports, before the `bdsk-*` fields)."""
    entry = Entry(
        "article",
        "k",
        fields={
            "author": "Doe, Jane",
            "title": "A Title",
            "journal": "Phys. Rev. X",
            "volume": "10",
            "pages": "021058",
            "doi": "10.1103/physrevx.10.021058",
            "eprint": ValueString("hal-02887773"),
            "archiveprefix": ValueString("HAL"),
            "year": "2020",
        },
    )
    entry.add_url("https://example.com")
    text = export_entries([entry], fields="minimal")
    assert text.startswith("@article{k,\n")
    assert "Eprint = {hal-02887773}" in text
    assert "Archive = {https://hal.science}" in text
    full = export_entries([entry])
    assert "Archive = {https://hal.science}" in full
    assert full.index("Archive =") < full.index("Bdsk-Url-1 =")
    # not in "stored" mode (used by `Library.edit`, which must not
    # round-trip a synthetic field into the library)
    assert "Archive =" not in export_entries([entry], preprint="stored")
    assert "Archive =" not in export_entries(
        [entry], fields="minimal", preprint="stored"
    )
    # nor with an explicit field list (always the stored fields)
    assert "Archive =" not in export_entries(
        [entry], fields=["eprint", "archiveprefix", "archive"]
    )


def test_thesis_with_eprint_not_transformed():
    """A thesis deposited on a preprint server is not preprint-only:
    no transformation (but its full export still gains the `archive`
    link base -- REVTeX renders the eprint of every entry type)."""
    entry = Entry(
        "phdthesis",
        "k",
        fields={
            "author": "Doe, Jane",
            "title": "A Thesis",
            "school": "A University",
            "eprint": ValueString("tel-00007910v2"),
            "archiveprefix": ValueString("hal"),
            "year": "2014",
        },
    )
    text = export_entries([entry])
    assert text.startswith("@phdthesis{k,\n")
    assert "Eprint = {tel-00007910v2}" in text
    assert "Archive = {https://hal.science}" in text


def test_unpublished_export_keeps_stored_note():
    """The `unpublished` form writes a stored `note` verbatim."""
    entry = Entry(
        "misc",
        "k",
        fields={
            "author": "Doe, Jane",
            "title": "A Title",
            "journal": "arXiv:1234.5678",
            "eprint": "1234.5678",
            "archiveprefix": "arXiv",
            "note": "submitted to Phys. Rev. A",
            "year": "2024",
        },
    )
    text = export_entries([entry], fields="minimal", preprint="unpublished")
    assert text.startswith("@unpublished{k,\n")
    assert "Note = {submitted to Phys. Rev. A}" in text
    assert "Note = {preprint}" not in text
