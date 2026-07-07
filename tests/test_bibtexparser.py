"""Tests pinning the `bibtexparser` API that `bibdeskparser` relies on.

The `bibtexparser` v2 API is undocumented and unstable. This module
defines and verifies *every* assumption that `bibdeskparser` makes about
`bibtexparser`, so that a future version bump that changes any of these
behaviors fails loudly here, rather than causing subtle breakage
elsewhere. The tests are written against the installed
``bibtexparser==2.0.0b9``.
"""

import bibtexparser
import pytest
from bibtexparser import Library, model
from bibtexparser.middlewares import (
    RemoveEnclosingMiddleware,
    SeparateCoAuthors,
    SplitNameParts,
)
from bibtexparser.middlewares.middleware import BlockMiddleware


def _make_entry(key, **fields):
    """Construct a minimal `Entry` with the given key and fields."""
    return model.Entry(
        entry_type="article",
        key=key,
        fields=[model.Field(key=k, value=v) for (k, v) in fields.items()],
    )


BIBTEX = """\
@string{jpb = {J. Phys. B}}

@article{key1,
    author = {Goerz, Michael H. and Anderson, Randy},
    title = {Some Title},
    journal = jpb,
}
"""


# 1. parse_string / parse_file with an empty parse stack


def test_parse_string_empty_stack_no_string_interpolation():
    """With ``parse_stack=[]``, `@string` macros are not interpolated."""
    bib = bibtexparser.parse_string(BIBTEX, parse_stack=[])
    entry = bib.entries[0]
    assert entry["journal"] == "jpb"


def test_parse_string_empty_stack_keeps_enclosing_braces():
    """With ``parse_stack=[]``, field values keep their braces."""
    bib = bibtexparser.parse_string(BIBTEX, parse_stack=[])
    entry = bib.entries[0]
    assert entry["title"] == "{Some Title}"


def test_parse_string_empty_stack_string_value_keeps_braces():
    """With ``parse_stack=[]``, `@string` values keep their braces."""
    bib = bibtexparser.parse_string(BIBTEX, parse_stack=[])
    string = bib.strings[0]
    assert string.key == "jpb"
    assert string.value == "{J. Phys. B}"


def test_parse_file_accepts_parse_stack(tmp_path):
    """``parse_file`` exists and accepts a ``parse_stack`` argument."""
    path = tmp_path / "test.bib"
    path.write_text(BIBTEX, encoding="utf-8")
    bib = bibtexparser.parse_file(str(path), parse_stack=[])
    entry = bib.entries[0]
    assert entry.key == "key1"
    assert entry["journal"] == "jpb"
    assert entry["title"] == "{Some Title}"


# 2. Library


def test_library_constructor_accepts_blocks():
    """``Library(blocks=...)`` preserves the given blocks in order."""
    e1 = _make_entry("a")
    e2 = _make_entry("b")
    bib = Library(blocks=[e1, e2])
    assert bib.blocks == [e1, e2]
    assert bib.entries == [e1, e2]


def test_library_constructor_rejects_fail_on_duplicate_key():
    """The ``Library`` constructor does *not* take
    ``fail_on_duplicate_key`` in v2.0.0b9; the flag exists on ``add()``
    (default `False`) and ``replace()`` (default `True`) instead."""
    with pytest.raises(TypeError):
        Library(blocks=[], fail_on_duplicate_key=False)


def test_library_properties():
    """A parsed ``Library`` exposes the expected accessor properties."""
    source = BIBTEX + "\n@comment{BibDesk metadata}\n"
    bib = bibtexparser.parse_string(source, parse_stack=[])
    assert [type(b).__name__ for b in bib.blocks] == [
        "String",
        "Entry",
        "ExplicitComment",
    ]
    assert [e.key for e in bib.entries] == ["key1"]
    assert set(bib.entries_dict.keys()) == {"key1"}
    assert bib.entries_dict["key1"] is bib.entries[0]
    assert [s.key for s in bib.strings] == ["jpb"]
    assert bib.strings_dict["jpb"] is bib.strings[0]
    assert bib.failed_blocks == []
    assert [c.comment for c in bib.comments] == ["BibDesk metadata"]


def test_library_add():
    """``Library.add`` appends a block."""
    bib = Library(blocks=[_make_entry("a")])
    new = _make_entry("b")
    bib.add(new)
    assert [e.key for e in bib.entries] == ["a", "b"]


def test_library_add_duplicate_key():
    """``Library.add`` with ``fail_on_duplicate_key=False`` (the
    default) turns a duplicate into a failed block instead of
    raising."""
    bib = Library(blocks=[_make_entry("a")])
    bib.add(_make_entry("a"), fail_on_duplicate_key=False)
    assert [e.key for e in bib.entries] == ["a"]
    assert len(bib.failed_blocks) == 1
    assert isinstance(bib.failed_blocks[0], model.DuplicateBlockKeyBlock)
    with pytest.raises(ValueError):
        bib.add(_make_entry("a"), fail_on_duplicate_key=True)


def test_library_remove():
    """``Library.remove`` removes a block."""
    e1 = _make_entry("a")
    e2 = _make_entry("b")
    bib = Library(blocks=[e1, e2])
    bib.remove(e1)
    assert bib.entries == [e2]
    assert bib.blocks == [e2]


def test_library_replace():
    """``Library.replace`` swaps a block in place, preserving order."""
    e1 = _make_entry("a")
    e2 = _make_entry("b")
    bib = Library(blocks=[e1, e2])
    new = _make_entry("c")
    bib.replace(e1, new)
    assert [e.key for e in bib.entries] == ["c", "b"]


# 3. Duplicate entry keys when parsing


DUPLICATE_BIBTEX = """\
@article{key1, title = {First}}
@article{key1, title = {Second}}
"""


def test_duplicate_keys_first_entry_wins():
    """With duplicate keys, ``entries_dict`` maps to the first entry."""
    bib = bibtexparser.parse_string(DUPLICATE_BIBTEX, parse_stack=[])
    assert bib.entries_dict["key1"]["title"] == "{First}"


def test_duplicate_keys_second_entry_is_failed_block():
    """The duplicate becomes a ``DuplicateBlockKeyBlock`` in
    ``failed_blocks`` (with ``.key`` and ``.raw``), not an entry."""
    bib = bibtexparser.parse_string(DUPLICATE_BIBTEX, parse_stack=[])
    assert len(bib.entries) == 1
    assert len(bib.failed_blocks) == 1
    failed = bib.failed_blocks[0]
    assert isinstance(failed, model.DuplicateBlockKeyBlock)
    assert failed.key == "key1"
    assert failed.raw == "@article{key1, title = {Second}}"


# 4. bibtexparser.model


def test_entry_attributes():
    """A parsed ``Entry`` has type, key, and ordered fields."""
    bib = bibtexparser.parse_string(BIBTEX, parse_stack=[])
    entry = bib.entries[0]
    assert entry.entry_type == "article"
    assert entry.key == "key1"
    assert [f.key for f in entry.fields] == ["author", "title", "journal"]
    assert all(isinstance(f, model.Field) for f in entry.fields)
    assert entry.fields_dict["journal"].value == "jpb"


def test_entry_getitem_returns_field_value():
    """Dict-like ``entry[key]`` access returns the field *value*."""
    bib = bibtexparser.parse_string(BIBTEX, parse_stack=[])
    entry = bib.entries[0]
    assert entry["journal"] == "jpb"


def test_entry_set_field():
    """``set_field`` appends a new field or overwrites an existing
    one."""
    entry = _make_entry("a", title="T")
    entry.set_field(model.Field(key="year", value="2024"))
    assert [(f.key, f.value) for f in entry.fields] == [
        ("title", "T"),
        ("year", "2024"),
    ]
    entry.set_field(model.Field(key="title", value="T2"))
    assert [(f.key, f.value) for f in entry.fields] == [
        ("title", "T2"),
        ("year", "2024"),
    ]


def test_entry_construction():
    """``Entry`` and ``Field`` can be constructed directly."""
    entry = model.Entry(
        entry_type="article",
        key="key1",
        fields=[model.Field(key="title", value="T")],
    )
    assert entry.entry_type == "article"
    assert entry.key == "key1"
    assert entry["title"] == "T"


def test_field_is_mutable():
    """``Field(key=..., value=...)`` has mutable key and value."""
    field = model.Field(key="title", value="T")
    field.key = "booktitle"
    field.value = "T2"
    assert field.key == "booktitle"
    assert field.value == "T2"


def test_string_model():
    """``String`` has ``.key`` and ``.value``."""
    string = model.String(key="jpb", value="{J. Phys. B}")
    assert string.key == "jpb"
    assert string.value == "{J. Phys. B}"


def test_comment_models():
    """``ExplicitComment`` and ``ImplicitComment`` have ``.comment``."""
    assert model.ExplicitComment("meta").comment == "meta"
    assert model.ImplicitComment("% note").comment == "% note"


# 5. Block.raw


def test_raw_is_exact_source_slice():
    """After parsing, each block's ``.raw`` is the exact slice of the
    source text."""
    source = BIBTEX + "\n%% trailing comment\n"
    bib = bibtexparser.parse_string(source, parse_stack=[])
    assert bib.strings[0].raw == "@string{jpb = {J. Phys. B}}"
    assert bib.entries[0].raw == (
        "@article{key1,\n"
        "    author = {Goerz, Michael H. and Anderson, Randy},\n"
        "    title = {Some Title},\n"
        "    journal = jpb,\n"
        "}"
    )
    assert bib.comments[0].raw == "%% trailing comment"
    for block in bib.blocks:
        assert block.raw in source


class _RewriteTitle(BlockMiddleware):
    """Middleware that overwrites each entry's title field."""

    def transform_entry(self, entry, bib):
        entry.fields_dict["title"].value = "MUTATED"
        return entry


def test_raw_not_updated_by_middleware():
    """Mutating a field via a middleware leaves ``.raw`` unchanged."""
    bib = bibtexparser.parse_string(BIBTEX, parse_stack=[])
    raw_before = bib.entries[0].raw
    transformed = _RewriteTitle(allow_inplace_modification=False).transform(
        bib
    )
    entry = transformed.entries[0]
    assert entry["title"] == "MUTATED"
    assert entry.raw == raw_before


# 6. BlockMiddleware


class _Marker:
    """Arbitrary non-str object used as a field/comment value."""


class _ObjectInjector(BlockMiddleware):
    """Middleware replacing values with arbitrary Python objects."""

    def transform_entry(self, entry, bib):
        entry.fields_dict["title"].value = _Marker()
        return entry

    def transform_string(self, string, bib):
        string.value = _Marker()
        return string

    def transform_explicit_comment(self, comment, bib):
        comment.comment = _Marker()
        return comment


def test_block_middleware_hooks():
    """Subclassing ``BlockMiddleware`` with per-block-type
    ``transform_*`` hooks works; ``.transform(library)`` returns a
    ``Library``; hooks may replace values with arbitrary (non-str)
    Python objects, including an ``ExplicitComment``'s ``.comment``."""
    source = BIBTEX + "\n@comment{BibDesk metadata}\n"
    bib = bibtexparser.parse_string(source, parse_stack=[])
    middleware = _ObjectInjector(allow_inplace_modification=False)
    transformed = middleware.transform(bib)
    assert isinstance(transformed, Library)
    assert isinstance(transformed.entries[0]["title"], _Marker)
    assert isinstance(transformed.strings[0].value, _Marker)
    assert isinstance(transformed.comments[0].comment, _Marker)


# 7. Name handling middlewares


NAMES_BIBTEX = """\
@article{key1,
    author = {Goerz, Michael H. and Ludwig van Beethoven
              and Ford, Jr., Henry},
    title = {Some Title},
}
"""


def test_remove_enclosing_middleware():
    """``RemoveEnclosingMiddleware`` strips braces from field values."""
    bib = bibtexparser.parse_string(NAMES_BIBTEX, parse_stack=[])
    bib = RemoveEnclosingMiddleware().transform(bib)
    assert bib.entries[0]["title"] == "Some Title"


def test_separate_coauthors():
    """``SeparateCoAuthors`` splits an author value on " and "."""
    bib = bibtexparser.parse_string(NAMES_BIBTEX, parse_stack=[])
    bib = RemoveEnclosingMiddleware().transform(bib)
    bib = SeparateCoAuthors().transform(bib)
    assert bib.entries[0]["author"] == [
        "Goerz, Michael H.",
        "Ludwig van Beethoven",
        "Ford, Jr., Henry",
    ]


def test_split_name_parts():
    """``SplitNameParts`` turns author strings into ``NameParts`` with
    ``first``/``von``/``last``/``jr`` list attributes."""
    bib = bibtexparser.parse_string(NAMES_BIBTEX, parse_stack=[])
    bib = RemoveEnclosingMiddleware().transform(bib)
    bib = SeparateCoAuthors().transform(bib)
    bib = SplitNameParts().transform(bib)
    goerz, beethoven, ford = bib.entries[0]["author"]
    assert goerz.first == ["Michael", "H."]
    assert goerz.von == []
    assert goerz.last == ["Goerz"]
    assert goerz.jr == []
    assert beethoven.first == ["Ludwig"]
    assert beethoven.von == ["van"]
    assert beethoven.last == ["Beethoven"]
    assert beethoven.jr == []
    assert ford.first == ["Henry"]
    assert ford.von == []
    assert ford.last == ["Ford"]
    assert ford.jr == ["Jr."]


# 8. Implicit-comment whitespace handling


def test_implicit_comment_whitespace():
    """Free text between blocks becomes ``ImplicitComment`` blocks.

    Pin the exact v2.0.0b9 behavior: consecutive comment lines that are
    separated only by blank lines are merged into a *single*
    ``ImplicitComment`` (internal blank lines preserved verbatim);
    leading blank lines before a comment are dropped, and trailing
    whitespace is rstripped. Inter-block blank-line counts are thus NOT
    preserved by bibtexparser.
    """
    source = "\n\n%% line one\n\n\n%% line two\n\n@article{k, title = {T}}\n"
    bib = bibtexparser.parse_string(source, parse_stack=[])
    assert [type(b).__name__ for b in bib.blocks] == [
        "ImplicitComment",
        "Entry",
    ]
    comment = bib.blocks[0]
    assert comment.comment == "%% line one\n\n\n%% line two"
    assert comment.raw == "%% line one\n\n\n%% line two"


def test_blank_lines_between_entries_produce_no_blocks():
    """Whitespace-only text between entries yields no comment block, so
    blank-line separation between entries is lost entirely."""
    source = "@article{a, title = {A}}\n\n\n\n@article{b, title = {B}}\n"
    bib = bibtexparser.parse_string(source, parse_stack=[])
    assert [type(b).__name__ for b in bib.blocks] == ["Entry", "Entry"]


# 9. parse_file reads UTF-8


def test_parse_file_reads_utf8(tmp_path):
    """``parse_file`` decodes UTF-8 file content by default."""
    source = "@article{key1,\n  title = {Präzision π},\n}\n"
    path = tmp_path / "utf8.bib"
    path.write_text(source, encoding="utf-8")
    bib = bibtexparser.parse_file(str(path), parse_stack=[])
    assert bib.entries[0]["title"] == "{Präzision π}"
