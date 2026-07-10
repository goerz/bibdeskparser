"""Tests for `bibdeskparser.library`."""

import datetime
import os
import re
import warnings
from contextlib import contextmanager
from pathlib import Path

import pytest
from IPython.lib.pretty import pretty

import bibdeskparser.library as library_module
from bibdeskparser.bdskfile import BibDeskFile
from bibdeskparser.entry import Entry
from bibdeskparser.groups import render_static_groups
from bibdeskparser.header import parse_header, update_header
from bibdeskparser.library import Library, StaleFileError

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"


def _entry_block(text, key):
    """The raw text of the entry block for `key` in `text`.

    Entry blocks are separated by a blank line before the next `@`
    block, so the block for `key` runs from its own `@type{key,` up to
    (but not including) the following `"\\n\\n@"`.
    """
    start = text.rindex("@", 0, text.index(f"{key},"))
    match = re.search(r"\n\n@", text[start:])
    end = start + match.start() if match else len(text)
    return text[start:end]


@pytest.fixture(scope="module", name="refs_text")
def fixture_refs_text():
    """The verbatim text of `refs.bib`."""
    return REFS_BIB.read_text(encoding="utf-8")


@pytest.fixture(name="bib")
def fixture_library():
    """A fresh `Library` loaded from `refs.bib` (recreated per test)."""
    return Library(REFS_BIB)


# -- 1. byte-exact pristine round-trip -------------------------------- #


def test_byte_exact_pristine_roundtrip(tmp_path, refs_text, bib):
    """Loading `refs.bib` and saving it unmodified reproduces the
    original file byte-for-byte."""
    out = tmp_path / "out.bib"
    bib.save(out)
    assert out.read_text(encoding="utf-8") == refs_text


def test_byte_exact_pristine_roundtrip_twice(tmp_path, refs_text, bib):
    """Saving twice in a row (still unmodified) is stable."""
    out = tmp_path / "out.bib"
    bib.save(out)
    bib.save(tmp_path / "out2.bib")
    assert out.read_text(encoding="utf-8") == refs_text
    assert (tmp_path / "out2.bib").read_text(encoding="utf-8") == refs_text


# -- 2. modify-one-entry round-trip ------------------------------------ #


def test_modify_one_entry_roundtrip(tmp_path, refs_text, bib):
    """Modifying a single entry leaves every other entry byte-exact,
    bumps the header timestamp (keeping the creator), and writes the
    modified entry with its fields in BibDesk order."""
    entry = bib["GoerzJPB2011"]
    entry["abstract"] = "New abstract."
    entry["note"] = "Some note."  # a brand new field, appended at the end

    out = tmp_path / "out.bib"
    bib.save(out)
    output = out.read_text(encoding="utf-8")

    assert "New abstract." in output
    assert "note = {Some note.}" in output

    block = _entry_block(output, "GoerzJPB2011")
    field_keys = re.findall(r"^\t([\w-]+) = ", block, re.MULTILINE)
    assert field_keys == [
        "abstract",
        "archiveprefix",
        "author",
        "date-added",
        "date-modified",
        "doi",
        "eprint",
        "journal",
        "keywords",
        "note",
        "number",
        "pages",
        "title",
        "volume",
        "year",
        "bdsk-file-1",
        "bdsk-url-1",
    ]

    # Unrelated entries are untouched, verbatim:
    for key in ["GoerzNJP2014", "GoerzPRA2014", "GoerzDiploma2010"]:
        assert _entry_block(output, key) == _entry_block(refs_text, key)

    # The header changed only in its timestamp:
    orig_creator, orig_timestamp = parse_header(refs_text)
    new_creator, new_timestamp = parse_header(output)
    assert new_creator == orig_creator
    assert new_timestamp > orig_timestamp


# -- 3. .timestamp ----------------------------------------------------- #


def test_timestamp_after_load(bib):
    """`.timestamp` matches the header of `refs.bib` after loading."""
    assert bib.timestamp == datetime.datetime(
        2026,
        7,
        9,
        7,
        22,
        48,
        tzinfo=datetime.timezone(datetime.timedelta(hours=-4)),
    )


def test_timestamp_none_before_first_save():
    """A from-scratch library has no timestamp until saved."""
    assert Library().timestamp is None


def test_save_without_path_raises():
    """Saving a from-scratch library without ever specifying a path
    raises."""
    with pytest.raises(ValueError):
        Library().save()


def test_timestamp_updated_by_modifying_save(tmp_path, bib):
    """A non-pristine save updates `.timestamp`."""
    before = bib.timestamp
    bib["GoerzJPB2011"]["abstract"] = "Changed."
    bib.save(tmp_path / "out.bib")
    assert bib.timestamp is not None
    assert bib.timestamp > before


def test_timestamp_unchanged_by_pristine_save(tmp_path, bib):
    """A pristine save does not touch `.timestamp`."""
    before = bib.timestamp
    bib.save(tmp_path / "out.bib")
    assert bib.timestamp == before


# -- 4. .path ------------------------------------------------------------ #


def test_path_after_load(bib):
    """`.path` is the file a library was loaded from, as a `Path`."""
    assert bib.path == REFS_BIB
    assert isinstance(bib.path, Path)


def test_path_none_before_first_save():
    """A from-scratch library has no path until saved."""
    assert Library().path is None


def test_path_updated_by_save(tmp_path, bib):
    """Saving to a new location updates `.path` to that location."""
    out = tmp_path / "out.bib"
    bib.save(out)
    assert bib.path == out
    assert isinstance(bib.path, Path)


def test_path_set_by_first_save(tmp_path):
    """Saving a from-scratch library sets `.path`."""
    out = tmp_path / "out.bib"
    lib = Library()
    lib.save(out)
    assert lib.path == out


# -- 5. .strings --------------------------------------------------------- #


def test_strings_get(bib):
    """Reading a macro strips its delimiters."""
    assert bib.strings["epjqt"] == "EPJ Quantum Technol."


def test_strings_set_new(tmp_path, bib):
    """Setting a new macro defines it, and it is saved as a braced
    `@string`."""
    bib.strings["foo"] = "Bar Baz"
    assert bib.strings["foo"] == "Bar Baz"
    out = tmp_path / "out.bib"
    bib.save(out)
    assert "@string{foo = {Bar Baz}}" in out.read_text(encoding="utf-8")


def test_strings_set_lowercases_name(bib):
    """Setting a macro with an uppercase name stores it lowercased,
    matching BibDesk's case-insensitive macro table."""
    bib.strings["FOO"] = "Bar Baz"
    assert bib.strings["foo"] == "Bar Baz"
    assert "FOO" not in bib.strings


def test_strings_set_invalid_name_raises(bib):
    """A macro name with a space is not valid BibTeX."""
    with pytest.raises(ValueError):
        bib.strings["Foo Bar"] = "x"


def test_strings_set_existing_updates_value(bib):
    """Setting an already-defined macro overwrites its value in
    place."""
    bib.strings["jpb"] = "Journal of Physics B"
    assert bib.strings["jpb"] == "Journal of Physics B"
    assert len(bib.strings) == 9


def test_strings_delitem_unknown_raises(bib):
    """Deleting an undefined macro name raises `KeyError`."""
    with pytest.raises(KeyError):
        del bib.strings["no-such-macro"]


def test_strings_mapping_interface(bib):
    """`.strings` behaves like a `dict` for reading."""
    assert "epjqt" in bib.strings
    assert "no-such-macro" not in bib.strings
    assert len(bib.strings) == 9
    assert set(bib.strings) >= {"epjqt", "jpb", "pra"}


def test_strings_repr_shows_macros(bib):
    """`repr(bib.strings)` immediately shows every macro name and
    value, exactly like a plain `dict`."""
    assert repr(bib.strings) == repr(dict(bib.strings))
    assert "'epjqt': 'EPJ Quantum Technol.'" in repr(bib.strings)


def test_strings_repr_pretty_shows_macros(bib):
    """IPython/Jupyter pretty-printing `bib.strings` shows the same
    name -> value mapping as `repr`, indented across multiple
    lines."""
    assert pretty(bib.strings) == pretty(dict(bib.strings))


def test_rename_string_updates_usages(bib):
    """Renaming a macro updates its `@string` and every entry using
    it, marking those entries dirty."""
    entry = bib["GoerzJPB2011"]
    assert entry._dirty is False
    bib.rename_string("jpb", "jphysb")
    assert bib.strings["jphysb"] == "J. Phys. B"
    assert "jpb" not in bib.strings
    assert entry["journal"] == "jphysb"
    assert entry._dirty is True


def test_rename_string_unknown_raises(bib):
    """Renaming an undefined macro raises `KeyError`."""
    with pytest.raises(KeyError):
        bib.rename_string("no-such-macro", "new-name")


def test_rename_string_existing_target_raises(bib):
    """Renaming onto an existing macro name is rejected."""
    with pytest.raises(ValueError):
        bib.rename_string("jpb", "pra")


def test_rename_string_invalid_target_raises(bib):
    """Renaming to an invalid macro name is rejected."""
    with pytest.raises(ValueError):
        bib.rename_string("jpb", "Not Valid")


def test_delete_string_in_use_raises(bib):
    """Deleting a macro referenced by an entry is rejected, and the
    macro is not deleted."""
    with pytest.raises(ValueError, match="jpb"):
        del bib.strings["jpb"]
    assert "jpb" in bib.strings


def test_delete_unused_string_succeeds(bib):
    """Deleting a macro not referenced by any entry succeeds."""
    bib.strings["unused"] = "Unused Macro"
    del bib.strings["unused"]
    assert "unused" not in bib.strings


def test_duplicate_macro_value_warning_on_set(bib):
    """Setting a macro to a value already used by another macro
    warns."""
    with pytest.warns(UserWarning, match="expand to the same value"):
        bib.strings["jpb2"] = "J. Phys. B"


def test_duplicate_macro_value_warning_on_load(tmp_path):
    """Loading a file with two macros expanding to the same value
    warns."""
    text = (
        "@string{a = {Same}}\n\n"
        "@string{b = {Same}}\n\n"
        "@article{k1,\n\ttitle = {T}}\n"
    )
    path = tmp_path / "dup.bib"
    path.write_text(text, encoding="utf-8")
    with pytest.warns(UserWarning, match="expand to the same value"):
        Library(path)


# -- 6. .groups ---------------------------------------------------------- #

GROUP_NAMES = [
    "My Papers",
    "OCT Software",
    "Preprints",
    "Superconducting Qubits",
]


@pytest.fixture(name="stale_bib")
def fixture_stale_bib(tmp_path):
    """A library whose static groups reference a citation key with no
    corresponding entry (`"Ghost"`), as can occur in a hand-edited or
    externally modified `.bib` file."""
    text = (
        "@article{K1,\n\ttitle = {T}}\n\n"
        "@comment{" + render_static_groups({"G": ("K1", "Ghost")}) + "}\n"
    )
    path = tmp_path / "stale.bib"
    path.write_text(text, encoding="utf-8")
    return Library(path)


def test_groups_mapping_read_interface(bib):
    """`.groups` reads like a `dict` mapping group name to a tuple of
    citation keys, and compares equal to an equivalent plain `dict`."""
    assert list(bib.groups) == GROUP_NAMES
    assert len(bib.groups) == 4
    assert "My Papers" in bib.groups
    assert "No Such Group" not in bib.groups
    assert bib.groups["Preprints"] == ("Aiello2605.00152",)
    assert isinstance(bib.groups["My Papers"], tuple)
    assert bib.groups == dict(bib.groups)
    with pytest.raises(KeyError):
        bib.groups["No Such Group"]  # pylint: disable=pointless-statement


def test_groups_repr_shows_members(bib):
    """`repr(bib.groups)` immediately shows every group and its
    members, exactly like a plain `dict`."""
    assert repr(bib.groups) == repr(dict(bib.groups))
    assert repr(bib.groups).startswith("{'My Papers': (")


def test_groups_repr_pretty_shows_members(bib):
    """IPython/Jupyter pretty-printing `bib.groups` shows the same
    name -> keys mapping as `repr`, indented across multiple lines."""
    assert pretty(bib.groups) == pretty(dict(bib.groups))


def test_groups_for_entry_via_entry(bib):
    """`entry.groups` (a tuple) reflects the group data."""
    assert bib["GoerzJPB2011"].groups == ("My Papers",)
    assert bib["GoerzSPP2019"].groups == ("My Papers", "OCT Software")


def test_groups_setitem_creates_empty_group(bib):
    """Assigning `()` under a new name creates an empty group without
    touching any entry's `.groups`."""
    before = {entry.key: entry.groups for entry in bib.entries}
    bib.groups["Brand New Group"] = ()
    assert bib.groups["Brand New Group"] == ()
    after = {entry.key: entry.groups for entry in bib.entries}
    assert before == after


def test_groups_setitem_creates_group_with_keys(bib):
    """Assigning a tuple of keys under a new name creates the group and
    updates exactly the member entries' `.groups`."""
    other = bib["GoerzSPP2019"].groups
    bib.groups["New Group"] = ("GoerzJPB2011", "GoerzQ2022")
    assert bib.groups["New Group"] == ("GoerzJPB2011", "GoerzQ2022")
    assert "New Group" in bib["GoerzJPB2011"].groups
    assert "New Group" in bib["GoerzQ2022"].groups
    assert bib["GoerzSPP2019"].groups == other


def test_groups_setitem_replaces_membership(bib):
    """Assigning to an existing group replaces its membership
    wholesale, refreshing dropped and added entries alike."""
    assert "My Papers" in bib["GoerzJPB2011"].groups
    bib.groups["My Papers"] = ("GoerzNJP2014", "GoerzPRA2014")
    assert bib.groups["My Papers"] == ("GoerzNJP2014", "GoerzPRA2014")
    assert "My Papers" not in bib["GoerzJPB2011"].groups
    assert "My Papers" in bib["GoerzNJP2014"].groups


def test_groups_setitem_rejects_bare_string(bib):
    """Assigning a single string (instead of an iterable of keys) is
    rejected, so it cannot be misread as many one-character keys."""
    with pytest.raises(TypeError, match="single string"):
        bib.groups["My Papers"] = "GoerzJPB2011"
    with pytest.raises(TypeError):
        bib.groups["My Papers"] = ("GoerzJPB2011", 42)


def test_groups_setitem_rejects_unknown_key(bib):
    """Assigning a citation key with no entry in the library raises
    `KeyError`, leaving the group unchanged."""
    before = bib.groups["My Papers"]
    with pytest.raises(KeyError, match="NoSuchKey2099"):
        bib.groups["My Papers"] = ("GoerzJPB2011", "NoSuchKey2099")
    assert bib.groups["My Papers"] == before


def test_groups_setitem_dedupes_keys(bib):
    """Duplicate keys in an assignment are dropped, preserving the
    first occurrence's position."""
    bib.groups["Dupes"] = ("GoerzQ2022", "GoerzJPB2011", "GoerzQ2022")
    assert bib.groups["Dupes"] == ("GoerzQ2022", "GoerzJPB2011")


def test_groups_stale_keys_grandfathered(stale_bib):
    """A key loaded from the file without a corresponding entry stays
    assignable to its group (and removable), but cannot spread to
    other groups."""
    assert stale_bib.groups["G"] == ("K1", "Ghost")
    stale_bib.add_to_group("G", "Ghost")  # already a member: no-op
    assert stale_bib.groups["G"] == ("K1", "Ghost")
    stale_bib.groups["G"] = ("Ghost",)  # re-assigning it is fine
    assert stale_bib.groups["G"] == ("Ghost",)
    with pytest.raises(KeyError, match="Ghost"):
        stale_bib.groups["G2"] = ("Ghost",)
    stale_bib.groups["G2"] = ()
    with pytest.raises(KeyError, match="Ghost"):
        stale_bib.add_to_group("G2", "Ghost")
    stale_bib.remove_from_group("G", "Ghost")
    assert stale_bib.groups["G"] == ()


def test_groups_noop_assignment_keeps_pristine(tmp_path, refs_text, bib):
    """Re-assigning a group's current membership does not mark the
    library as modified: a subsequent save is still byte-exact."""
    bib.groups["My Papers"] = bib.groups["My Papers"]
    out = tmp_path / "out.bib"
    bib.save(out)
    assert out.read_text(encoding="utf-8") == refs_text


def test_add_to_group_updates_only_that_entry(bib):
    """Adding entries to a group updates just those entries' `.groups`,
    leaving unrelated entries untouched."""
    other = bib["GoerzSPP2019"].groups
    bib.groups["New Group"] = ()
    result = bib.add_to_group("New Group", "GoerzJPB2011", "GoerzQ2022")
    assert result is None
    assert "New Group" in bib["GoerzJPB2011"].groups
    assert "New Group" in bib["GoerzQ2022"].groups
    assert bib.groups["New Group"] == ("GoerzJPB2011", "GoerzQ2022")
    assert bib["GoerzSPP2019"].groups == other


def test_add_to_group_duplicate_is_noop(bib):
    """Adding a key that is already a member is a silent no-op."""
    before = bib["GoerzJPB2011"].groups
    bib.add_to_group("My Papers", "GoerzJPB2011")
    assert bib["GoerzJPB2011"].groups == before
    assert bib.groups["My Papers"].count("GoerzJPB2011") == 1


def test_add_to_group_unknown_group_raises(bib):
    """Adding to a group that does not exist raises `KeyError` (groups
    are created explicitly, via `bib.groups[name] = ...`)."""
    with pytest.raises(KeyError):
        bib.add_to_group("No Such Group", "GoerzJPB2011")


def test_add_to_group_unknown_key_raises(bib):
    """Adding a citation key that has no corresponding entry raises
    `KeyError`, without modifying the group."""
    assert "NoSuchKey2099" not in bib
    before = bib.groups["Preprints"]
    with pytest.raises(KeyError, match="NoSuchKey2099"):
        bib.add_to_group("Preprints", "NoSuchKey2099")
    assert bib.groups["Preprints"] == before


def test_remove_from_group_updates_only_that_entry(bib):
    """Removing an entry from a group updates just that entry's
    `.groups`, leaving unrelated entries untouched."""
    other = bib["GoerzSPP2019"].groups
    assert bib.remove_from_group("My Papers", "GoerzJPB2011") is None
    assert "My Papers" not in bib["GoerzJPB2011"].groups
    assert "GoerzJPB2011" not in bib.groups["My Papers"]
    assert bib["GoerzSPP2019"].groups == other


def test_remove_from_group_not_a_member_is_noop(bib):
    """Removing a key that is not a member is a silent no-op, but an
    unknown group name raises `KeyError`."""
    before = bib["GoerzJPB2011"].groups
    bib.remove_from_group("Preprints", "GoerzJPB2011")
    assert bib["GoerzJPB2011"].groups == before
    with pytest.raises(KeyError):
        bib.remove_from_group("No Such Group", "GoerzJPB2011")


def test_groups_delitem_updates_every_member_entry(bib):
    """Deleting a group drops it from every member entry's `.groups`
    (not just one)."""
    assert "My Papers" in bib["GoerzJPB2011"].groups
    assert "My Papers" in bib["GoerzSPP2019"].groups
    del bib.groups["My Papers"]
    assert "My Papers" not in bib["GoerzJPB2011"].groups
    assert "My Papers" not in bib["GoerzSPP2019"].groups
    assert "My Papers" not in bib.groups


def test_groups_delitem_unknown_name_raises(bib):
    """Deleting a group name that does not exist raises `KeyError`."""
    with pytest.raises(KeyError):
        del bib.groups["No Such Group"]


def test_groups_mutablemapping_mixins(bib):
    """The `MutableMapping` mixins funnel through the view's
    `__setitem__`/`__delitem__`, maintaining entry consistency."""
    keys = bib.groups.pop("Preprints")
    assert keys == ("Aiello2605.00152",)
    assert "Preprints" not in bib.groups
    assert bib["Aiello2605.00152"].groups == ()
    assert bib.groups.setdefault("Preprints", ()) == ()
    assert bib.groups["Preprints"] == ()
    bib.groups.update({"Preprints": ("Aiello2605.00152",)})
    assert bib["Aiello2605.00152"].groups == ("Preprints",)
    bib.groups.clear()
    assert len(bib.groups) == 0
    assert all(entry.groups == () for entry in bib.entries)


def test_delete_entry_cascades_to_groups(bib):
    """Deleting an entry removes its citation key from every group."""
    assert "GoerzSPP2019" in bib.groups["My Papers"]
    assert "GoerzSPP2019" in bib.groups["OCT Software"]
    del bib["GoerzSPP2019"]
    assert "GoerzSPP2019" not in bib.groups["My Papers"]
    assert "GoerzSPP2019" not in bib.groups["OCT Software"]


def test_rekey_cascades_to_groups(bib):
    """`rekey` rewrites the citation key in every group, preserving
    its position, and the entry keeps its group membership."""
    position = bib.groups["My Papers"].index("GoerzNJP2014")
    bib.rekey("GoerzNJP2014", "NewKey2026")
    assert bib.groups["My Papers"][position] == "NewKey2026"
    assert "GoerzNJP2014" not in bib.groups["My Papers"]
    assert bib["NewKey2026"].groups == ("My Papers",)


def test_setitem_rekey_cascades_to_groups(bib):
    """The `bib[new] = bib[old]` spelling of a rename keeps group
    membership, exactly like `rekey`."""
    position = bib.groups["OCT Software"].index("GoerzQ2022")
    bib["NewKey2026"] = bib["GoerzQ2022"]
    assert bib.groups["OCT Software"][position] == "NewKey2026"
    assert bib["NewKey2026"].groups == ("My Papers", "OCT Software")


# -- 7. .keywords ---------------------------------------------------------#


def test_keywords_computed_from_entries(bib):
    """`.keywords` maps each keyword to the tuple of citation keys of
    the entries carrying it, computed from the stored fields."""
    assert bib.keywords["quantum computing"] == ("GoerzJPB2011",)
    assert bib.keywords["optimal control"] == ("GoerzDiploma2010",)
    assert bib["GoerzJPB2011"].keywords == (
        "Rydberg atoms",
        "quantum computing",
        "quantum information",
    )


def test_keywords_field_readable_not_writable_via_dict(bib):
    """The `keywords` field is readable through the entry `dict`
    interface, but not writable (which is what keeps `.keywords`
    always consistent)."""
    entry = bib["GoerzJPB2011"]
    assert isinstance(entry["keywords"], str)
    assert "keywords" in entry
    with pytest.raises(KeyError):
        entry["keywords"] = "some, keywords"


def test_add_to_keyword_updates_immediately(bib):
    """`add_to_keyword` edits the entries' stored field; the change is
    visible in `entry.keywords` and `library.keywords` right away."""
    entry = bib["GoerzNJP2014"]
    assert entry._dirty is False
    assert bib.add_to_keyword("new topic", "GoerzNJP2014", "GoerzQ2022") is (
        None
    )
    assert bib.keywords["new topic"] == ("GoerzNJP2014", "GoerzQ2022")
    assert entry.keywords == ("new topic",)
    assert entry._dirty is True  # keyword edits touch the entry ...


def test_group_mutation_does_not_dirty_entries(bib):
    """... while group mutations only affect the groups `@comment`
    block, leaving the member entries pristine."""
    entry = bib["GoerzDiploma2010"]
    bib.add_to_group("My Papers", "GoerzDiploma2010")
    assert entry.groups == ("My Papers",)
    assert entry._dirty is False


def test_add_to_keyword_existing_is_noop(bib):
    """Adding a keyword an entry already carries is a silent no-op."""
    entry = bib["GoerzJPB2011"]
    before = entry.keywords
    bib.add_to_keyword("quantum computing", "GoerzJPB2011")
    assert entry.keywords == before
    assert entry._dirty is False


def test_add_to_keyword_unknown_key_raises(bib):
    """An unknown citation key raises `KeyError` before any entry is
    modified."""
    with pytest.raises(KeyError):
        bib.add_to_keyword("new topic", "GoerzNJP2014", "NoSuchKey2099")
    assert "new topic" not in bib.keywords
    assert bib["GoerzNJP2014"].keywords == ()


def test_add_to_keyword_invalid_keyword_raises(bib):
    """Empty keywords and keywords containing a comma (the stored
    separator) are rejected."""
    with pytest.raises(ValueError, match="empty"):
        bib.add_to_keyword("  ", "GoerzNJP2014")
    with pytest.raises(ValueError, match="comma"):
        bib.add_to_keyword("a, b", "GoerzNJP2014")
    with pytest.raises(TypeError):
        bib.add_to_keyword(42, "GoerzNJP2014")


def test_remove_from_keyword_drops_empty_field(bib):
    """Removing an entry's last keyword removes the stored `keywords`
    field entirely."""
    entry = bib["GoerzDiploma2010"]
    bib.remove_from_keyword("optimal control", "GoerzDiploma2010")
    assert entry.keywords == ()
    assert "optimal control" not in bib.keywords
    assert entry._find_field("keywords") is None
    # removing it again (or from a non-carrying entry) is a no-op:
    bib.remove_from_keyword("optimal control", "GoerzDiploma2010")


def test_keyword_changes_survive_save_and_reload(tmp_path, bib):
    """Keyword edits are persisted in the entries' `keywords` fields."""
    bib.add_to_keyword("Schrödinger", "GoerzNJP2014")
    bib.remove_from_keyword("quantum computing", "GoerzJPB2011")
    out = tmp_path / "out.bib"
    bib.save(out)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the duplicate-key warning
        reloaded = Library(out)
    assert reloaded["GoerzNJP2014"].keywords == ("Schrödinger",)
    assert "quantum computing" not in reloaded.keywords
    assert 'Schr{\\"o}dinger' in out.read_text(encoding="utf-8")


def test_keywords_view_setitem_and_delitem(bib):
    """Assigning/deleting through the `library.keywords` mapping
    interface makes exactly the given entries carry the keyword."""
    bib.keywords["quantum computing"] = ["GoerzNJP2014"]
    assert bib.keywords["quantum computing"] == ("GoerzNJP2014",)
    assert "quantum computing" in bib["GoerzNJP2014"].keywords
    assert "quantum computing" not in bib["GoerzJPB2011"].keywords

    del bib.keywords["quantum computing"]
    assert "quantum computing" not in bib.keywords
    assert "quantum computing" not in bib["GoerzNJP2014"].keywords


def test_keywords_view_setitem_empty_deletes(bib):
    """Assigning `()` removes the keyword from every entry (an empty
    keyword has no representation in the file)."""
    bib.keywords["optimal control"] = ()
    assert "optimal control" not in bib.keywords
    assert bib["GoerzDiploma2010"].keywords == ()


def test_keywords_view_setitem_validates_before_mutating(bib):
    """A bare string or an unknown citation key is rejected before any
    entry is modified."""
    with pytest.raises(TypeError, match="single string"):
        bib.keywords["optimal control"] = "GoerzJPB2011"
    with pytest.raises(KeyError):
        bib.keywords["optimal control"] = ("GoerzJPB2011", "NoSuchKey2099")
    assert bib.keywords["optimal control"] == ("GoerzDiploma2010",)
    assert bib["GoerzJPB2011"]._dirty is False


def test_keywords_view_delitem_unknown_raises(bib):
    """Deleting an unknown keyword raises `KeyError`."""
    with pytest.raises(KeyError):
        del bib.keywords["no-such-keyword"]


def test_keywords_view_mapping_interface(bib):
    """`.keywords` behaves like a `dict` for reading, with a plain-dict
    `repr` that shows all keywords and their entries."""
    assert "quantum computing" in list(bib.keywords)
    assert len(bib.keywords) == len(list(bib.keywords))
    assert bib.keywords == dict(bib.keywords)
    assert repr(bib.keywords) == repr(dict(bib.keywords))
    assert "'optimal control': ('GoerzDiploma2010',)" in repr(bib.keywords)


def test_keywords_repr_pretty_shows_entries(bib):
    """IPython/Jupyter pretty-printing `bib.keywords` shows the same
    keyword -> keys mapping as `repr`, indented across multiple
    lines."""
    assert pretty(bib.keywords) == pretty(dict(bib.keywords))


def test_bare_keywords_value_is_not_a_macro_reference(tmp_path):
    """A bare (unbraced) `keywords` value, as might come from a
    hand-edited file, is literal text: it is exempt from
    `rename_string` rewriting, from macro-deletion protection, and
    from the undefined-macro check on save."""
    text = (
        "@string{alpha = {Some Value}}\n\n"
        "@article{K1,\n\ttitle = {T},\n\tkeywords = alpha\n}\n"
    )
    path = tmp_path / "bare_keywords.bib"
    path.write_text(text, encoding="utf-8")
    bib = Library(path)
    assert bib["K1"].keywords == ("alpha",)
    bib.rename_string("alpha", "beta")  # does not rewrite the keyword
    assert bib["K1"].keywords == ("alpha",)
    assert bib["K1"]._dirty is False
    del bib.strings["beta"]  # not blocked by the matching keyword
    assert len(bib.strings) == 0
    # The bare keyword does not raise as an undefined macro:
    bib.save(tmp_path / "out.bib")


# -- 8. .duplicate_keys ---------------------------------------------------#


def test_duplicate_keys_warns_and_reports():
    """Loading `refs.bib` warns about, and reports, its deliberate
    duplicate key."""
    with pytest.warns(UserWarning, match="duplicate citation keys"):
        duplicate_library = Library(REFS_BIB)
    assert duplicate_library.duplicate_keys == ("GoerzJOSS2025",)


def test_duplicate_keys_load_does_not_log_bibtexparser_noise(caplog):
    """Loading a file with a duplicate key does not leak
    `bibtexparser`'s internal "Unknown block type" log records; the
    condition is only reported via the `UserWarning` above."""
    with caplog.at_level("WARNING"):
        with pytest.warns(UserWarning, match="duplicate citation keys"):
            Library(REFS_BIB)
    assert "Unknown block type" not in caplog.text


def test_duplicate_field_key_warns(tmp_path, caplog):
    """Loading a file with a duplicate field key within one entry
    warns (via `Library`, not as raw `bibtexparser` logging)."""
    text = "@article{k1,\n\ttitle = {A},\n\ttitle = {B}\n}\n"
    path = tmp_path / "dup_field.bib"
    path.write_text(text, encoding="utf-8")
    with caplog.at_level("WARNING"):
        with pytest.warns(UserWarning, match="could not be parsed"):
            bib = Library(path)
    assert "Unknown block type" not in caplog.text
    assert len(bib) == 0


# -- 9. dict interface ----------------------------------------------------#


def test_dict_interface_basic(bib):
    """`Library` behaves like a `dict` mapping key to `Entry`."""
    entry = bib["GoerzJPB2011"]
    assert isinstance(entry, Entry)
    assert len(bib) == len(bib.entries)
    assert "GoerzJPB2011" in list(bib)
    assert all(isinstance(e, Entry) for e in bib.entries)


def test_add_new_entry(bib):
    """Adding a new entry sets `date-added` and wires up `.groups`."""
    entry = Entry("article", "NewKey2026", fields={"title": "T"})
    assert entry.date_added is not None
    bib["NewKey2026"] = entry
    assert bib["NewKey2026"] is entry
    assert entry.groups == ()
    bib.groups["Test Group"] = ()
    bib.add_to_group("Test Group", "NewKey2026")
    assert entry.groups == ("Test Group",)
    assert entry.date_added is not None
    assert "NewKey2026" in bib


def test_add_entry_adopts_assigned_key(bib):
    """Adding an entry under a key different from its own rekeys it
    to match, rather than raising."""
    entry = Entry("article", "WrongKey", fields={"title": "T"})
    bib["OtherKey"] = entry
    assert entry.key == "OtherKey"
    assert bib["OtherKey"] is entry
    assert "OtherKey" in bib
    assert "WrongKey" not in bib


def test_setitem_with_already_attached_entry_rekeys(bib):
    """`lib[new] = lib[old]` is recognized, via object identity, as an
    intentional rename rather than an attempt to add a disconnected
    entry -- equivalent to `lib.rekey(old, new)`."""
    entry = bib["GoerzJPB2011"]
    bib["OtherKey"] = entry
    assert entry.key == "OtherKey"
    assert bib["OtherKey"] is entry
    assert "GoerzJPB2011" not in bib


def test_setitem_with_already_attached_entry_to_existing_key_raises(
    bib,
):
    """`lib[new] = lib[old]` still raises if `new` is already used by a
    *different* entry -- the same collision `rekey` itself guards
    against -- leaving both entries untouched."""
    entry = bib["GoerzJPB2011"]
    with pytest.raises(ValueError):
        bib["GoerzQ2022"] = entry
    assert bib["GoerzJPB2011"] is entry
    assert bib["GoerzQ2022"] is not entry


def test_delete_then_add_under_new_key_rekeys_entry(bib):
    """An alternative way to rekey an already-attached entry: delete
    it under its old key, then assign it under the new one. (`rekey`
    is the more direct way to do this; see below.)"""
    entry = bib["GoerzJPB2011"]
    del bib["GoerzJPB2011"]
    bib["NewKey2026"] = entry
    assert entry.key == "NewKey2026"
    assert bib["NewKey2026"] is entry
    assert "GoerzJPB2011" not in bib


def test_rekey_renames_entry(bib):
    """`rekey` renames an already-attached entry and immediately
    updates the library's dict interface."""
    entry = bib["GoerzQ2022"]
    bib.rekey("GoerzQ2022", "xxx")
    assert entry.key == "xxx"
    assert bib["xxx"] is entry
    assert "GoerzQ2022" not in bib
    with pytest.raises(KeyError):
        bib["GoerzQ2022"]  # pylint: disable=pointless-statement


def test_rekey_missing_old_key_raises(bib):
    """Renaming a key that isn't in the library raises `KeyError`."""
    with pytest.raises(KeyError):
        bib.rekey("NoSuchKey", "xxx")


def test_rekey_to_existing_key_raises(bib):
    """Renaming to a key already used by a *different* entry raises,
    leaving both entries untouched."""
    with pytest.raises(ValueError):
        bib.rekey("GoerzQ2022", "GoerzJPB2011")
    assert bib["GoerzQ2022"].key == "GoerzQ2022"
    assert bib["GoerzJPB2011"].key == "GoerzJPB2011"


def test_rekey_same_key_is_noop(bib):
    """Renaming a key to itself is a harmless no-op."""
    entry = bib["GoerzQ2022"]
    bib.rekey("GoerzQ2022", "GoerzQ2022")
    assert bib["GoerzQ2022"] is entry


def test_setitem_rejects_non_entry(bib):
    """Only `Entry` instances may be assigned."""
    with pytest.raises(TypeError):
        bib["NotAnEntry"] = {"title": "T"}


def test_setitem_replaces_existing_key(bib):
    """Assigning a new `Entry` to an already-present key replaces it,
    detaching the old entry."""
    old_entry = bib["GoerzJPB2011"]
    new_entry = Entry("article", "GoerzJPB2011", fields={"title": "Replaced"})
    bib["GoerzJPB2011"] = new_entry
    assert bib["GoerzJPB2011"] is new_entry
    assert bib["GoerzJPB2011"]["title"] == "Replaced"
    assert old_entry.groups == ()
    # group membership is by citation key, so the new entry takes over
    # the old entry's place in the groups:
    assert new_entry.groups == ("My Papers",)


def test_repr(bib):
    """`repr` shows the loaded path."""
    assert repr(bib) == f"Library({REFS_BIB!r})"


def test_delete_entry(bib):
    """Deleting a key detaches the entry from the library and removes
    the key from every group."""
    entry = bib["GoerzJPB2011"]
    del bib["GoerzJPB2011"]
    assert "GoerzJPB2011" not in bib
    assert entry.groups == ()
    assert "GoerzJPB2011" not in bib.groups["My Papers"]


# -- 10. stale save --------------------------------------------------------#


def test_stale_save_raises_and_force_overwrites(tmp_path, refs_text):
    """Saving over a file that was modified on disk (newer header
    timestamp) raises `StaleFileError`; `force=True` overwrites
    anyway."""
    path = tmp_path / "refs.bib"
    path.write_text(refs_text, encoding="utf-8")
    bib = Library(path)

    # Simulate BibDesk re-saving the file after this library was
    # loaded, with a later header timestamp:
    newer_timestamp = bib.timestamp + datetime.timedelta(days=1)
    newer_text = update_header(refs_text, newer_timestamp)
    path.write_text(newer_text, encoding="utf-8")

    bib["GoerzJPB2011"]["abstract"] = "Changed."
    with pytest.raises(StaleFileError):
        bib.save(path)

    bib.save(path, force=True)
    output = path.read_text(encoding="utf-8")
    assert output != newer_text
    assert "Changed." in output


# -- 11. from-scratch library ----------------------------------------------#


def test_from_scratch_roundtrip(tmp_path):
    """A from-scratch library saves and reloads correctly."""
    bib = Library()
    assert bib.timestamp is None

    bib.strings["x"] = "Y"
    entry = Entry("article", "K1", fields={"title": "T"})
    bib["K1"] = entry

    out = tmp_path / "new.bib"
    bib.save(out)
    assert bib.timestamp is not None

    text = out.read_text(encoding="utf-8")
    creator, timestamp = parse_header(text)
    assert creator  # non-empty
    assert timestamp == bib.timestamp

    reloaded = Library(out)
    assert reloaded["K1"]["title"] == "T"
    assert reloaded.strings["x"] == "Y"


# -- 12. undefined macro validation on save --------------------------------#


def test_undefined_macro_raises_on_save(tmp_path, bib):
    """Saving with an entry referencing an undefined macro raises."""
    # A plain macro-shaped value is stored as a bare macro reference
    # silently (wrap in MacroString/ValueString to be explicit).
    bib["GoerzJPB2011"]["journal"] = "totallyundefinedmacro"

    with pytest.raises(ValueError, match="totallyundefinedmacro"):
        bib.save(tmp_path / "x.bib")

    bib.strings["totallyundefinedmacro"] = "Some Journal"
    bib.save(tmp_path / "x.bib")  # now succeeds
    assert (tmp_path / "x.bib").exists()


# -- 13. missing referenced file -------------------------------------------#


def test_missing_linked_file_warns_on_save(tmp_path, bib):
    """A `.files` entry pointing to a now-missing file warns (but does
    not raise) on save."""
    real_file = tmp_path / "paper.pdf"
    real_file.write_bytes(b"%PDF-1.4 fake")
    bdsk_file = BibDeskFile(real_file, relative_to=tmp_path)
    bib["GoerzNJP2014"]._set_files([bdsk_file])
    real_file.unlink()  # now missing

    with pytest.warns(UserWarning, match="linked file does not exist"):
        bib.save(tmp_path / "out.bib")


# -- groups: synthesizing a `@comment` block where none existed -----------#


def test_groups_block_created_on_save_when_absent(tmp_path):
    """A library with no static-groups `@comment` block gets one added
    on save, once a group is created."""
    bib = Library()
    entry = Entry("article", "K1", fields={"title": "T"})
    bib["K1"] = entry
    bib.groups["My Papers"] = ("K1",)

    out = tmp_path / "new.bib"
    bib.save(out)
    text = out.read_text(encoding="utf-8")
    assert "BibDesk Static Groups{" in text

    reloaded = Library(out)
    assert reloaded.groups == {"My Papers": ("K1",)}
    assert reloaded["K1"].groups == ("My Papers",)


# -- file attachments: add/replace/unlink/rename ---------------------------#


@contextmanager
def _quiet_bookmarks():
    """Ignore the "Could not create a macOS bookmark" `UserWarning`
    (emitted for every genuinely new attachment when pyobjc is not
    installed)."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Could not create a macOS bookmark"
        )
        yield


def _file_bib(tmp_path, files=("a.pdf",)):
    """A `Library` with entries `K1`/`K2`, saved to `tmp_path /
    "lib.bib"`, with each of `files` created in `tmp_path` and
    attached to `K1`."""
    bib = Library()
    bib["K1"] = Entry("article", "K1", fields={"title": "T1"})
    bib["K2"] = Entry("article", "K2", fields={"title": "T2"})
    bib.save(tmp_path / "lib.bib")
    for name in files:
        (tmp_path / name).write_bytes(b"%PDF-1.4 fake")
        with _quiet_bookmarks():
            bib.add_file("K1", tmp_path / name)
    return bib


def test_add_file_library_relative(tmp_path):
    """A relative filename that exists in the library directory (and
    not in the CWD) is attached, stored relative to the library."""
    bib = _file_bib(tmp_path, files=())
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    assert bib["K1"]._dirty is False
    with _quiet_bookmarks():
        bib.add_file("K1", "a.pdf")
    assert bib["K1"].files == ["a.pdf"]
    assert bib["K1"]._dirty is True


def test_add_file_cwd_relative(tmp_path, monkeypatch):
    """A relative filename that exists in the CWD (and not in the
    library directory) is attached, stored relative to the library."""
    bib = _file_bib(tmp_path, files=())
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.chdir(workdir)
    with _quiet_bookmarks():
        bib.add_file("K1", "b.pdf")
    assert bib["K1"].files == ["work/b.pdf"]


def test_add_file_ambiguous_raises(tmp_path, monkeypatch):
    """A relative filename existing both in the library directory and
    in a (different) CWD raises `ValueError`."""
    bib = _file_bib(tmp_path, files=())
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "a.pdf").write_bytes(b"%PDF-1.4 other")
    monkeypatch.chdir(workdir)
    with pytest.raises(ValueError, match="ambiguous"):
        bib.add_file("K1", "a.pdf")


def test_add_file_cwd_is_library_dir(tmp_path, monkeypatch):
    """When the CWD *is* the library directory, both interpretations
    coincide: no ambiguity."""
    bib = _file_bib(tmp_path, files=())
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.chdir(tmp_path)
    with _quiet_bookmarks():
        bib.add_file("K1", "a.pdf")
    assert bib["K1"].files == ["a.pdf"]


def test_add_file_missing_raises(tmp_path):
    """A nonexistent filename raises `FileNotFoundError` (naming both
    checked locations)."""
    bib = _file_bib(tmp_path, files=())
    with pytest.raises(FileNotFoundError, match="ghost.pdf"):
        bib.add_file("K1", "ghost.pdf")


def test_add_file_unchecked(tmp_path):
    """With `check_that_file_exists=False`, a nonexistent filename is
    stored as-is, relative to the library directory, as a path-only
    attachment -- without any warning."""
    bib = _file_bib(tmp_path, files=())
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        bib.add_file("K1", "ghost.pdf", check_that_file_exists=False)
    assert bib["K1"].files == ["ghost.pdf"]


def test_add_file_duplicate_raises(tmp_path):
    """Attaching a file that is already attached raises `ValueError`."""
    bib = _file_bib(tmp_path)
    with pytest.raises(ValueError, match="already attached"):
        bib.add_file("K1", "a.pdf")


def test_file_methods_require_library_path(tmp_path):
    """All file operations on a never-saved library raise
    `ValueError`."""
    bib = Library()
    bib["K1"] = Entry("article", "K1", fields={"title": "T"})
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ValueError, match="save the library first"):
        bib.add_file("K1", tmp_path / "a.pdf")
    with pytest.raises(ValueError, match="save the library first"):
        bib.unlink_file("K1", "a.pdf", remove=False)
    with pytest.raises(ValueError, match="save the library first"):
        bib.replace_file("K1", "a.pdf", "b.pdf", remove=False)
    with pytest.raises(ValueError, match="save the library first"):
        bib.rename_file("K1", "a.pdf", "b.pdf")


def test_add_file_unknown_key_raises(tmp_path):
    """An unknown citation key raises `KeyError`."""
    bib = _file_bib(tmp_path)
    with pytest.raises(KeyError):
        bib.add_file("NoSuchKey", "a.pdf")


def test_unlink_file_keeps_on_disk(tmp_path):
    """`unlink_file(..., remove=False)` removes the attachment (with
    renumbering) but leaves the file on disk."""
    bib = _file_bib(tmp_path, files=("a.pdf", "b.pdf"))
    bib.unlink_file("K1", "a.pdf", remove=False)
    assert bib["K1"].files == ["b.pdf"]
    entry = bib["K1"]
    assert "bdsk-file-1" in entry._entry.fields_dict
    assert "bdsk-file-2" not in entry._entry.fields_dict
    assert (tmp_path / "a.pdf").exists()


def test_unlink_file_remove_deletes(tmp_path, monkeypatch):
    """`unlink_file(..., remove=True)` also deletes the file from
    disk."""
    monkeypatch.setattr(library_module, "_delete_file", os.remove)
    bib = _file_bib(tmp_path, files=("a.pdf",))
    bib.unlink_file("K1", "a.pdf", remove=True)
    assert bib["K1"].files == []
    assert not (tmp_path / "a.pdf").exists()


def test_unlink_file_remove_skips_shared(tmp_path, monkeypatch):
    """`remove=True` does not delete a file still linked from another
    entry (a `UserWarning` instead)."""
    monkeypatch.setattr(library_module, "_delete_file", os.remove)
    bib = _file_bib(tmp_path, files=("shared.pdf",))
    with _quiet_bookmarks():
        bib.add_file("K2", "shared.pdf")
    with pytest.warns(UserWarning, match="still linked"):
        bib.unlink_file("K1", "shared.pdf", remove=True)
    assert bib["K1"].files == []
    assert bib["K2"].files == ["shared.pdf"]
    assert (tmp_path / "shared.pdf").exists()


def test_unlink_file_remove_already_missing(tmp_path):
    """`remove=True` for a file already absent from disk is not an
    error."""
    bib = _file_bib(tmp_path, files=("a.pdf",))
    (tmp_path / "a.pdf").unlink()
    bib.unlink_file("K1", "a.pdf", remove=True)
    assert bib["K1"].files == []


def test_unlink_file_not_linked_raises(tmp_path):
    """Unlinking a file that is not attached raises `ValueError`."""
    bib = _file_bib(tmp_path)
    with pytest.raises(ValueError, match="not linked"):
        bib.unlink_file("K1", "other.pdf", remove=False)


def test_match_attachment_ambiguous_raises(tmp_path, monkeypatch):
    """A relative filename matching two *different* attachments (via
    its library-relative and CWD-relative interpretations) raises
    `ValueError`."""
    (tmp_path / "work").mkdir()
    bib = _file_bib(tmp_path, files=("x.pdf", "work/x.pdf"))
    monkeypatch.chdir(tmp_path / "work")
    with pytest.raises(ValueError, match="ambiguous"):
        bib.unlink_file("K1", "x.pdf", remove=False)
    # An absolute path disambiguates:
    bib.unlink_file("K1", tmp_path / "work" / "x.pdf", remove=False)
    assert bib["K1"].files == ["x.pdf"]


def test_replace_file_keeps_position(tmp_path):
    """`replace_file` swaps in the new file at the old file's position
    in `.files`."""
    bib = _file_bib(tmp_path, files=("a.pdf", "b.pdf"))
    (tmp_path / "c.pdf").write_bytes(b"%PDF-1.4 fake")
    with _quiet_bookmarks():
        bib.replace_file("K1", "a.pdf", "c.pdf", remove=False)
    assert bib["K1"].files == ["c.pdf", "b.pdf"]
    assert (tmp_path / "a.pdf").exists()


def test_replace_file_remove_deletes_old(tmp_path, monkeypatch):
    """`replace_file(..., remove=True)` deletes the old file from
    disk."""
    monkeypatch.setattr(library_module, "_delete_file", os.remove)
    bib = _file_bib(tmp_path, files=("a.pdf",))
    (tmp_path / "c.pdf").write_bytes(b"%PDF-1.4 fake")
    with _quiet_bookmarks():
        bib.replace_file("K1", "a.pdf", "c.pdf", remove=True)
    assert bib["K1"].files == ["c.pdf"]
    assert not (tmp_path / "a.pdf").exists()


def test_replace_file_duplicate_raises(tmp_path):
    """Replacing with a file that is already attached raises
    `ValueError`."""
    bib = _file_bib(tmp_path, files=("a.pdf", "b.pdf"))
    with pytest.raises(ValueError, match="already attached"):
        bib.replace_file("K1", "a.pdf", "b.pdf", remove=False)


# -- url attachments: add/replace/remove -----------------------------------#


def test_library_add_url(tmp_path):
    """`Library.add_url` delegates to `Entry.add_url`."""
    bib = _file_bib(tmp_path)
    bib.add_url("K1", "http://example.org/a")
    bib.add_url("K1", "https://example.org/b")
    assert bib["K1"].urls == (
        "http://example.org/a",
        "https://example.org/b",
    )


def test_library_add_url_unknown_key_raises(tmp_path):
    """An unknown citation key raises `KeyError`."""
    bib = _file_bib(tmp_path)
    with pytest.raises(KeyError):
        bib.add_url("NoSuchKey", "http://example.org/a")


def test_library_add_url_invalid_and_duplicate_raise(tmp_path):
    """`add_url` raises `ValueError` for an invalid URL or a
    duplicate."""
    bib = _file_bib(tmp_path)
    with pytest.raises(ValueError):
        bib.add_url("K1", "not a url")
    bib.add_url("K1", "http://example.org/a")
    with pytest.raises(ValueError, match="already linked"):
        bib.add_url("K1", "http://example.org/a")


def test_library_replace_url(tmp_path):
    """`Library.replace_url` swaps a URL in place; a missing old URL or
    invalid new URL raises `ValueError`."""
    bib = _file_bib(tmp_path)
    bib.add_url("K1", "http://example.org/a")
    bib.replace_url("K1", "http://example.org/a", "http://example.org/c")
    assert bib["K1"].urls == ("http://example.org/c",)
    with pytest.raises(ValueError, match="not linked"):
        bib.replace_url("K1", "http://example.org/x", "http://example.org/y")
    with pytest.raises(ValueError):
        bib.replace_url("K1", "http://example.org/c", "not a url")


def test_library_remove_url(tmp_path):
    """`Library.remove_url` removes a linked URL; a missing one raises
    `ValueError`."""
    bib = _file_bib(tmp_path)
    bib.add_url("K1", "http://example.org/a")
    bib.remove_url("K1", "http://example.org/a")
    assert bib["K1"].urls == ()
    with pytest.raises(ValueError, match="not linked"):
        bib.remove_url("K1", "http://example.org/a")


def test_rename_file_bare_name(tmp_path):
    """A bare new filename renames the file within its current
    directory (on disk and in `.files`)."""
    bib = _file_bib(tmp_path, files=("a.pdf",))
    with _quiet_bookmarks():
        bib.rename_file("K1", "a.pdf", "renamed.pdf")
    assert bib["K1"].files == ["renamed.pdf"]
    assert not (tmp_path / "a.pdf").exists()
    assert (tmp_path / "renamed.pdf").exists()


def test_rename_file_updates_all_entries(tmp_path):
    """Renaming a file linked from several entries updates every one
    of them."""
    bib = _file_bib(tmp_path, files=("shared.pdf",))
    with _quiet_bookmarks():
        bib.add_file("K2", "shared.pdf")
    bib.save()
    assert bib["K2"]._dirty is False
    with _quiet_bookmarks():
        bib.rename_file("K1", "shared.pdf", "renamed.pdf")
    assert bib["K1"].files == ["renamed.pdf"]
    assert bib["K2"].files == ["renamed.pdf"]
    assert bib["K1"]._dirty is True
    assert bib["K2"]._dirty is True


def test_rename_file_into_subdirectory(tmp_path):
    """A new filename with a directory component is interpreted
    relative to the library directory."""
    bib = _file_bib(tmp_path, files=("a.pdf",))
    (tmp_path / "sub").mkdir()
    with _quiet_bookmarks():
        bib.rename_file("K1", "a.pdf", "sub/a.pdf")
    assert bib["K1"].files == ["sub/a.pdf"]
    assert (tmp_path / "sub" / "a.pdf").exists()


def test_rename_file_target_exists_raises(tmp_path):
    """Renaming onto an existing file raises `FileExistsError`."""
    bib = _file_bib(tmp_path, files=("a.pdf", "b.pdf"))
    with pytest.raises(FileExistsError):
        bib.rename_file("K1", "a.pdf", "b.pdf")
    assert bib["K1"].files == ["a.pdf", "b.pdf"]


def test_rename_file_missing_on_disk_raises(tmp_path):
    """Renaming an attachment whose file is absent from disk raises
    `FileNotFoundError`."""
    bib = _file_bib(tmp_path, files=("a.pdf",))
    (tmp_path / "a.pdf").unlink()
    with pytest.raises(FileNotFoundError):
        bib.rename_file("K1", "a.pdf", "renamed.pdf")


def test_attachments_roundtrip_through_save(tmp_path):
    """Attachments added via `add_file` survive a save/reload cycle."""
    bib = _file_bib(tmp_path, files=("a.pdf",))
    bib.save()
    reloaded = Library(tmp_path / "lib.bib")
    assert reloaded["K1"].files == ["a.pdf"]
