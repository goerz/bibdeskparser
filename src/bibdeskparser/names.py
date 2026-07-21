r"""Read-only structured view of person-name fields (`author`, `editor`).

BibDesk stores the `author`/`editor` field as a flat, de-TeXified Unicode
string, e.g. `"Goerz, Michael H and Calarco, Tommaso"`, and only *derives*
a structured representation (first/von/last/Jr name parts) for display in
its UI; it never re-serializes that structured view back to the field.
This module mirrors that: `structured_names` builds a read-only
`list` of `NameParts` on demand, using `bibtexparser`'s own name-splitting
middlewares (`RemoveEnclosingMiddleware`, `SeparateCoAuthors`,
`SplitNameParts`), run on a throwaway single-field `Entry` wrapped in a
throwaway `bibtexparser.Library` so that the caller's real entry is never
touched.

`bibdeskparser` never uses this pipeline for *writing*: `bibtexparser`
also provides a `MergeNameParts` middleware that goes the other way
(`NameParts` -> string), but round-tripping through it is lossy. For
example, a LaTeX tie in `Koch, C.~P.` would be rewritten as `Koch, C. P.`,
silently losing the non-breaking space BibDesk's own editor preserves.
So `author`/`editor` stay plain strings in the dict interface, and
`structured_names` is only ever used to build the read-only
`Entry.author`/`Entry.editor` properties.
"""

import bibtexparser
from bibtexparser.middlewares import (
    RemoveEnclosingMiddleware,
    SeparateCoAuthors,
    SplitNameParts,
)
from bibtexparser.model import Entry, Field

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["structured_names"]


def structured_names(value, allow_inplace_modification=True):
    r"""Parse a raw `author`/`editor` field value into structured names.

    ```python
    structured_names(value, allow_inplace_modification=True)
    ```

    * `value`: the raw field value string, e.g.
      `"{Goerz, Michael H and Calarco, Tommaso}"` (with or without its
      enclosing `{...}`/`"..."` delimiters) or `""`/`None` for a missing
      field.
    * `allow_inplace_modification`: passed through to the underlying
      `bibtexparser` middlewares (see the `bibtexparser`
      `Middleware` base class).

    Returns a `list` of `bibtexparser.middlewares.names.NameParts`, each
    with `.first`, `.von`, `.last`, `.jr` attributes (each a `list` of
    strings), in the order the names appear in `value`. Returns `[]` if
    `value` is empty or `None`. Raises `bibtexparser`'s
    `InvalidNameError` (a subclass of {exc}`ValueError`) if `value`
    cannot be split into names (e.g. a name with too many commas).

    This is a **read-only derived view**: BibDesk stores `author` and
    `editor` as flat Unicode strings and only derives a structured
    representation for display, so `bibdeskparser` never writes through
    this pipeline (see the module docstring for why re-serializing via
    `MergeNameParts` would be lossy).

    ```python
    >>> from bibdeskparser.names import structured_names
    >>> names = structured_names(
    ...     "Goerz, Michael H and Calarco, Tommaso and Koch, Christiane P"
    ... )
    >>> [n.last for n in names]
    [['Goerz'], ['Calarco'], ['Koch']]
    >>> names[0].first
    ['Michael', 'H']
    >>> structured_names("")
    []
    >>> structured_names(None)
    []

    ```
    """
    if not value:
        return []
    field = Field(key="author", value=value)
    entry = Entry(entry_type="article", key="probe", fields=[field])
    library = bibtexparser.Library([entry])
    for middleware in (
        RemoveEnclosingMiddleware(
            allow_inplace_modification=allow_inplace_modification
        ),
        SeparateCoAuthors(
            allow_inplace_modification=allow_inplace_modification
        ),
        SplitNameParts(allow_inplace_modification=allow_inplace_modification),
    ):
        library = middleware.transform(library)
    if library.failed_blocks:
        # The name middlewares do not raise on an unparseable name;
        # they replace the entry with a `MiddlewareErrorBlock` that
        # carries the original `InvalidNameError`.
        raise library.failed_blocks[0].error
    return library.entries[0].fields_dict["author"].value
