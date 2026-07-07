r"""Serialization of a `bibtexparser` library in BibDesk's file format.

BibDesk lays out a `.bib` file as the header comment, the `@string`
definitions, the entries, and finally the group `@comment` blocks.
Blocks are separated by one blank line, except for two blank lines
before the `@string` section and before the first entry. Entry fields
are written one per line, indented with a tab, with the closing brace
fused onto the last field line.

`render_library` serializes a parsed library back to that exact
format: for an unmodified library, the output is byte-identical to the
original file.

```python
>>> import bibtexparser
>>> from bibdeskparser.middleware import parse_stack
>>> from bibdeskparser.writer import render_library
>>> source = (
...     '@article{key1,\n'
...     '\tauthor = {Gr{\\"u}n, Anna},\n'
...     '\tyear = {2026}}\n'
... )
>>> library = bibtexparser.parse_string(source, parse_stack=parse_stack())
>>> library.entries[0]["author"]  # Unicode model ...
'{Grün, Anna}'
>>> render_library(library) == source  # ... but byte-exact output
True

```
"""

from bibtexparser.model import (
    Entry,
    ExplicitComment,
    ImplicitComment,
    ParsingFailedBlock,
    String,
)

from .bdskfile import BibDeskFile
from .header import restore_trailing_space
from .middleware import TeXifyMiddleware

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "render_library",
    "serialize_block",
    "bibdesk_field_order",
    "separator",
]


#: First line of the header comment in files written by BibDesk.
_BIBDESK_HEADER_PREFIX = (
    "%% This BibTeX bibliography file was created using BibDesk"
)


def serialize_block(block):
    r"""Serialize a single block in BibDesk's exact format.

    ```python
    serialize_block(block)
    ```

    Returns the string representation (without trailing newline) of a
    `bibtexparser` block:

    * `ImplicitComment`: the comment text, verbatim. If the comment is
      a BibDesk header, the trailing space that the parser rstripped
      from the last line is restored.
    * `String`: `@string{key = value}`.
    * `ExplicitComment`: `@comment{...}`, with the comment body
      written verbatim.
    * `Entry`: the entry type and key, then one tab-indented line per
      field, with the closing brace directly after the last field
      value. {any}`bibdeskparser.bdskfile.BibDeskFile` values are
      serialized via their
      {any}`~bibdeskparser.bdskfile.BibDeskFile.to_field_value` method.
    * `ParsingFailedBlock` (e.g., a `DuplicateBlockKeyBlock` for an
      entry with a duplicate key): the block's `raw` source slice,
      verbatim, so that files with duplicate keys still round-trip.

    Raises {any}`TypeError` for any other block type.

    ```python
    >>> from bibtexparser.model import Entry, Field, String
    >>> from bibdeskparser.writer import serialize_block
    >>> print(serialize_block(String(key="jpb", value="{J. Phys. B}")))
    @string{jpb = {J. Phys. B}}
    >>> entry = Entry(
    ...     entry_type="article",
    ...     key="key1",
    ...     fields=[
    ...         Field(key="author", value="{Goerz}"),
    ...         Field(key="year", value="{2026}"),
    ...     ],
    ... )
    >>> serialize_block(entry)
    '@article{key1,\n\tauthor = {Goerz},\n\tyear = {2026}}'

    ```
    """
    if isinstance(block, ImplicitComment):
        text = block.comment
        if text.startswith(_BIBDESK_HEADER_PREFIX):
            text = restore_trailing_space(text)
        return text
    if isinstance(block, String):
        return f"@string{{{block.key} = {block.value}}}"
    if isinstance(block, ExplicitComment):
        return f"@comment{{{block.comment}}}"
    if isinstance(block, Entry):
        if not block.fields:
            return f"@{block.entry_type}{{{block.key}}}"
        lines = [f"@{block.entry_type}{{{block.key},"]
        last = len(block.fields) - 1
        for i, field in enumerate(block.fields):
            value = field.value
            if isinstance(value, BibDeskFile):
                value = value.to_field_value()
            tail = "}" if i == last else ","
            lines.append(f"\t{field.key} = {value}{tail}")
        return "\n".join(lines)
    if isinstance(block, ParsingFailedBlock):
        return block.raw
    raise TypeError(f"Unhandled block type: {type(block).__name__}")


def _effective_type(block):
    """The block type to use for separator purposes.

    A `ParsingFailedBlock` counts as the block it wraps
    (`ignore_error_block`), or as an `Entry` if it wraps nothing, since
    failed blocks are almost always broken entries (e.g., duplicate
    keys)."""
    if isinstance(block, ParsingFailedBlock):
        inner = block.ignore_error_block
        return type(inner) if inner is not None else Entry
    return type(block)


def separator(prev_block, cur_block):
    """The blank-line separator BibDesk puts between two blocks.

    ```python
    separator(prev_block, cur_block)
    ```

    Returns `"\\n\\n\\n"` (two blank lines) between the header comment
    and the first `@string`, and between the last `@string` and the
    first entry, i.e., when `prev_block` is an `ImplicitComment` and
    `cur_block` is a `String`, or when `prev_block` is a `String` and
    `cur_block` is an `Entry`. Returns `"\\n\\n"` (one blank line) for
    every other transition. A `ParsingFailedBlock` counts as the block
    it wraps (usually an `Entry` with a duplicate key).
    """
    prev_type = _effective_type(prev_block)
    cur_type = _effective_type(cur_block)
    double = (
        issubclass(prev_type, ImplicitComment) and issubclass(cur_type, String)
    ) or (issubclass(prev_type, String) and issubclass(cur_type, Entry))
    return "\n\n\n" if double else "\n\n"


def render_library(library):
    """Serialize a library to the exact text BibDesk would write.

    ```python
    render_library(library)
    ```

    Returns the full text of the `.bib` file for `library`: all blocks
    serialized with `serialize_block`, joined with `separator`, with a
    final newline. Before serializing, the library is passed through
    `TeXifyMiddleware` on a copy (`allow_inplace_modification=False`),
    so Unicode field values are written as TeX and the caller's
    library is left untouched.
    """
    library = TeXifyMiddleware(allow_inplace_modification=False).transform(
        library
    )
    pieces = []
    prev = None
    for block in library.blocks:
        if prev is not None:
            pieces.append(separator(prev, block))
        pieces.append(serialize_block(block))
        prev = block
    pieces.append("\n")
    return "".join(pieces)


def bibdesk_field_order(fields):
    """Sort entry fields the way BibDesk does.

    ```python
    bibdesk_field_order(fields)
    ```

    Returns the list of `bibtexparser` `Field` objects in `fields`
    sorted case-insensitively alphabetically by key, except that all
    `bdsk-*` fields (file attachments, URLs) come after all other
    fields (each group sorted alphabetically). The sort is stable and
    purely lexical, so, e.g., `bdsk-file-10` sorts *before*
    `bdsk-file-2` (`"1" < "2"`), matching the field order in files
    written by BibDesk.

    This helper is not used by `render_library` (which writes fields
    in their existing order); it is intended for normalizing the field
    order of newly created or modified entries.

    ```python
    >>> from bibtexparser.model import Field
    >>> from bibdeskparser.writer import bibdesk_field_order
    >>> fields = [
    ...     Field(key="bdsk-url-1", value="{http://example.org}"),
    ...     Field(key="year", value="{2026}"),
    ...     Field(key="author", value="{Goerz, Michael}"),
    ... ]
    >>> [field.key for field in bibdesk_field_order(fields)]
    ['author', 'year', 'bdsk-url-1']

    ```
    """

    def sort_key(field):
        key = field.key.lower()
        return (key.startswith("bdsk-"), key)

    return sorted(fields, key=sort_key)
