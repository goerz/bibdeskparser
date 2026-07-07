"""Tests for `bibdeskparser.entry`."""

import datetime
from pathlib import Path

import bibtexparser
import pytest
from bibtexparser import model

import bibdeskparser.entry as entry_module
from bibdeskparser.bdskfile import BibDeskFile
from bibdeskparser.entry import Entry, Value
from bibdeskparser.middleware import parse_stack

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"

_FIXED_DATE_FIELDS = [
    model.Field(key="date-added", value="{2026-01-01 00:00:00 +0000}"),
    model.Field(key="date-modified", value="{2026-01-01 00:00:00 +0000}"),
]


def _pristine_entry(entry_type="article", key="K", extra_fields=()):
    """An `Entry._wrap`-ped entry with dates already set (simulating a
    freshly loaded, unmodified entry)."""
    fields = [
        model.Field(key=field.key, value=field.value)
        for field in _FIXED_DATE_FIELDS
    ] + list(extra_fields)
    model_entry = model.Entry(entry_type=entry_type, key=key, fields=fields)
    return Entry._wrap(model_entry)


# -- MutableMapping basics -------------------------------------------------- #


def test_get_set_delete():
    """Basic get/set/delete on a normal field."""
    entry = Entry("article", "K")
    entry["title"] = "Some Title"
    assert entry["title"] == "Some Title"
    del entry["title"]
    assert "title" not in entry


def test_case_insensitive_access():
    """Field access is case-insensitive and does not duplicate fields."""
    entry = Entry("article", "K")
    entry["Title"] = "Some Title"
    assert entry["TITLE"] == "Some Title"
    assert entry["title"] == "Some Title"
    assert len(entry) == 1


def test_iteration_excludes_date_and_bdsk_fields():
    """`__iter__`/`__len__`/`__contains__` skip date-*/bdsk-* fields."""
    entry = _pristine_entry(
        extra_fields=[
            model.Field(key="title", value="{T}"),
            model.Field(key="bdsk-url-1", value="{http://example.org}"),
        ]
    )
    assert set(entry.keys()) == {"title"}
    assert len(entry) == 1
    assert "date-added" not in entry
    assert "date-modified" not in entry
    assert "bdsk-url-1" not in entry
    assert "title" in entry


def test_mutablemapping_mixins():
    """`keys`/`values`/`items`/`get`/`pop`/`update` work via the
    `MutableMapping` mixin."""
    entry = Entry("article", "K")
    entry["title"] = "T"
    entry["year"] = "2024"
    assert dict(entry.items()) == {"title": "T", "year": "2024"}
    assert set(entry.values()) == {"T", "2024"}
    assert entry.get("missing", "default") == "default"
    entry.update({"journal": "Some Journal"})
    assert entry["journal"] == "Some Journal"
    value = entry.pop("year")
    assert value == "2024"
    assert "year" not in entry


def test_date_fields_excluded_from_dict_interface():
    """`date-added`/`date-modified` cannot be set/deleted through the
    dict interface."""
    entry = Entry("article", "K")
    with pytest.raises(KeyError):
        entry["date-added"] = "x"
    with pytest.raises(KeyError):
        entry["date-modified"] = "x"
    with pytest.raises(KeyError):
        del entry["date-added"]
    with pytest.raises(KeyError):
        entry["date-added"]  # pylint: disable=pointless-statement


def test_bdsk_fields_excluded_from_dict_interface():
    """`bdsk-*` fields cannot be accessed through the dict interface."""
    entry = Entry("article", "K")
    with pytest.raises(KeyError):
        entry["bdsk-url-1"] = "x"
    with pytest.raises(KeyError):
        del entry["bdsk-url-1"]


# -- brace stripping / Value / macro warnings ------------------------------- #


def test_get_strips_braces():
    """A plain unicode value is stored braced but returned without
    braces."""
    entry = Entry("article", "K")
    entry["title"] = "Some Title"
    assert entry["title"] == "Some Title"
    assert entry._entry.fields_dict["title"].value == "{Some Title}"


def test_value_forces_braces_even_for_macro_name():
    """`Value("prl")` is stored braced even though "prl" is a valid
    macro name; plain `"prl"` is stored bare and warns."""
    entry = Entry("article", "K")
    entry["journal"] = Value("prl")
    assert entry["journal"] == "prl"
    assert entry._entry.fields_dict["journal"].value == "{prl}"

    with pytest.warns(UserWarning, match="macro reference"):
        entry["journal"] = "prl"
    assert entry["journal"] == "prl"
    assert entry._entry.fields_dict["journal"].value == "prl"


def test_texify_roundtrip():
    """Setting a unicode value stores its TeX-encoded form; getting it
    back gives the original unicode."""
    entry = Entry("article", "K")
    entry["title"] = "Universität Tübingen"
    raw = entry._entry.fields_dict["title"].value
    assert '{\\"u}' in raw
    assert entry["title"] == "Universität Tübingen"


# -- dates / dirty ---------------------------------------------------------- #


def test_fresh_entry_dates_and_dirty(monkeypatch):
    """A freshly constructed entry gets `date-added`/`date-modified`
    set to (approximately) now, and is `dirty` (a brand new entry has
    never been saved)."""
    fixed = datetime.datetime(
        2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
    )

    class _FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(entry_module.datetime, "datetime", _FakeDateTime)
    entry = Entry("article", "Key2026")
    assert entry.date_added == fixed
    assert entry.date_modified == fixed
    assert entry.date_added.tzinfo is not None
    assert entry.dirty is True


def test_date_modified_advances_on_mutation(monkeypatch):
    """Mutating a field advances `date_modified` but not `date_added`."""
    fixed = datetime.datetime(
        2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
    )

    class _FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(entry_module.datetime, "datetime", _FakeDateTime)
    entry = Entry("article", "Key2026")
    assert entry.date_added == fixed
    assert entry.date_modified == fixed

    later = fixed + datetime.timedelta(seconds=5)

    class _FakeDateTimeLater(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(entry_module.datetime, "datetime", _FakeDateTimeLater)
    entry["title"] = "T"
    assert entry.date_modified == later
    assert entry.date_added == fixed


def test_wrap_is_pristine_then_becomes_dirty():
    """`Entry._wrap` does not touch dates/dirty; mutating afterward
    flips `dirty` to `True`."""
    entry = _pristine_entry(
        extra_fields=[model.Field(key="title", value="{T}")]
    )
    assert entry.dirty is False
    entry["title"] = "New Title"
    assert entry.dirty is True


def test_missing_date_fields_give_none():
    """`date_added`/`date_modified` are `None` if the fields are
    absent."""
    model_entry = model.Entry(entry_type="article", key="K", fields=[])
    entry = Entry._wrap(model_entry)
    assert entry.date_added is None
    assert entry.date_modified is None


# -- key / entry_type ------------------------------------------------------- #


def test_entry_type_setter_touches_dirty():
    """Setting `entry_type` delegates and marks the entry dirty."""
    entry = _pristine_entry()
    assert entry.dirty is False
    entry.entry_type = "book"
    assert entry.entry_type == "book"
    assert entry._entry.entry_type == "book"
    assert entry.dirty is True


def test_key_is_read_only():
    """`key` cannot be reassigned; renaming happens through the
    owning `Library` instead."""
    entry = _pristine_entry(key="K")
    with pytest.raises(AttributeError):
        entry.key = "NewKey"
    assert entry.key == "K"


# -- groups ----------------------------------------------------------------- #


def test_groups_without_library():
    """Without a `Library` maintaining it, `groups` is empty."""
    entry = Entry("article", "K")
    assert entry.groups == ()


def test_groups_snapshot():
    """`groups` returns the `Library`-maintained membership as a
    (read-only) `tuple`."""
    entry = Entry("article", "K")
    entry._groups = ("Group A", "Group B")
    assert entry.groups == ("Group A", "Group B")
    assert isinstance(entry.groups, tuple)


# -- keywords ----------------------------------------------------------------#


def test_keywords_excluded_from_dict_interface():
    """The `keywords` field cannot be read, set, or deleted through
    the dict interface, and iteration/`len` skip it."""
    entry = _pristine_entry(
        extra_fields=[
            model.Field(key="title", value="{T}"),
            model.Field(key="keywords", value="{a, b}"),
        ]
    )
    with pytest.raises(KeyError, match="keywords"):
        entry["keywords"]  # pylint: disable=pointless-statement
    with pytest.raises(KeyError, match="keywords"):
        entry["keywords"] = "x"
    with pytest.raises(KeyError, match="keywords"):
        del entry["keywords"]
    assert set(entry.keys()) == {"title"}
    assert len(entry) == 1
    assert "keywords" not in entry


def test_constructor_rejects_keywords_field():
    """`fields` in the constructor go through the dict interface, so a
    `keywords` field is rejected like any other hidden field."""
    with pytest.raises(KeyError, match="keywords"):
        Entry("article", "K", fields={"keywords": "a, b"})


def test_keywords_property_parses_stored_field():
    """`.keywords` parses the stored comma-separated field on access,
    decoding TeX accents like any other field value."""
    entry = _pristine_entry(
        extra_fields=[
            model.Field(
                key="keywords",
                value=r"{quantum computing, Schr{\"o}dinger}",
            ),
        ]
    )
    assert entry.keywords == ("quantum computing", "Schrödinger")
    assert Entry("article", "K").keywords == ()


def test_bare_keywords_value_is_literal():
    """A bare (unbraced) stored `keywords` value, as might come from a
    hand-edited file, is literal text: it is not normalized as a macro
    name (keywords are never `@string` references)."""
    entry = _pristine_entry(
        extra_fields=[model.Field(key="keywords", value="Alpha")]
    )
    assert entry.keywords == ("Alpha",)


def test_set_keywords_roundtrip():
    """The private `_set_keywords` stores the TeX-encoded field,
    removes the field when set to `()`, and marks the entry dirty."""
    entry = _pristine_entry()
    assert entry.dirty is False
    entry._set_keywords(("quantum computing", "Schrödinger"))
    assert entry.keywords == ("quantum computing", "Schrödinger")
    raw = entry._entry.fields_dict["keywords"].value
    assert raw == r"{quantum computing, Schr{\"o}dinger}"
    assert entry.dirty is True

    entry._set_keywords(())
    assert entry.keywords == ()
    assert "keywords" not in entry._entry.fields_dict


def test_set_keywords_empty_to_empty_is_noop():
    """`_set_keywords(())` on an entry without keywords does not touch
    the entry."""
    entry = _pristine_entry()
    entry._set_keywords(())
    assert entry.dirty is False


def test_copy_keeps_keywords():
    """Keywords are stored in the entry itself, so `copy()` preserves
    them (unlike `groups`, which are library data)."""
    entry = _pristine_entry(
        extra_fields=[model.Field(key="keywords", value="{a, b}")]
    )
    entry._groups = ("Some Group",)
    copy = entry.copy()
    assert copy.keywords == ("a", "b")
    assert copy.groups == ()


# -- files ------------------------------------------------------------------ #


def test_files_getter_numeric_order(tmp_path):
    """`files` returns paths in numeric order, e.g. 2 before 10."""
    fields = [
        model.Field(
            key="bdsk-file-10",
            value=BibDeskFile(
                tmp_path / "b.pdf", bookmark=b"\x02", relative_to=tmp_path
            ),
        ),
        model.Field(
            key="bdsk-file-2",
            value=BibDeskFile(
                tmp_path / "a.pdf", bookmark=b"\x01", relative_to=tmp_path
            ),
        ),
    ]
    entry = _pristine_entry(extra_fields=fields)
    assert entry.files == ["a.pdf", "b.pdf"]


def test_files_read_only(tmp_path):
    """`.files` cannot be assigned: attachments are managed through
    the owning `Library` (which knows the `.bib` directory)."""
    original = BibDeskFile(
        tmp_path / "a.pdf",
        bookmark=b"\xde\xad\xbe\xef",
        relative_to=tmp_path,
    )
    entry = _pristine_entry(
        extra_fields=[model.Field(key="bdsk-file-1", value=original)]
    )
    with pytest.raises(AttributeError):
        entry.files = ["a.pdf", "b.pdf"]
    assert entry.files == ["a.pdf"]
    assert entry.dirty is False


def test_set_files_renumbers_and_touches(tmp_path):
    """The private `_set_files` rebuilds the `bdsk-file-N` fields,
    renumbering from 1, and marks the entry dirty."""
    file_a = BibDeskFile(
        tmp_path / "a.pdf", bookmark=b"\x01", relative_to=tmp_path
    )
    file_b = BibDeskFile(
        tmp_path / "b.pdf", bookmark=b"\x02", relative_to=tmp_path
    )
    entry = _pristine_entry(
        extra_fields=[
            model.Field(key="bdsk-file-1", value=file_a),
            model.Field(key="bdsk-file-2", value=file_b),
        ]
    )
    assert entry.dirty is False
    entry._set_files([file_b])
    assert entry.files == ["b.pdf"]
    assert entry._entry.fields_dict["bdsk-file-1"].value is file_b
    assert "bdsk-file-2" not in entry._entry.fields_dict
    assert entry.dirty is True


# -- urls ------------------------------------------------------------------- #


def test_urls_getter_setter_roundtrip():
    """`.urls` round-trips a list of URLs in order."""
    entry = Entry("article", "K")
    entry.urls = ["http://example.org/a", "https://example.org/b"]
    assert entry.urls == ["http://example.org/a", "https://example.org/b"]
    assert entry.dirty is True


def test_urls_setter_rejects_invalid_url():
    """An invalid URL raises `ValueError` and does not modify the
    entry."""
    entry = Entry("article", "K")
    with pytest.raises(ValueError):
        entry.urls = ["not a url"]
    assert entry.urls == []


# -- author / editor -------------------------------------------------------- #


def test_author_and_editor():
    """`.author`/`.editor` give structured names; absent fields give
    `[]`."""
    entry = Entry("article", "K")
    entry["author"] = "Goerz, Michael H and Calarco, Tommaso"
    names = entry.author
    assert len(names) == 2
    assert names[0].last == ["Goerz"]
    assert entry.editor == []


# -- copy ------------------------------------------------------------------- #


def test_copy_is_independent():
    """`.copy()` returns an independent entry."""
    entry = Entry("article", "K")
    entry["title"] = "Original"
    copy = entry.copy()
    assert copy.dirty is False
    assert copy.groups == ()
    assert copy["title"] == "Original"

    copy["title"] = "Changed"
    assert entry["title"] == "Original"

    entry["title"] = "Changed Again"
    assert copy["title"] == "Changed"


# -- loading a real entry from refs.bib ------------------------------------- #


@pytest.fixture(name="jpb_entry")
def fixture_jpb_entry():
    """The `GoerzJPB2011` entry from `tests/Refs/refs.bib`, wrapped."""
    text = REFS_BIB.read_text(encoding="utf-8")
    bib = bibtexparser.parse_string(text, parse_stack=parse_stack())
    model_entry = bib.entries_dict["GoerzJPB2011"]
    return Entry._wrap(model_entry)


def test_real_entry_journal_macro(jpb_entry):
    """A bare macro reference is returned normalized (lowercase)."""
    assert jpb_entry["journal"] == "jpb"


def test_real_entry_title_unicode_no_braces(jpb_entry):
    """The title is returned as unicode without enclosing braces."""
    title = jpb_entry["title"]
    assert "{" not in title
    assert "}" not in title
    assert "quantum speed limit" in title


def test_real_entry_files(jpb_entry):
    """`.files` gives the one attached file's relative path."""
    assert jpb_entry.files == ["GoerzJPB11.pdf"]


def test_real_entry_urls(jpb_entry):
    """`.urls` gives the one attached URL."""
    assert jpb_entry.urls == [
        "http://stacks.iop.org/0953-4075/44/i=15/a=154011"
    ]


def test_real_entry_author(jpb_entry):
    """`.author` gives three structured names."""
    assert len(jpb_entry.author) == 3


def test_real_entry_not_dirty_before_mutation(jpb_entry):
    """A freshly loaded (wrapped) entry is not dirty."""
    assert jpb_entry.dirty is False
