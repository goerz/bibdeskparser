"""Tests for the plain (non-database) `.bib` format: detection, the
marker line, plain-format saving, format conversion, and
`Library.export(update=...)`."""

import shutil
import warnings
from pathlib import Path

import pytest

import bibdeskparser.config as config
from bibdeskparser import Entry, FormatConversionWarning, Library
from bibdeskparser.plain import PlainOptions, format_marker, parse_marker

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the process-global configuration around every test."""
    config.active.reset()
    yield
    config.active.reset()


@pytest.fixture
def refs(tmp_path):
    """A copy of `refs.bib` in `tmp_path`, as a `Library`."""
    shutil.copy(REFS_BIB, tmp_path / "refs.bib")
    return Library(tmp_path / "refs.bib")


@pytest.fixture
def paper(refs, tmp_path):
    """`paper.bib`: a fresh export of two entries from `refs`."""
    path = tmp_path / "paper.bib"
    refs.export("GrondPRA2009a", "Evans1983", outfile=path)
    return path


def _write(tmp_path, text, name="plain.bib"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# -- the marker line ------------------------------------------------------ #


def test_marker_roundtrip():
    """`format_marker` and `parse_marker` are inverses for every
    option combination."""
    for unicode_ in (True, False):
        for expand in (True, False):
            for preprint in ("unpublished", "misc", "article", "stored"):
                options = PlainOptions(unicode_, expand, preprint)
                assert parse_marker(format_marker(options)) == options


def test_marker_text():
    assert format_marker(PlainOptions(True, False, "unpublished")) == (
        "%% Created by BibDeskParser (unicode, preprints as unpublished)."
    )
    assert format_marker(PlainOptions(False, True, "misc")) == (
        "%% Created by BibDeskParser "
        "(TeX-encoded, strings expanded, preprints as misc)."
    )


def test_marker_parse_case_insensitive():
    options = parse_marker(
        "%% created by bibdeskparser (TEX-ENCODED, Preprints as Article)."
    )
    assert options == PlainOptions(False, False, "article")


def test_marker_parse_rejects_unknown():
    """Anything outside the fixed vocabulary disqualifies the
    marker."""
    assert parse_marker("%% Created by BibDeskParser (unicode, x).") is None
    assert (
        parse_marker("%% Created by BibDeskParser (preprints as bogus).")
        is None
    )
    assert parse_marker("% a plain comment") is None
    assert parse_marker("%% Created by BibDesk (unicode).") is None


def test_marker_parse_defaults():
    """Options not named in the marker take their defaults."""
    options = parse_marker("%% Created by BibDeskParser (unicode).")
    assert options == PlainOptions(True, False, "unpublished")


# -- format detection ------------------------------------------------------ #


def test_database_file_not_plain(refs):
    assert not refs._plain


def test_from_scratch_not_plain():
    assert not Library()._plain


def test_exported_file_is_plain(paper):
    lib = Library(paper)
    assert lib._plain
    assert lib._plain_options == PlainOptions(True, False, "unpublished")


def test_groups_comment_marks_database(tmp_path):
    """A BibDesk group `@comment` block marks the database format,
    even without a header."""
    from bibdeskparser.groups import render_static_groups

    groups_comment = render_static_groups({"G": ("k1",)})
    path = _write(
        tmp_path,
        "@article{k1,\n    Title = {T},\n    Year = {2024},\n}\n"
        "\n"
        f"@comment{{{groups_comment}}}\n",
    )
    assert not Library(path)._plain


def test_bdsk_field_marks_database(tmp_path):
    """Any `bdsk-*` field marks the database format, regardless of
    whether the value is binary attachment data or a plain URL."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "    Bdsk-Url-1 = {https://example.com},\n"
        "}\n",
    )
    assert not Library(path)._plain


def test_dates_are_not_database_markers(tmp_path):
    """`date-added`/`date-modified` do not mark the database format
    (an entry pasted from a database is legitimate plain content)."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Date-Added = {2024-01-01 10:00:00 +0000},\n"
        "    Date-Modified = {2024-01-02 10:00:00 +0000},\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    assert Library(path)._plain


def test_marker_contradicted_by_database_content(tmp_path, refs):
    """Database markers win over a marker line, with a warning."""
    text = format_marker(PlainOptions(True, False, "unpublished")) + (
        "\n\n@article{k1,\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "    Bdsk-Url-1 = {https://example.com},\n"
        "}\n"
    )
    path = _write(tmp_path, text)
    with pytest.warns(UserWarning, match="treating it as a BibDesk database"):
        lib = Library(path)
    assert not lib._plain


# -- option heuristics (marker-less files) --------------------------------- #


def test_heuristic_encoding_ascii_is_tex(tmp_path):
    """An all-ASCII file is detected as TeX-encoded (the safe choice
    for the first non-ASCII value written to it)."""
    path = _write(
        tmp_path, "@article{k1,\n    Title = {T},\n    Year = {2024},\n}\n"
    )
    lib = Library(path)
    assert lib._plain_options.unicode is False


def test_heuristic_encoding_unicode(tmp_path):
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Author = {Grün, Anna},\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    lib = Library(path)
    assert lib._plain_options.unicode is True


def test_heuristic_encoding_ignores_url(tmp_path):
    """Non-ASCII text in a URL field does not make the file Unicode
    (URL fields are exempt from TeX encoding in either format)."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Title = {T},\n"
        "    Url = {https://example.com/münchen},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    lib = Library(path)
    assert lib._plain_options.unicode is False


def test_heuristic_strings_expanded(tmp_path):
    """A file with no macro usage at all is treated as expanded."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Journal = {Phys. Rev. A},\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    assert Library(path)._plain_options.expand_strings is True


def test_heuristic_strings_bare_month_counts_as_macro_usage(tmp_path):
    """A bare month reference marks the file as using macros, even
    though the month macros never come with a definition."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Journal = {Phys. Rev. A},\n"
        "    Month = jan,\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    assert Library(path)._plain_options.expand_strings is False


def test_heuristic_strings_definition_counts_as_macro_usage(tmp_path):
    path = _write(
        tmp_path,
        "@string{pra = {Phys. Rev. A}}\n"
        "\n"
        "@article{k1,\n"
        "    Journal = pra,\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    assert Library(path)._plain_options.expand_strings is False


def test_heuristic_preprint_form(tmp_path):
    """The stored type of the file's preprint-only entries sets the
    preprint form; mixed or absent falls back to the configuration."""
    preprint_fields = (
        "    Author = {Doe, Jane},\n"
        "    Eprint = {2003.10132},\n"
        "    Archiveprefix = {arXiv},\n"
        "    Title = {T},\n"
        "    Year = {2020},\n"
    )
    path = _write(
        tmp_path, "@misc{k1,\n" + preprint_fields + "}\n", "misc.bib"
    )
    assert Library(path)._plain_options.preprint == "misc"
    path = _write(
        tmp_path, "@unpublished{k1,\n" + preprint_fields + "}\n", "unp.bib"
    )
    assert Library(path)._plain_options.preprint == "unpublished"
    mixed = (
        "@misc{k1,\n"
        + preprint_fields
        + "}\n\n@unpublished{k2,\n"
        + preprint_fields.replace("k1", "k2")
        + "}\n"
    )
    path = _write(tmp_path, mixed, "mixed.bib")
    assert Library(path)._plain_options.preprint == "unpublished"  # config
    path = _write(
        tmp_path,
        "@article{k1,\n    Title = {T},\n    Year = {2024},\n}\n",
        "none.bib",
    )
    # constructing a Library re-discovers the configuration, so the
    # configured fallback must come from a config file
    (tmp_path / "bibdeskparser.toml").write_text(
        'preprint_export = "article"\n', encoding="utf-8"
    )
    assert Library(path)._plain_options.preprint == "article"


def test_marker_overrides_heuristics(tmp_path):
    """A marker pins the options even where the heuristics would
    decide otherwise (here: an all-ASCII file declared Unicode)."""
    path = _write(
        tmp_path,
        "%% Created by BibDeskParser (unicode, preprints as misc).\n"
        "\n"
        "@article{k1,\n    Title = {T},\n    Year = {2024},\n}\n",
    )
    assert Library(path)._plain_options == PlainOptions(True, False, "misc")


# -- saving in the plain format -------------------------------------------- #


def test_export_save_roundtrip(paper):
    """A file created by `export` round-trips byte-identically through
    load and save."""
    before = paper.read_text(encoding="utf-8")
    Library(paper).save()
    assert paper.read_text(encoding="utf-8") == before


def test_plain_save_no_header_no_dates(paper):
    """A modification does not synthesize a header and does not stamp
    date fields."""
    lib = Library(paper)
    lib["Evans1983"]["note"] = "Lecture notes"
    lib.save()
    text = paper.read_text(encoding="utf-8")
    assert "BibDesk" not in text.replace("BibDeskParser", "")
    assert "Date-Added" not in text
    assert "Date-Modified" not in text
    assert "    Note = {Lecture notes},\n" in text


def test_plain_save_dirty_entry_reordered(paper):
    """A modified entry is written in BibDesk's field order; untouched
    entries keep their stored order."""
    lib = Library(paper)
    lib["Evans1983"]["note"] = "Lecture notes"
    lib.save()
    text = paper.read_text(encoding="utf-8")
    assert text.index("Author = {Evans") < text.index("Note =")
    assert text.index("Note =") < text.index("Title = {An Introduction")


def test_plain_touch_updates_existing_dates(tmp_path):
    """An entry that already stores date fields (pasted from a
    database) keeps `date-added` and gets `date-modified` updated."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Date-Added = {2020-01-01 10:00:00 +0000},\n"
        "    Date-Modified = {2020-01-02 10:00:00 +0000},\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    lib = Library(path)
    lib["k1"]["note"] = "N"
    lib.save()
    text = path.read_text(encoding="utf-8")
    assert "Date-Added = {2020-01-01 10:00:00 +0000}" in text
    assert "Date-Modified = {2020-01-02 10:00:00 +0000}" not in text
    assert "Date-Modified = " in text


def test_plain_save_set_string(paper):
    """`set_string`-style mutations keep the file plain; the new
    definition is written in place."""
    lib = Library(paper)
    lib.strings["jpb"] = "J. Phys. B"
    lib.save()
    text = paper.read_text(encoding="utf-8")
    assert "@string{jpb = {J. Phys. B}}" in text
    assert Library(paper)._plain


def test_plain_save_delete_and_rekey(paper):
    lib = Library(paper)
    del lib["GrondPRA2009a"]
    lib.rekey("Evans1983", "Evans1983notes")
    lib.save()
    text = paper.read_text(encoding="utf-8")
    assert "GrondPRA2009a" not in text
    assert "@unpublished{Evans1983notes,\n" in text
    assert "Date-Added" not in text
    assert Library(paper)._plain


def test_plain_save_tex_encoding(tmp_path):
    """A TeX-encoded plain file gets new non-ASCII values TeX-encoded
    on save."""
    path = _write(
        tmp_path, "@article{k1,\n    Title = {T},\n    Year = {2024},\n}\n"
    )
    lib = Library(path)
    lib["k1"]["author"] = "Grün, Anna"
    lib.save()
    text = path.read_text(encoding="utf-8")
    assert 'Gr{\\"u}n' in text
    assert "Grün" not in text


def test_plain_save_relayouts_handwritten_file(tmp_path):
    """A hand-written plain file is re-laid out into the export layout
    on save (never losing fields), keeping its comments."""
    path = _write(
        tmp_path,
        "% my references\n"
        "\n"
        "@article{k1,\n"
        "  year    = {2024},\n"
        '  title   = "T",\n'
        "}\n",
    )
    lib = Library(path)
    lib.save()
    assert path.read_text(encoding="utf-8") == (
        "% my references\n"
        "\n"
        "@article{k1,\n"
        "    Year = {2024},\n"
        "    Title = {T},\n"
        "}\n"
    )


def test_plain_save_expand_strings(tmp_path):
    """In a macro-free (expanded) file, a macro-shaped value written
    by `set_field` is inlined on save once the macro is defined."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        "    Journal = {Phys. Rev. A},\n"
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
    )
    lib = Library(path)
    assert lib._plain_options.expand_strings is True
    lib.strings["prl"] = "Phys. Rev. Lett."
    lib["k1"]["journal"] = "prl"
    lib.save()
    text = path.read_text(encoding="utf-8")
    assert "Journal = {Phys. Rev. Lett.}" in text


def test_import_into_plain_file_stays_plain(paper, refs):
    """`import_bibtex` into a plain file keeps it plain, and the
    imported entry gains no date fields."""
    lib = Library(paper)
    snippet = refs.export("Tannor2007", marker=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        keys = lib.import_bibtex(snippet)
    lib.save()
    assert keys == ["Tannor2007"]
    assert Library(paper)._plain
    text = paper.read_text(encoding="utf-8")
    assert "Date-Added" not in text
    assert "Date-Modified" not in text


# -- conversion to the database format -------------------------------------- #


def test_set_group_converts(paper):
    lib = Library(paper)
    with pytest.warns(FormatConversionWarning, match="static group 'Read'"):
        lib.groups["Read"] = ("Evans1983",)
    assert not lib._plain
    lib.save()
    text = paper.read_text(encoding="utf-8")
    assert text.startswith(
        "%% This BibTeX bibliography file was created using BibDesk"
    )
    assert "BibDesk Static Groups" in text
    assert not Library(paper)._plain


def test_add_url_converts(paper):
    lib = Library(paper)
    with pytest.warns(FormatConversionWarning, match="URL linked"):
        lib.add_url("Evans1983", "https://example.com/notes.pdf")
    assert not lib._plain


def test_add_file_converts(paper, tmp_path):
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4 fake")
    lib = Library(paper)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        lib.add_file("Evans1983", "notes.pdf")
    assert any(issubclass(w.category, FormatConversionWarning) for w in caught)
    assert not lib._plain


def test_conversion_reenables_date_stamping(paper):
    """After the conversion, mutations stamp date fields again."""
    lib = Library(paper)
    with pytest.warns(FormatConversionWarning):
        lib.groups["Read"] = ()
    lib["Evans1983"]["note"] = "N"
    lib.save()
    text = paper.read_text(encoding="utf-8")
    assert "date-modified" in text.lower()


def test_invalid_url_does_not_convert(paper):
    lib = Library(paper)
    with pytest.raises(ValueError):
        lib.add_url("Evans1983", "not a url")
    assert lib._plain


def test_save_converts_on_imported_bdsk_fields(paper, refs):
    """Entries that gained `bdsk-*` fields outside `add_file`/`add_url`
    (e.g. through `import`) convert the library at save time."""
    shutil.copy(REFS_BIB.parent / "GoerzQ2022.pdf", paper.parent)
    lib = Library(paper)
    snippet = refs.export("GoerzQ2022", fields="full", marker=False)
    assert "Bdsk-File-1" in snippet
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lib.import_bibtex(snippet)
    with pytest.warns(FormatConversionWarning, match="file attachments"):
        lib.save()
    assert not Library(paper)._plain


# -- Library.export(update=...) --------------------------------------------- #


def test_update_refreshes_from_library(paper, refs):
    """Corrections in the library propagate into the exported file,
    overwriting local edits to entries the library knows."""
    plain = Library(paper)
    plain["Evans1983"]["note"] = "local note"
    plain.save()
    refs.strings["pra"] = "Physical Review A"
    refs.export(update=paper)
    text = paper.read_text(encoding="utf-8")
    assert "@string{pra = {Physical Review A}}" in text
    assert "local note" not in text


def test_update_appends_new_key(paper, refs):
    refs.export("GoerzQ2022", update=paper)
    text = paper.read_text(encoding="utf-8")
    assert "@article{GoerzQ2022,\n" in text
    assert text.index("GoerzQ2022") > text.index("Evans1983")
    assert "@string{quant = {Quantum}}" in text
    # existing entries were left in place
    assert "@article{GrondPRA2009a,\n" in text


def test_update_with_keys_only_touches_those(paper, refs):
    plain = Library(paper)
    plain["Evans1983"]["note"] = "local note"
    plain.save()
    refs.export("GrondPRA2009a", update=paper)
    text = paper.read_text(encoding="utf-8")
    assert "local note" in text  # Evans1983 was not named


def test_update_never_removes(paper, refs):
    """An entry deleted from the library (or hand-written) stays in
    the file, and unused `@string` definitions are kept."""
    plain = Library(paper)
    plain.strings["unused"] = "Unused Journal"
    plain.save()
    handwritten = (
        "@article{Colleague2024,\n"
        "    Author = {Colleague, A.},\n"
        "    Title = {Handwritten},\n"
        "    Year = {2024},\n"
        "}\n"
    )
    paper.write_text(
        paper.read_text(encoding="utf-8") + "\n" + handwritten,
        encoding="utf-8",
    )
    refs.export(update=paper)
    text = paper.read_text(encoding="utf-8")
    assert "@article{Colleague2024,\n" in text
    assert "Handwritten" in text
    assert "@string{unused = {Unused Journal}}" in text


def test_update_unknown_key_rejected(paper, refs):
    with pytest.raises(KeyError, match="NoSuchKey"):
        refs.export("NoSuchKey", update=paper)


def test_update_requires_existing_file(refs, tmp_path):
    with pytest.raises(FileNotFoundError, match="outfile"):
        refs.export("Evans1983", update=tmp_path / "missing.bib")


def test_update_refuses_database_target(refs, tmp_path):
    target = tmp_path / "db.bib"
    shutil.copy(REFS_BIB, target)
    with pytest.raises(ValueError, match="a BibDesk header"):
        refs.export(update=target)


def test_update_outfile_mutually_exclusive(paper, refs, tmp_path):
    with pytest.raises(ValueError, match="not both"):
        refs.export("Evans1983", update=paper, outfile=tmp_path / "out.bib")


def test_update_never_writes_bdsk_fields(paper, refs):
    """Even a full-fields update of an entry with attachments writes
    no `bdsk-*` fields (a plain target cannot represent them)."""
    refs.export("GoerzQ2022", fields="full", update=paper)
    text = paper.read_text(encoding="utf-8")
    assert "@article{GoerzQ2022,\n" in text
    assert "Abstract" in text  # full fields
    assert "Bdsk-" not in text
    assert Library(paper)._plain


def test_update_explicit_override_rewrites_marker(paper, refs):
    """An explicit option override is recorded in the marker, so it is
    sticky for subsequent updates."""
    refs.export("GoerzQ2022", update=paper, unicode=False)
    text = paper.read_text(encoding="utf-8")
    assert text.startswith(
        "%% Created by BibDeskParser "
        "(TeX-encoded, preprints as unpublished).\n"
    )
    assert "Sebasti{\\'a}n" in text  # re-encoded
    assert "Sebastián" not in text
    # a subsequent update keeps the recorded encoding
    refs.export(update=paper)
    assert Library(paper)._plain_options.unicode is False


def test_update_adds_marker_to_markerless_file(refs, tmp_path):
    path = _write(
        tmp_path,
        "@article{GrondPRA2009a,\n"
        "    Author = {Grond, Julian},\n"
        "    Title = {Optimizing},\n"
        "    Year = {2009},\n"
        "}\n",
        "paper.bib",
    )
    refs.export(update=path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("%% Created by BibDeskParser ")


def test_update_no_marker_leaves_state_untouched(refs, tmp_path):
    """`marker=False` neither adds a marker to a marker-less file nor
    rewrites an existing one."""
    path = _write(
        tmp_path,
        "@article{GrondPRA2009a,\n"
        "    Author = {Grond, Julian},\n"
        "    Title = {Optimizing},\n"
        "    Year = {2009},\n"
        "}\n",
        "paper.bib",
    )
    refs.export(update=path, marker=False)
    assert "BibDeskParser" not in path.read_text(encoding="utf-8")


def test_update_roundtrip_idempotent(paper, refs):
    """Updating a freshly exported file is byte-identical."""
    before = paper.read_text(encoding="utf-8")
    refs.export(update=paper)
    assert paper.read_text(encoding="utf-8") == before


def test_update_string_only_in_file_kept(paper, refs):
    """A macro only the file defines keeps its value; a macro the
    library also defines gets the library's value."""
    plain = Library(paper)
    plain.strings["local"] = "Local Journal"
    plain.save()
    refs.export(update=paper)
    text = paper.read_text(encoding="utf-8")
    assert "@string{local = {Local Journal}}" in text
    assert "@string{pra = {Phys. Rev. A}}" in text


def test_entry_added_to_plain_library_gets_no_new_dates(paper):
    """A detached entry carries no date fields, and adding it to a
    plain library never creates them."""
    lib = Library(paper)
    entry = Entry("article", "New2026", fields={"title": "T"})
    assert entry.date_added is None
    assert entry.date_modified is None
    lib["New2026"] = entry
    entry["year"] = "2026"
    assert entry.date_added is None
    assert entry.date_modified is None
    lib.save()
    assert "Date-" not in paper.read_text(encoding="utf-8")


# -- @preamble blocks -------------------------------------------------------


PREAMBLE_BIB = (
    '@preamble{"\\newcommand{\\noopsort}[1]{}"}\n'
    "\n"
    "@article{k1,\n"
    "    Title = {T},\n"
    "    Year = {2024},\n"
    "}\n"
)


def test_plain_save_preserves_preamble(tmp_path):
    """A `@preamble` block in a plain file survives a save (verbatim),
    for a pristine and for a modified library."""
    path = _write(tmp_path, PREAMBLE_BIB)
    lib = Library(path)
    assert lib._plain
    lib.save()
    assert path.read_text(encoding="utf-8") == PREAMBLE_BIB
    lib["k1"]["note"] = "N"
    lib.save()
    text = path.read_text(encoding="utf-8")
    assert text.startswith('@preamble{"\\newcommand{\\noopsort}[1]{}"}\n')
    assert "Note = {N}," in text


def test_update_preserves_preamble(tmp_path, refs):
    """`export --update` keeps a `@preamble` block in the target."""
    path = _write(tmp_path, PREAMBLE_BIB, "paper.bib")
    refs.export("Evans1983", update=path)
    text = path.read_text(encoding="utf-8")
    assert '@preamble{"\\newcommand{\\noopsort}[1]{}"}' in text
    assert "@unpublished{Evans1983,\n" in text


def test_converted_save_preserves_preamble(tmp_path):
    """Converting a plain file with a `@preamble` to the database
    format keeps the block in the database-format output."""
    path = _write(tmp_path, PREAMBLE_BIB)
    lib = Library(path)
    with pytest.warns(FormatConversionWarning):
        lib.groups["G"] = ("k1",)
    lib.save()
    text = path.read_text(encoding="utf-8")
    assert text.startswith(
        "%% This BibTeX bibliography file was created using BibDesk"
    )
    assert '@preamble{"\\newcommand{\\noopsort}[1]{}"}' in text


# -- review follow-ups ------------------------------------------------------


def test_export_requires_keys(refs):
    """`Library.export()` without keys and without `update` raises."""
    with pytest.raises(ValueError, match="at least one citation key"):
        refs.export()


def test_update_with_field_list(paper, refs):
    """An explicit field list applies to the entries an update
    rewrites."""
    refs.export("GoerzQ2022", update=paper, fields=["title", "year"])
    text = paper.read_text(encoding="utf-8")
    assert "@article{GoerzQ2022,\n" in text
    assert "Title = {Quantum Optimal Control" in text
    assert "Doi" not in text.split("GoerzQ2022")[1]


def test_update_tex_encoded_stable(tmp_path, refs):
    """Updating a TeX-encoded, marker-less target re-encodes values
    as TeX, and repeated updates are byte-stable."""
    path = _write(
        tmp_path,
        "@article{k1,\n"
        '    Author = {Gr{\\"u}n, Anna},\n'
        "    Title = {T},\n"
        "    Year = {2024},\n"
        "}\n",
        "paper.bib",
    )
    refs.export("GoerzQ2022", update=path)
    first = path.read_text(encoding="utf-8")
    # a macro-free all-ASCII target detects as TeX-encoded with
    # expanded strings; both are recorded in the marker
    assert first.startswith(
        "%% Created by BibDeskParser "
        "(TeX-encoded, strings expanded, preprints as unpublished).\n"
    )
    assert "Sebasti{\\'a}n" in first  # written TeX-encoded
    assert "Journal = {Quantum}," in first  # macro inlined
    assert 'Gr{\\"u}n' in first  # kept entry re-encodes stably
    refs.export(update=path)
    assert path.read_text(encoding="utf-8") == first
