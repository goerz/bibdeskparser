"""Tests for `bibdeskparser.specifiers` (the format-specifier
language, in both the cite-key and the file-name context)."""

import warnings

import pytest

from bibdeskparser import specifiers
from bibdeskparser.entry import Entry
from bibdeskparser.specifiers import (
    compile_format,
    missing_required_fields,
    render_format,
    required_fields,
)


def _entry(**fields):
    """An `article` test entry with the given fields (suppressing
    field-appropriateness warnings)."""
    return _typed_entry("article", **fields)


def _typed_entry(entry_type, **fields):
    """A test entry of the given type (suppressing field-appropriateness
    warnings)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Entry(entry_type, "temp", fields)


@pytest.fixture(name="entry")
def fixture_entry():
    """A prototypical article entry."""
    return _entry(
        author=(
            "Goerz, Michael H. and Halperin, Eli J. and Aytac, Jon M. "
            "and Koch, Christiane P. and Whaley, K. Birgitta"
        ),
        title=(
            "Robustness of high-fidelity {Rydberg} gates with "
            "single-site addressability"
        ),
        journal="Phys. Rev. A",
        volume="90",
        pages="032329",
        year="2014",
        month="aug",
        doi="10.1103/PhysRevA.90.032329",
    )


def _gen(entry, format_string, **kwargs):
    """Compile and render `format_string` for `entry`."""
    return render_format(compile_format(format_string), entry, **kwargs)


# -- validation (compile_format) --------------------------------------- #


def test_invalid_specifier():
    with pytest.raises(ValueError, match="invalid specifier %x"):
        compile_format("%a1%x")


def test_trailing_percent_raises():
    with pytest.raises(ValueError, match="empty specifier"):
        compile_format("%a1%")


def test_percent_escape_is_invalid_for_keys():
    """`%%` would put a literal `%` in the key, which is not a valid
    cite-key character."""
    with pytest.raises(ValueError, match="invalid escape specifier"):
        compile_format("%a1%%%Y")


def test_local_file_specifiers_rejected():
    """`%l`/`%L`/`%e`/`%E` exist only for AutoFile file names."""
    for char in "lLeE":
        with pytest.raises(ValueError, match="local files"):
            compile_format(f"%{char}%n0")


def test_document_info_not_implemented():
    """`%i` is recognized, but bibdeskparser does not model BibDesk's
    document info."""
    with pytest.raises(NotImplementedError, match="%i"):
        compile_format("%a1%i{Project}%Y")


def test_second_unique_specifier_rejected():
    with pytest.raises(ValueError, match="only once"):
        compile_format("%a1%u0%Y%n0")


def test_missing_field_argument():
    for char in "fwcs":
        with pytest.raises(ValueError, match=r"followed by a \{Field\} name"):
            compile_format(f"%{char}")
        with pytest.raises(ValueError, match=r"followed by a \{Field\} name"):
            compile_format(f"%{char}{{journal")


def test_missing_closing_bracket():
    with pytest.raises(ValueError, match=r"missing '\]'"):
        compile_format("%a[-")


def test_invalid_escape_in_opt_arg():
    with pytest.raises(ValueError, match="invalid escape specifier"):
        compile_format("%a[%%]1")


@pytest.mark.xfail(
    raises=NotImplementedError,
    reason="%i requires modeling BibDesk's @bibdesk_info block",
    strict=True,
)
def test_document_info_rendering():
    """Rendering `%i{Key}` should insert the document-info value once
    document info is supported."""
    fmt = compile_format("%a1-%i{Project}")
    entry = _entry(author="Goerz, Michael H.")
    # the document_info argument does not exist yet
    # pylint: disable-next=unexpected-keyword-arg
    key = render_format(fmt, entry, document_info={"Project": "qdyn"})
    assert key == "Goerz-qdyn"


# -- literal text and escapes ------------------------------------------ #


def test_literal_text_and_escapes(entry):
    assert _gen(entry, "bib-%Y%1%[%]%-x") == "bib-20141[]-x"


def test_literal_text_is_sanitized(entry):
    """Invalid cite-key characters in literal format text are
    dropped, whitespace becomes `-`."""
    assert _gen(entry, "a b(c)%Y") == "a-bc2014"


# -- author specifiers -------------------------------------------------- #


def test_authors_default(entry):
    assert _gen(entry, "%a") == "GoerzHalperinAytacKochWhaley"


def test_first_author(entry):
    assert _gen(entry, "%a1") == "Goerz"


def test_authors_count_and_chars(entry):
    assert _gen(entry, "%a33") == "GoeHalAyt"


def test_authors_from_end(entry):
    assert _gen(entry, "%a-1") == "Whaley"


def test_authors_separator_and_etal(entry):
    assert _gen(entry, "%a[+][-etal]2") == "Goerz+Halperin-etal"


def test_authors_etal_trailing_digit(entry):
    """An unescaped trailing digit in the `[etal]` argument lowers
    the number of names (BibDesk quirk)."""
    assert _gen(entry, "%a[+][X1]3") == "GoerzX"


def test_authors_etal_trailing_digit_no_separator(entry):
    """The trailing etal digit reduces the requested count even with an
    empty separator (the `%a[][X1]2` example from the docs)."""
    assert _gen(entry, "%a[][X1]2") == "GoerzX"


def test_authors_or_editors():
    entry = _entry(editor="Smith, John", title="T")
    assert _gen(entry, "%p1") == "Smith"
    assert _gen(entry, "%a1x") == "x"  # %a never falls back to editor


def test_authors_with_initials(entry):
    assert _gen(entry, "%A2") == "Goerz.M;Halperin.E"


def test_authors_with_initials_custom_separators(entry):
    assert _gen(entry, "%A[-][][]2") == "GoerzM-HalperinE"


def test_author_names_sanitized():
    entry = _entry(author='M{\\"u}ller, Klaus and Gro{\\ss}, Peter')
    assert _gen(entry, "%a") == "MullerGross"


# -- title specifiers --------------------------------------------------- #


def test_title(entry):
    assert _gen(entry, "%t10") == "Robustness"


def test_title_braces_removed(entry):
    assert _gen(entry, "%t").startswith(
        "Robustness-of-high-fidelity-Rydberg-gates"
    )


def test_title_words(entry):
    """`%T` counts only words longer than the small-word length (3 by
    default), but includes the short words in between."""
    assert _gen(entry, "%T2") == "Robustness-of-high-fidelity"


def test_title_words_skipping_small(entry):
    """With a `[small word length]`, short words are skipped and do
    not count."""
    assert _gen(entry, "%T[3]2") == "Robustness-high-fidelity"


# -- date specifiers ----------------------------------------------------- #


def test_year(entry):
    assert _gen(entry, "%Y") == "2014"
    assert _gen(entry, "%y") == "14"


def test_two_digit_year():
    assert _gen(_entry(year="97", title="T"), "%Y") == "1997"
    assert _gen(_entry(year="14", title="T"), "%Y") == "2014"


def test_month_from_macro(entry):
    assert _gen(entry, "%m") == "08"


def test_month_variants():
    assert _gen(_entry(month="September", title="T"), "%m") == "09"
    assert _gen(_entry(month="11", title="T"), "%m") == "11"
    assert _gen(_entry(month="bogus", title="T"), "%m") == "01"
    # a missing month renders nothing, and an all-empty result falls
    # back to a numbered key
    assert _gen(_entry(title="T"), "%m") == "1"


# -- field specifiers ---------------------------------------------------- #


def test_field(entry):
    assert _gen(entry, "%f{volume}") == "90"


def test_field_truncated(entry):
    assert _gen(entry, "%f{journal}5") == "Phys."


def test_field_slash_replacement(entry):
    assert _gen(entry, "%f{doi}[_]") == "10.1103_PhysRevA.90.032329"


def test_field_macro_expansion():
    """A bare `@string` macro reference is expanded via `strings`."""
    entry = _entry(journal="pra", title="T")
    strings = {"pra": "Phys. Rev. A"}
    assert _gen(entry, "%f{journal}", strings=strings) == "Phys.-Rev.-A"
    assert _gen(entry, "%f{journal}") == "pra"


def test_field_cite_key(entry):
    assert _gen(entry, "%f{Cite Key}", current_key="Old") == "Old"


def test_field_bibtex_type(entry):
    assert _gen(entry, "%f{BibTeX Type}") == "article"


def test_field_words(entry):
    assert _gen(entry, "%w{doi}[./][-][_]2") == "10_1103"


def test_boolean_field():
    entry = _entry(title="T")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entry["published"] = "yes"
    assert _gen(entry, "%s{published}[P][U]") == "P"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entry["published"] = "no"
    assert _gen(entry, "%s{published}[P][U]") == "U"


def test_boolean_field_draft():
    """The `%s{Draft}[D][F]` example from the docs: `D` for a `yes`
    value, `F` otherwise."""
    entry = _entry(title="T")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entry["draft"] = "yes"
    assert _gen(entry, "%s{Draft}[D][F]") == "D"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entry["draft"] = "no"
    assert _gen(entry, "%s{Draft}[D][F]") == "F"


def test_keywords():
    entry = _entry(title="T")
    entry._set_keywords(  # pylint: disable=protected-access
        ("quantum control", "rydberg")
    )
    assert _gen(entry, "%k[-][_]") == "quantum-control_rydberg"
    assert _gen(entry, "%k[-][_]1") == "quantum-control"


def test_document_name(entry):
    assert _gen(entry, "%b-%Y", document_name="refs") == "refs-2014"
    assert _gen(entry, "%b-%Y") == "-2014"


# -- acronyms and the initials mapping ----------------------------------- #


def test_acronym(entry):
    """`%c{journal}0` gives the getbibtex-style journal initials."""
    assert _gen(entry, "%c{journal}0") == "PRA"


def test_acronym_small_word_length(entry):
    """The default ignores words of up to 3 characters, but words
    ending in `.` always count."""
    assert _gen(entry, "%c{journal}") == "PR"
    entry_njp = _entry(journal="New J. Phys.", title="T")
    assert _gen(entry_njp, "%c{journal}0") == "NJP"


def test_initials_mapping():
    """The `[initials]` config mapping overrides the acronym, both by
    full value and by macro name."""
    initials = {"journal": {"npj Quantum Inf": "NPJQI"}}
    entry = _entry(journal="npj Quantum Inf", title="T")
    assert _gen(entry, "%c{journal}0") == "NQI"
    assert _gen(entry, "%c{journal}0", initials=initials) == "NPJQI"
    macro_entry = _entry(journal="npjqi", title="T")
    strings = {"npjqi": "npj Quantum Inf"}
    assert (
        _gen(
            macro_entry,
            "%c{journal}0",
            strings=strings,
            initials=initials,
        )
        == "NPJQI"
    )
    by_macro_name = {"journal": {"npjqi": "NPJQI"}}
    assert (
        _gen(
            macro_entry,
            "%c{journal}0",
            strings=strings,
            initials=by_macro_name,
        )
        == "NPJQI"
    )


# -- container virtual field ---------------------------------------------- #


def test_container_resolves_by_type():
    """The virtual `container` field maps to the type's venue field."""
    article = _typed_entry("article", journal="Phys. Rev. A", title="T")
    inproc = _typed_entry(
        "inproceedings", booktitle="Proc. of Something", title="T"
    )
    book = _typed_entry("book", series="Lecture Notes", title="T")
    assert _gen(article, "%f{container}") == "Phys.-Rev.-A"
    assert _gen(inproc, "%f{container}") == "Proc.-of-Something"
    assert _gen(book, "%f{container}") == "Lecture-Notes"


def test_container_acronym_by_type():
    """`%c{container}` acronyms the type-appropriate venue field."""
    article = _typed_entry("article", journal="Phys. Rev. A", title="T")
    inproc = _typed_entry("inproceedings", booktitle="New J. Phys.", title="T")
    assert _gen(article, "%c{container}0") == "PRA"
    assert _gen(inproc, "%c{container}0") == "NJP"


def test_container_empty_for_typeless():
    """A type with no container (e.g. `@misc`) renders `container` as
    empty, so a cross-type format stays usable."""
    misc = _typed_entry("misc", author="Doe, J", title="T", year="2020")
    # container contributes nothing, but the rest of the key still forms
    assert _gen(misc, "%a1%c{container}0%Y") == "Doe2020"


def test_container_initials_by_concrete_field():
    """The `[initials]` table for `%c{container}` is keyed by the
    concrete field (booktitle for inproceedings)."""
    inproc = _typed_entry(
        "inproceedings",
        booktitle="Proc. SPIE 11700, Optical and Quantum Sensing",
        title="T",
    )
    initials = {
        "booktitle": {"Proc. SPIE 11700, Optical and Quantum Sensing": "SPIE"}
    }
    assert _gen(inproc, "%c{container}0", initials=initials) == "SPIE"


def test_container_required_field_by_type():
    """`container` is required only when the entry type has a container
    field; it never blocks a type that has none."""
    fmt = compile_format("%a1%c{container}0%Y%u0")
    article = _typed_entry("article", author="Doe, J", title="T", year="2020")
    # the article has no journal, so its container requirement is unmet
    assert missing_required_fields(fmt, article) == ["container"]
    complete = _typed_entry(
        "inproceedings",
        author="Doe, J",
        title="T",
        booktitle="Proc.",
        year="2020",
    )
    assert missing_required_fields(fmt, complete) == []
    misc = _typed_entry("misc", author="Doe, J", title="T", year="2020")
    assert missing_required_fields(fmt, misc) == []


def test_required_fields_deduplicated():
    """A requirement referenced multiple times appears only once, in
    first-seen order."""
    fmt = compile_format("%a%a%Y%c{journal}0%c{journal}0")
    assert required_fields(fmt) == ["author", "year", "journal"]
    incomplete = _typed_entry("article", year="2020")
    assert missing_required_fields(fmt, incomplete) == ["author", "journal"]


# -- random specifiers ---------------------------------------------------- #


def test_random_specifiers(entry):
    specifiers._RNG.seed(42)  # pylint: disable=protected-access
    key = _gen(entry, "%r2%R2%d2")
    assert len(key) == 6
    assert key[0:2].islower()
    assert key[2:4].isupper()
    assert key[4:6].isdigit()


# -- unique specifiers ------------------------------------------------------ #


def test_unique_grows_only_as_needed(entry):
    taken = set()
    for expected in ("Goerz2014", "Goerz2014a", "Goerz2014b"):
        key = _gen(entry, "%a1%Y%u0", is_free=lambda k: k not in taken)
        assert key == expected
        taken.add(key)


def test_unique_fixed_count(entry):
    taken = {"Goerz:2014aa"}
    assert _gen(entry, "%a1:%Y%u2") == "Goerz:2014aa"
    assert (
        _gen(entry, "%a1:%Y%u2", is_free=lambda k: k not in taken)
        == "Goerz:2014ab"
    )


def test_unique_uppercase_and_numeric(entry):
    assert _gen(entry, "%a1%Y%U1") == "Goerz2014A"
    taken = {"Goerz2014"}
    assert (
        _gen(entry, "%a1%Y%n0", is_free=lambda k: k not in taken)
        == "Goerz20141"
    )


def test_numeric_suffix_skips_leading_zero(entry):
    """A grown numeric suffix continues 8, 9, 10 (not 00)."""
    taken = {"Goerz2014"} | {f"Goerz2014{i}" for i in range(1, 10)}
    assert (
        _gen(entry, "%a1%Y%n0", is_free=lambda k: k not in taken)
        == "Goerz201410"
    )


def test_unique_prefix_suffix(entry):
    """With count 0, `[prefix][suffix]` surround the unique characters
    once disambiguation becomes necessary."""
    taken = {"Goerz2014"}
    assert (
        _gen(
            entry,
            "%a1%Y%u[.][]0",
            is_free=lambda k: k not in taken,
        )
        == "Goerz2014.a"
    )


def test_unique_infix_between_base_and_end(entry):
    """The unique characters are inserted where the specifier occurs,
    not at the end."""
    taken = {"Goerz2014X"}
    assert (
        _gen(entry, "%a1%Y%u0X", is_free=lambda k: k not in taken)
        == "Goerz2014aX"
    )


def test_unique_hash_deterministic(entry):
    """`%u[Field]N` derives the unique characters from a hash of the
    field, so the same entry always gets the same key."""
    key1 = _gen(entry, "%a1:%Y%u[Title]2")
    key2 = _gen(entry, "%a1:%Y%u[Title]2")
    assert key1 == key2
    assert key1.startswith("Goerz:2014")
    assert len(key1) == len("Goerz:2014") + 2
    other = _entry(
        author="Goerz, Michael H.", title="Something Else", year="2014"
    )
    assert _gen(other, "%a1:%Y%u[Title]2") != key1


def test_unique_hash_doi(entry):
    key = _gen(entry, "%a1:%Y%u[Doi]2")
    assert key == _gen(entry, "%a1:%Y%u[Doi]2")


def test_lowercase(entry):
    assert _gen(entry, "%a1%c{journal}0%Y", lowercase=True) == ("goerzpra2014")


def test_lowercase_downgrades_uppercase_unique(entry):
    assert _gen(entry, "%a1%Y%U1", lowercase=True) == "goerz2014a"


def test_empty_format_yields_numbered_key(entry):
    empty = _entry(title="T")
    assert _gen(empty, "%f{note}") == "1"
    taken = {"1"}
    assert _gen(empty, "%f{note}", is_free=lambda k: k not in taken) == "2"


# -- idempotent regeneration ---------------------------------------------- #


def test_current_key_matching_pattern_is_kept(entry):
    """Regenerating a key that already fits the format is a no-op,
    even if the unique characters differ from what generation would
    pick."""
    taken = {"GoerzPRA2014"}
    key = _gen(
        entry,
        "%a1%c{journal}0%Y%u0",
        current_key="GoerzPRA2014b",
        is_free=lambda k: k not in taken,
    )
    assert key == "GoerzPRA2014b"


def test_current_key_not_matching_is_replaced(entry):
    key = _gen(
        entry,
        "%a1%c{journal}0%Y%u0",
        current_key="SomethingElse",
    )
    assert key == "GoerzPRA2014"


# -- required fields -------------------------------------------------------- #


def test_required_fields():
    fmt = compile_format("%a1%c{journal}0%Y%m%t%k%u0")
    assert required_fields(fmt) == [
        "author",
        "journal",
        "year",
        "month",
        "title",
        "keywords",
    ]
    fmt = compile_format("%p1%f{Cite Key}%f{BibTeX Type}")
    assert required_fields(fmt) == ["author/editor"]
    fmt = compile_format("%a1%c{container}0%Y")
    assert required_fields(fmt) == ["author", "container", "year"]


def test_missing_required_fields(entry):
    fmt = compile_format("%a1%c{journal}0%Y%u0")
    assert missing_required_fields(fmt, entry) == []
    incomplete = _entry(author="Smith, John", title="T")
    assert missing_required_fields(fmt, incomplete) == [
        "journal",
        "year",
    ]
    editor_only = _entry(editor="Smith, John", title="T")
    fmt = compile_format("%p1%t")
    assert missing_required_fields(fmt, editor_only) == []
    fmt = compile_format("%a1%t")
    assert missing_required_fields(fmt, editor_only) == ["author"]


# -- file-name formats (the AutoFile context) ------------------------------ #


def _gen_file(entry, format_string, **kwargs):
    """Compile (in the file context) and render `format_string`."""
    return render_format(
        compile_format(format_string, context="file"), entry, **kwargs
    )


def test_invalid_context_rejected():
    with pytest.raises(ValueError, match="invalid format context"):
        compile_format("%n0", context="path")


def test_file_specifiers_accepted_in_file_context():
    for char in "lLeE":
        compile_format(f"%{char}%n0", context="file")


def test_file_format_requires_unique_specifier():
    with pytest.raises(ValueError, match="unique specifier"):
        compile_format("%l%e", context="file")
    with pytest.raises(ValueError, match="%u, %U, or %n"):
        compile_format("%f{Cite Key}.pdf", context="file")


def test_file_format_second_unique_specifier_rejected():
    with pytest.raises(ValueError, match="only once"):
        compile_format("%l%u0%n0%e", context="file")


def test_percent_escape_valid_in_file_context(entry):
    """A literal `%` is fine in a file name (unlike in a cite key)."""
    assert _gen_file(entry, "x%%y%n0") == "x%y"
    assert _gen_file(entry, "%a[%%]2%n0") == "Goerz%Halperin"


def test_old_filename_specifiers(entry):
    """`%l`/`%L`/`%e` insert the linked file's current name; `:` (the
    one invalid file-name character) is stripped, spaces are kept."""
    filename = "/some/dir/My Paper: v2.pdf"
    assert _gen_file(entry, "%l%n0", filename=filename) == "My Paper v2"
    assert _gen_file(entry, "%L%n0", filename=filename) == "My Paper v2.pdf"
    assert _gen_file(entry, "%l%n0%e", filename=filename) == (
        "My Paper v2.pdf"
    )


def test_extension_without_dot(entry):
    """`%E` inserts the extension without the leading dot, with an
    optional `[default]` for extensionless files."""
    assert _gen_file(entry, "x.%E%n0", filename="a/b.ps") == "x.ps"
    assert _gen_file(entry, "x.%E[pdf]%n0", filename="a/b.ps") == "x.ps"
    assert _gen_file(entry, "x.%E[pdf]%n0", filename="a/b") == "x.pdf"
    assert _gen_file(entry, "x.%E%n0", filename="a/b") == "x."


def test_old_filename_specifiers_without_filename(entry):
    """Without a `filename`, the old-filename specifiers render
    nothing."""
    assert _gen_file(entry, "X%l%L%e%n0") == "X"


def test_literal_slash_is_directory_separator(entry):
    """A literal `/` in the format survives (creating subfolders),
    while a `/` inside a field value becomes `-`."""
    assert _gen_file(entry, "%Y/%f{doi}%n0") == (
        "2014/10.1103-PhysRevA.90.032329"
    )
    # an explicit [slash] argument still overrides the default
    assert _gen_file(entry, "%f{doi}[_]%n0") == "10.1103_PhysRevA.90.032329"


def test_value_slash_replacement_in_words_and_keywords():
    entry = _entry(title="T", doi="10.1103/PhysRevA.90.032329")
    entry._set_keywords(  # pylint: disable=protected-access
        ("quantum/control",)
    )
    assert _gen_file(entry, "%w{doi}[.]2%n0") == "101103-PhysRevA"
    assert _gen_file(entry, "%k%n0") == "quantum-control"


def test_file_names_keep_non_ascii():
    """File names keep accented characters (cite keys fold them to
    ASCII)."""
    entry = _entry(author="Müller, Jörg", title="T")
    assert _gen_file(entry, "%a1%n0") == "Müller"
    assert _gen(entry, "%a1") == "Muller"


def test_file_names_keep_spaces(entry):
    assert _gen_file(entry, "%t22%n0") == "Robustness of high-fid"


def test_cite_key_colon_stripped_in_file_context(entry):
    assert (
        _gen_file(entry, "%f{Cite Key}%n0", current_key="Goerz:2014")
        == "Goerz2014"
    )


def test_file_clean_levels():
    entry = _entry(title=r"\emph{Deep} Learning", year="2014")
    assert _gen_file(entry, "%f{title}%n0", clean="tex") == "Deep Learning"
    assert (
        _gen_file(entry, "%f{title}%n0", clean="braces")
        == r"\emphDeep Learning"
    )
    assert (
        _gen_file(entry, "%f{title}%n0", clean="none")
        == r"\emph{Deep} Learning"
    )


def test_file_lowercase(entry):
    assert (
        _gen_file(
            entry,
            "%f{Cite Key}%U0%e",
            filename="dir/X.PDF",
            current_key="Goerz",
            lowercase=True,
        )
        == "goerz.pdf"
    )


def test_leading_slash_stripped(entry):
    """A leading `/` cannot escape the auto-file location."""
    assert _gen_file(entry, "/sub/%f{Cite Key}%n0", current_key="K") == "sub/K"


def test_file_unique_from_filesystem_callback(entry):
    """`is_free` decides uniqueness (the library checks the target
    directory on disk); `%u0` grows characters only as needed."""
    taken = {"Goerz2014.pdf"}
    assert (
        _gen_file(
            entry,
            "%f{Cite Key}%u0%e",
            filename="old/paper.pdf",
            current_key="Goerz2014",
            is_free=lambda name: name not in taken,
        )
        == "Goerz2014a.pdf"
    )


def test_file_current_name_matching_pattern_is_kept(entry):
    """A file whose current name already fits the format keeps it,
    even though generation would pick different unique characters."""
    taken = {"Goerz2014.pdf"}
    assert (
        _gen_file(
            entry,
            "%f{Cite Key}%u0%e",
            filename="papers/Goerz2014b.pdf",
            current_key="Goerz2014",
            current_name="Goerz2014b.pdf",
            is_free=lambda name: name not in taken,
        )
        == "Goerz2014b.pdf"
    )
