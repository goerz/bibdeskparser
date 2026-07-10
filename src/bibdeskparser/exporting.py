r"""Serialization of `Entry` objects to bibtex text ("export" snippets).

Provides {func}`export_entries`, which renders one or more
{class}`bibdeskparser.entry.Entry` objects to a bibtex snippet in one of
three formats:

- `"default"`: every stored field except the BibDesk bookkeeping fields
  (`date-added`/`date-modified`) and the `bdsk-*` fields -- i.e., the
  `Entry` dict interface plus `keywords` -- Unicode and detexified,
  plus the entry's `bdsk-file-N`/`bdsk-url-N` fields rendered as plain
  relative paths/URLs. This is the format used to build the temporary
  file shown to `$EDITOR` (see the later `editing.py` module): it is
  re-parseable and its fields can be merged back into an `Entry` (the
  `bdsk-file`/`bdsk-url` and `keywords` lines are merged via their
  dedicated properties, not the dict interface, since those fields are
  not part of it).
- `"raw"`: the same field set/order as `"default"`, but field values are
  the literal TeX-encoded text as stored (i.e., exactly what would end
  up in a `.bib` file on disk), rather than the decoded Unicode dict
  values.
- `"minimal"`: a small, LaTeX-bibliography-oriented whitelist of fields
  per entry type, covering `article`, `inproceedings`, `incollection`,
  `mastersthesis`, and `phdthesis`, with a best-effort
  `author, title, year` fallback for every other entry type.

For `"default"` and `"raw"`, an optional `strings` mapping of macro name
to Unicode value (e.g., `library.strings`) is used to prepend `@string`
definitions for every macro name that is actually referenced (as a bare
field value) by the selected entries, so the exported snippet is
self-contained. `"minimal"` never emits `@string` definitions. The
`keywords` field is always literal text, never a macro reference: its
value is always rendered braced, and it never pulls in an `@string`
definition, even when a keyword happens to match a macro name.

This module intentionally does not import `bibdeskparser.library`
(which imports this module), to avoid a circular dependency.

```python
>>> from bibdeskparser.entry import Entry
>>> from bibdeskparser.exporting import export_entries
>>> entry = Entry(
...     "article",
...     "Key2024",
...     fields={"author": "Jane Doe", "title": "A Title", "year": "2024"},
... )
>>> text = export_entries([entry])
>>> text == (
...     "@article{Key2024,\n"
...     "\tauthor = {Jane Doe},\n"
...     "\ttitle = {A Title},\n"
...     "\tyear = {2024}\n"
...     "}\n"
... )
True

```
"""

import re

from .bdskfile import BibDeskFile
from .macros import is_valid_macro_name, normalize_macro_name
from .writer import bibdesk_field_order

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["export_entries"]

_FORMATS = frozenset(("default", "raw", "minimal"))

#: Non-normal field keys (never part of any exported format's field
#: list; `bdsk-file-N`/`bdsk-url-N` are handled separately).
_DATE_KEYS = frozenset(("date-added", "date-modified"))

_BDSK_FILE_RE = re.compile(r"bdsk-file-(\d+)$", re.IGNORECASE)
_BDSK_URL_RE = re.compile(r"bdsk-url-(\d+)$", re.IGNORECASE)

#: Per-entry-type field whitelist for the `"minimal"` format.
_MINIMAL_FIELDS = {
    "article": (
        "author",
        "title",
        "journal",
        "year",
        "doi",
        "pages",
        "volume",
        "number",
    ),
    "inproceedings": (
        "author",
        "title",
        "booktitle",
        "year",
        "doi",
        "pages",
        "address",
        "editor",
    ),
    "incollection": (
        "author",
        "title",
        "booktitle",
        "year",
        "doi",
        "pages",
        "editor",
        "publisher",
        "volume",
    ),
    "mastersthesis": ("author", "title", "school", "year"),
    "phdthesis": ("author", "title", "school", "year"),
}

#: Best-effort fallback whitelist for any entry type not covered by
#: `_MINIMAL_FIELDS` (e.g. `book`, `misc`, `techreport`,
#: `unpublished`, ...). Not tuned per type -- just enough for a minimal
#: citation.
_MINIMAL_FALLBACK = ("author", "title", "year")


def _is_normal_field(key):
    """Whether `key` is exported as a regular field: not a
    `date-added`/`date-modified`/`bdsk-*` field. This includes
    `keywords`, which `Entry`'s dict interface hides."""
    lkey = key.lower()
    return lkey not in _DATE_KEYS and not lkey.startswith("bdsk-")


def _normal_fields(entry):
    """The "normal" `Field` objects of `entry`, in BibDesk's field
    order."""
    fields = [f for f in entry._entry.fields if _is_normal_field(f.key)]
    return bibdesk_field_order(fields)


def _strip_braces(value):
    """Strip one matching pair of enclosing `{...}`/`"..."`, if
    present."""
    if isinstance(value, str) and len(value) >= 2:
        if (value[0] == "{" and value[-1] == "}") or (
            value[0] == '"' and value[-1] == '"'
        ):
            return value[1:-1]
    return value


def _render_value(value):
    """Render a Unicode field value: bare if it's a normalized macro
    name, else braced."""
    if is_valid_macro_name(value, normalized=True):
        return value
    return "{" + value + "}"


def _bdsk_bodies(entry):
    """`"name = value"` bodies (no trailing comma/newline) for
    `entry`'s `bdsk-file-N`/`bdsk-url-N` fields, in numeric order:
    files (as plain relative paths) before URLs (brace-stripped)."""
    file_fields = []
    url_fields = []
    for field in entry._entry.fields:
        match = _BDSK_FILE_RE.match(field.key)
        if match:
            file_fields.append((int(match.group(1)), field))
            continue
        match = _BDSK_URL_RE.match(field.key)
        if match:
            url_fields.append((int(match.group(1)), field))
    file_fields.sort(key=lambda item: item[0])
    url_fields.sort(key=lambda item: item[0])
    bodies = []
    for index, field in file_fields:
        value = field.value
        if isinstance(value, BibDeskFile):
            path = value.relative_path
        else:
            path = BibDeskFile.from_field_value(value).relative_path
        bodies.append(f"bdsk-file-{index} = {{{path}}}")
    for index, field in url_fields:
        url = _strip_braces(field.value)
        bodies.append(f"bdsk-url-{index} = {{{url}}}")
    return bodies


def _entry_bodies(entry, fmt):
    """`"name = value"` bodies (no trailing comma/newline), in order,
    for `entry` in the `"default"`/`"raw"` formats."""
    bodies = []
    for field in _normal_fields(entry):
        name = field.key.lower()
        if fmt == "raw":
            bodies.append(f"{name} = {field.value}")
        else:
            # `entry._decode` rather than `entry[field.key]`: the
            # decoding is identical, but the dict interface hides
            # `keywords`, which is still exported.
            value = entry._decode(field.key, field.value)
            if name == "keywords":
                # Keywords are always literal text, never a macro
                # reference: a one-word macro-shaped keyword must not
                # be rendered bare.
                bodies.append(f"{name} = {{{value}}}")
            else:
                bodies.append(f"{name} = {_render_value(value)}")
    bodies.extend(_bdsk_bodies(entry))
    return bodies


def _render_entry(entry, fmt):
    """Render a single `entry` (`"default"`/`"raw"`/`"minimal"`)."""
    if fmt == "minimal":
        return _render_minimal_entry(entry)
    bodies = _entry_bodies(entry, fmt)
    lines = [f"@{entry.entry_type}{{{entry.key},\n"]
    last = len(bodies) - 1
    for i, body in enumerate(bodies):
        tail = "" if i == last else ","
        lines.append(f"\t{body}{tail}\n")
    lines.append("}\n")
    return "".join(lines)


def _render_minimal_entry(entry):
    """Render a single `entry` in the `"minimal"` format."""
    whitelist = _MINIMAL_FIELDS.get(entry.entry_type.lower())
    if whitelist is None:
        whitelist = _MINIMAL_FALLBACK
    lines = [f"@{entry.entry_type}{{{entry.key},\n"]
    for name in whitelist:
        value = entry.get(name)
        if not value:
            continue
        lines.append(f"    {name.capitalize()} = {_render_value(value)},\n")
    lines.append("}\n")
    return "".join(lines)


def _is_bare(value):
    """Whether `value` is a string with no enclosing `{...}`/`"..."`
    (a bare macro reference, per BibDesk's convention)."""
    return isinstance(value, str) and bool(value) and value[0] not in '{"'


def _referenced_macro_names(entries):
    """The set of (normalized) macro names referenced as a bare field
    value by any entry in `entries`.

    The `keywords` field never counts as a macro reference (keywords
    are always literal text), so it never pulls in an `@string`
    definition."""
    names = set()
    for entry in entries:
        for field in entry._entry.fields:
            value = field.value
            if (
                _is_bare(value)
                and field.key.lower() != "keywords"
                and is_valid_macro_name(value, normalized=False)
            ):
                names.add(normalize_macro_name(value))
    return names


def _string_lines(entries, strings):
    """`@string{name = {value}}` lines for every macro referenced by
    `entries` that is defined in `strings`, sorted by name."""
    if not strings:
        return []
    names = sorted(
        name for name in _referenced_macro_names(entries) if name in strings
    )
    return [
        "@string{" + name + " = {" + strings[name] + "}}\n" for name in names
    ]


def export_entries(
    entries, strings=None, format="default", outfile=None
):  # pylint: disable=redefined-builtin
    """Serialize `entries` (an iterable of `Entry`) to bibtex text.

    ```python
    export_entries(entries, strings=None, format="default", outfile=None)
    ```

    Returns the text as a `str` if `outfile` is `None`, else writes it
    (UTF-8) to `outfile` and returns `None`.

    # Arguments

    * `entries`: an iterable of {class}`bibdeskparser.entry.Entry`.
    * `strings`: an optional `dict` mapping macro name to its Unicode
      value (e.g. `library.strings`), used to prepend `@string`
      definitions for every macro actually referenced by `entries`
      (see the module docstring); ignored for `format="minimal"`. A
      referenced macro not found in `strings` is silently skipped (not
      an error -- this is a best-effort self-containment feature, not
      a validator).
    * `format`: one of `"default"`, `"raw"`, `"minimal"` (see the
      module docstring); raises {exc}`ValueError` for any other value.
    * `outfile`: if given, a path (`str`/`pathlib.Path`) or an
      already-open text file object (anything with a `write` method;
      if already open, it is written to but not closed).

    Multiple entries are separated by a single blank line; the returned
    (or written) text always ends with exactly one trailing newline.
    """
    if format not in _FORMATS:
        raise ValueError(
            f"format must be one of {sorted(_FORMATS)}, not {format!r}"
        )
    entries = list(entries)
    pieces = []
    if format != "minimal":
        string_lines = _string_lines(entries, strings)
        if string_lines:
            pieces.append("".join(string_lines))
            pieces.append("\n")
    pieces.append("\n".join(_render_entry(entry, format) for entry in entries))
    text = "".join(pieces)
    if outfile is None:
        return text
    if hasattr(outfile, "write"):
        outfile.write(text)
        return None
    with open(outfile, "w", encoding="utf-8") as fh:
        fh.write(text)
    return None
