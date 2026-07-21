r"""Serialization of `Entry` objects to bibtex text ("export" snippets).

Provides {func}`export_entries`, which renders one or more
{class}`bibdeskparser.entry.Entry` objects to a bibtex snippet. Three
independent parameters control the output:

- `unicode` (default `True`): with `True`, field values are the Unicode
  text also returned by the `Entry` dict interface; with `False`, they
  are TeX-encoded, exactly as they would be written to the `.bib` file
  on disk (URL and `bdsk-*` fields are exempt from TeX encoding,
  matching BibDesk).
- `expand_strings` (default `False`): with `False`, a bare `@string`
  macro reference stays a bare reference, and the `@string` definitions
  for every macro referenced by the selected fields are prepended, so
  the snippet is self-contained; with `True`, each reference is
  replaced by the macro's (braced) value, resolved against `strings`
  plus the standard BibTeX month macros, and no `@string` definitions
  are emitted. An unresolvable reference stays bare, with a
  `UserWarning`.
- `fields` (default `"full"`): which fields to include. `"full"`
  includes every stored field except the BibDesk bookkeeping fields
  (`date-added`/`date-modified`), in BibDesk's field order, plus the
  entry's `bdsk-file-N`/`bdsk-url-N` fields rendered as plain relative
  paths/URLs. `"minimal"` restricts each entry to a small,
  LaTeX-bibliography-oriented whitelist of fields per entry type
  (covering `article`, `inproceedings`, `incollection`,
  `mastersthesis`, and `phdthesis`, with a best-effort
  `author, title, year` fallback for every other entry type). An
  explicit list of field names selects exactly those fields, in the
  given order (a name not defined on an entry is silently omitted).

A *preprint-only* entry -- a `misc` (or `unpublished`) entry with an
`eprint` from a recognized preprint archive, or any entry whose
`journal` is a recognized preprint pseudo-journal like
`arXiv:2205.15044` -- is exported in the form selected by the
`preprint` parameter, whatever its stored form:

- `preprint="unpublished"` (the default, via the `preprint_export`
  [configuration](configuration) setting): an `@unpublished` entry
  carrying the structured `eprint`/`archiveprefix` fields (derived
  from the pseudo-journal if not stored). A minimal export reduces
  to `author`/`title`/`eprint`/`archiveprefix`/`primaryclass`/
  `doi`/`year` (plus any stored `url`), with the entry type's
  required `note` field guaranteed: the stored `note` (typically a
  status like "submitted to Phys. Rev. A"), or the text "preprint".
  A full export keeps all other stored fields (including a stored
  pseudo-journal, which every BibTeX style ignores on `unpublished`
  and `misc` entries) and never synthesizes the `note`, so that a
  full-export round trip cannot plant one in a library.
- `preprint="misc"`: the same structured form as a `@misc` entry
  (no `note` handling -- `@misc` has no required fields).
- `preprint="article"`: an `@article` whose `journal` is the
  canonical pseudo-journal and whose `url` is the DOI-resolver
  address of the entry's `doi` (else the stored `url`, else the
  archive's page for the identifier); the
  `eprint`/`archiveprefix`/`primaryclass`/`doi` fields are omitted.
  A minimal export reduces to `author`/`title`/`journal`/`url`/
  `note`/`year`.
- `preprint="stored"`: no transformation; the entry is exported
  exactly as stored.

For a non-arXiv archive whose URL template has the form
`<base>/{id}` (HAL, bioRxiv, medRxiv by default), the structured
forms also emit an `archive` field holding the base URL: REVTeX's
`apsrev4-x`/`aipnum4-x` styles use it as the link base of the
rendered eprint (their built-in default is arXiv's). The same
`archive` field is appended to any full or minimal export of a
*published* entry whose `eprint` names such an archive. A stored
`archive` field is always written as-is, never overwritten.

An explicit list of field names always exports the stored fields,
and the stored entry is never modified by an export.

Every export uses the same layout, independent of these parameters:
fields indented with four spaces, capitalized field names (`Author`,
`Bdsk-File-1`), a comma after every field, and the closing brace on
its own line. Reproducing the byte-exact layout of the `.bib` file on
disk is the job of `bibdeskparser.writer`, not of exports; likewise,
no export is a byte-faithful slice of the file even with
`unicode=False`: `bdsk-file-N` values are rendered as plain paths (not
the stored binary plist data), and the `date-added`/`date-modified`
fields are omitted unless requested by name.

The `keywords` field is always literal text, never a macro reference:
its value is always rendered braced, it never pulls in an `@string`
definition, and it is never expanded, even when a keyword happens to
match a macro name.

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
>>> print(export_entries([entry]), end="")
@article{Key2024,
    Author = {Jane Doe},
    Title = {A Title},
    Year = {2024},
}

```
"""

import re
import warnings

from bibtexparser.model import Field

from .bdskfile import BibDeskFile
from .config import active
from .identifiers import (
    _archive_base,
    _archive_url,
    _entry_preprint,
    _strip_eprint_version,
)
from .macros import STANDARD_MACROS, is_valid_macro_name, normalize_macro_name
from .texmap import skip_texify, texify
from .writer import bibdesk_field_order

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["export_entries"]

#: Non-normal field keys (never part of the `"full"` field list;
#: `bdsk-file-N`/`bdsk-url-N` are handled separately).
_DATE_KEYS = frozenset(("date-added", "date-modified"))

_BDSK_FILE_RE = re.compile(r"bdsk-file-(\d+)$", re.IGNORECASE)
_BDSK_URL_RE = re.compile(r"bdsk-url-(\d+)$", re.IGNORECASE)

#: Per-entry-type field whitelist for `fields="minimal"`. The
#: `eprint`/`archiveprefix`/`primaryclass` fields of an `article`
#: give a "published, with preprint" reference under eprint-aware
#: styles like REVTeX (and are ignored by classic styles).
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
        "eprint",
        "archiveprefix",
        "archive",
        "primaryclass",
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

#: The fields of a minimal `preprint="misc"` export of a
#: preprint-only entry: the structured eprint fields plus the DOI
#: (and any stored `url`, the hyperlink of last resort for archives
#: whose identifiers a style would mislink -- REVTeX's eprint links
#: always point at arxiv.org). A stored `note` (typically a status
#: like "submitted to Phys. Rev. A") is kept: styles render it after
#: the reference.
_PREPRINT_MISC_FIELDS = (
    "author",
    "title",
    "eprint",
    "archiveprefix",
    "archive",
    "primaryclass",
    "doi",
    "url",
    "note",
    "year",
)

#: The fields of a minimal `preprint="article"` export of a
#: preprint-only entry: the pseudo-journal, hyperlinked via `url`
#: (plus any stored status `note`).
_PREPRINT_ARTICLE_FIELDS = (
    "author",
    "title",
    "journal",
    "url",
    "note",
    "year",
)


def _is_normal_field(key):
    """Whether `key` is part of the `"full"` field list as a regular
    field: not a `date-added`/`date-modified`/`bdsk-*` field. This
    includes `keywords`, which `Entry`'s dict interface hides."""
    lkey = key.lower()
    return lkey not in _DATE_KEYS and not lkey.startswith("bdsk-")


def _normal_fields(entry):
    """The "normal" `Field` objects of `entry`, in BibDesk's field
    order."""
    fields = [f for f in entry._entry.fields if _is_normal_field(f.key)]
    return bibdesk_field_order(fields)


def _bdsk_fields(entry):
    """The `bdsk-file-N`/`bdsk-url-N` `Field` objects of `entry`, in
    numeric order: all files before all URLs."""
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
    return [field for _, field in file_fields + url_fields]


def _strip_braces(value):
    """Strip one matching pair of enclosing `{...}`/`"..."`, if
    present."""
    if isinstance(value, str) and len(value) >= 2:
        if (value[0] == "{" and value[-1] == "}") or (
            value[0] == '"' and value[-1] == '"'
        ):
            return value[1:-1]
    return value


def _is_bare(value):
    """Whether `value` is a string with no enclosing `{...}`/`"..."`
    (a bare macro reference, per BibDesk's convention)."""
    return isinstance(value, str) and bool(value) and value[0] not in '{"'


def _is_macro_ref(key, value):
    """Whether the stored `value` of field `key` is a bare `@string`
    macro reference (same criterion as `Entry._decode`)."""
    return (
        _is_bare(value)
        and key.lower() != "keywords"
        and is_valid_macro_name(value, normalized=True)
    )


def _capitalized(name):
    """`name` with each hyphen-separated part capitalized, as used for
    field names in exports (`author` -> `Author`, `bdsk-file-1` ->
    `Bdsk-File-1`)."""
    return "-".join(part.capitalize() for part in name.split("-"))


def _selected_fields(entry, fields):
    """The stored `Field` objects of `entry` selected by `fields` (a
    validated `"full"`/`"minimal"`/list-of-names value), in export
    order."""
    if fields == "full":
        return _normal_fields(entry) + _bdsk_fields(entry)
    if fields == "minimal":
        whitelist = _MINIMAL_FIELDS.get(entry.entry_type.lower())
        if whitelist is None:
            whitelist = _MINIMAL_FALLBACK
        names = [name for name in whitelist if entry.get(name)]
    else:
        names = fields
    selected = []
    for name in names:
        field = entry._find_field(name)
        if field is not None:
            selected.append(field)
    return selected


def _field_body(entry, field, unicode, expand_strings, strings, referenced):
    """The `"Name = value"` body (no trailing comma/newline) for one
    stored `field` of `entry`.

    A bare macro reference that is kept (`expand_strings=False`) has
    its normalized name added to the `referenced` set (for the
    `@string` definitions block).
    """
    name = field.key.lower()
    value = field.value
    label = _capitalized(name)
    match = _BDSK_FILE_RE.match(name)
    if match:
        if isinstance(value, BibDeskFile):
            path = value.relative_path
        else:
            path = BibDeskFile.from_field_value(value).relative_path
        return f"{label} = {{{path}}}"
    if _BDSK_URL_RE.match(name):
        return f"{label} = {{{_strip_braces(value)}}}"
    if _is_macro_ref(field.key, value):
        macro = normalize_macro_name(value)
        if not expand_strings:
            referenced.add(macro)
            return f"{label} = {macro}"
        resolved = strings.get(macro)
        if resolved is None:
            warnings.warn(
                f"macro {macro!r} is undefined; keeping the bare " "reference",
                UserWarning,
                stacklevel=4,
            )
            return f"{label} = {macro}"
        if not unicode and not skip_texify(name):
            resolved = texify(resolved)
        return f"{label} = {{{resolved}}}"
    # In-memory storage may hold either Unicode or TeX-encoded text
    # (file-loaded values are detexified at parse time, assigned values
    # are texified by `__setitem__`), so always decode, and re-encode
    # for `unicode=False`, rather than trusting the stored form.
    rendered = str(entry._decode(field.key, field.value))
    if not unicode and not skip_texify(name):
        rendered = texify(rendered)
    return f"{label} = {{{rendered}}}"


def _derived_preprint_values(entry, preprint):
    """The derived values of the preprint-related fields of a
    preprint-only entry, as a `dict`: the stored value where the
    entry has the field, else the value derived from the
    `(archive, identifier)` `preprint` -- `eprint` (identifier,
    version suffix stripped), `archiveprefix` (the archive's
    canonical spelling), `journal` (the canonical pseudo-journal),
    and `url` (the DOI-resolver address for the entry's `doi`, else
    the stored `url`, else the archive's page for the identifier;
    `None` if there is no link at all)."""
    archive, identifier = preprint
    doi = str(entry.get("doi") or "").strip()
    if doi:
        url = f"https://doi.org/{doi}"
    else:
        url = str(entry.get("url") or "").strip() or _archive_url(
            archive, identifier
        )
    return {
        "eprint": str(entry.get("eprint") or "").strip()
        or _strip_eprint_version(identifier),
        "archiveprefix": str(entry.get("archiveprefix") or "").strip()
        or archive.name,
        # the link base for REVTeX's eprint machinery (None for
        # arXiv, the styles' built-in default, and for archives
        # without a `<base>/{id}` URL template)
        "archive": _archive_base(archive),
        "journal": f"{archive.name}:{identifier}",
        "url": url,
        # `@unpublished` requires a `note`; "preprint" is the neutral
        # status text when the entry does not store one
        "note": str(entry.get("note") or "").strip() or "preprint",
    }


def _preprint_selection(entry, preprint, mode, fields):
    """The `(entry_type, field_list)` for exporting the preprint-only
    `entry` (with `preprint` its `(archive, identifier)`) as `mode`
    (`"misc"` or `"article"`), under a `"full"`/`"minimal"` `fields`
    selection.

    `"misc"`/minimal is the structured eprint form (author, title,
    eprint, archiveprefix, archive, primaryclass, doi, year, plus a
    stored url/note); `"unpublished"`/minimal is the same form as
    `@unpublished`, with a `note` guaranteed (the stored one, or
    "preprint" -- `note` is a required field of `@unpublished`);
    `"article"`/minimal is the pseudo-journal form (author, title,
    journal, url, note, year) with the DOI written as its resolver
    URL. A `"full"` export keeps all other stored fields (including
    the pseudo-journal, which every BibTeX style ignores on `misc`
    and `unpublished` entries) and only ensures the derived fields:
    `eprint`/`archiveprefix`, and -- for a non-arXiv archive with a
    `<base>/{id}` URL template -- the `archive` link base; the
    synthesized `note` is *minimal-only*, so that a full export
    never round-trips it into a library. `"article"` replaces the
    eprint fields by the pseudo-journal and the `url`.
    """
    derived = _derived_preprint_values(entry, preprint)

    def synthetic(name):
        value = derived[name]
        if value is None:
            return None
        return Field(key=name, value="{" + value + "}")

    def stored_or_synthetic(name):
        field = entry._find_field(name)  # pylint: disable=protected-access
        if field is not None:
            return field
        if name in derived:
            return synthetic(name)
        return None

    if mode == "misc":
        keep_names = _PREPRINT_MISC_FIELDS
        drop = frozenset()
        ensure = ("eprint", "archiveprefix", "archive")
    elif mode == "unpublished":
        keep_names = _PREPRINT_MISC_FIELDS
        drop = frozenset()
        ensure = ("eprint", "archiveprefix", "archive")
        if fields == "minimal":
            # the `note` is only guaranteed in *minimal* exports: a
            # full export is the database-fidelity view, and must not
            # round-trip a synthesized note into a library
            ensure = ensure + ("note",)
    else:  # mode == "article"
        keep_names = _PREPRINT_ARTICLE_FIELDS
        drop = frozenset(
            (
                "journal",
                "url",
                "doi",
                "eprint",
                "archiveprefix",
                "primaryclass",
            )
        )
        ensure = ("journal", "url")
    if fields == "minimal":
        selected = []
        for name in keep_names:
            if name in ensure:
                # `"misc"`/`"unpublished"` keep a stored field
                # verbatim; `"article"` always writes the *derived*
                # journal/url (canonical spelling, DOI-resolver URL)
                field = (
                    synthetic(name)
                    if mode == "article"
                    else stored_or_synthetic(name)
                )
            elif entry.get(name):
                # pylint: disable-next=protected-access
                field = entry._find_field(name)
            else:
                field = None
            if field is not None:
                selected.append(field)
        return mode, selected
    # fields == "full"
    selected = [
        field
        for field in _normal_fields(entry)
        if field.key.lower() not in drop
    ]
    have = {field.key.lower() for field in selected}
    for name in ensure:
        if name not in have:
            field = synthetic(name)
            if field is not None:
                selected.append(field)
    return mode, bibdesk_field_order(selected) + _bdsk_fields(entry)


def _published_archive_field(entry, selected):
    """A synthetic `archive` field (the link base for REVTeX's
    eprint machinery) for the full or minimal export of a
    *published* entry whose selected `eprint` names a recognized
    non-arXiv archive with a `<base>/{id}` URL template; `None`
    when not applicable (no eprint selected, arXiv, unrecognized
    archive, or an `archive` already stored)."""
    names = {field.key.lower() for field in selected}
    if "eprint" not in names or "archive" in names:
        return None
    prefix = str(entry.get("archiveprefix") or "").strip() or "arXiv"
    archive = active.preprint_archives.get(prefix.lower())
    if archive is None:
        return None
    base = _archive_base(archive)
    if base is None:
        return None
    return Field(key="archive", value="{" + base + "}")


def _render_entry(
    entry, fields, unicode, expand_strings, strings, referenced, preprint
):
    """Render a single `entry` (with a trailing newline).

    `preprint` (`"misc"`, `"unpublished"`, `"article"`, or
    `"stored"`) selects the export form of a preprint-only entry;
    explicit field lists and `"stored"` always render the stored
    entry as-is."""
    entry_type = entry.entry_type
    selected = None
    if preprint != "stored" and fields in ("full", "minimal"):
        info = _entry_preprint(entry, active.preprint_archives)
        if info is not None:
            entry_type, selected = _preprint_selection(
                entry, info, preprint, fields
            )
    if selected is None:
        selected = _selected_fields(entry, fields)
        if fields in ("full", "minimal") and preprint != "stored":
            extra = _published_archive_field(entry, selected)
            if extra is not None:
                if fields == "full":
                    selected = bibdesk_field_order(
                        _normal_fields(entry) + [extra]
                    ) + _bdsk_fields(entry)
                else:
                    selected.append(extra)
    lines = [f"@{entry_type}{{{entry.key},\n"]
    for field in selected:
        body = _field_body(
            entry, field, unicode, expand_strings, strings, referenced
        )
        lines.append(f"    {body},\n")
    lines.append("}\n")
    return "".join(lines)


def _string_lines(referenced, strings, unicode):
    """`@string{name = {value}}` lines for every macro name in
    `referenced` that is defined in `strings`, sorted by name."""
    if not strings:
        return []
    names = sorted(name for name in referenced if name in strings)
    lines = []
    for name in names:
        value = strings[name]
        if not unicode:
            value = texify(value)
        lines.append("@string{" + name + " = {" + value + "}}\n")
    return lines


def _check_fields(fields):
    """Validate the `fields` parameter of `export_entries`.

    Returns `"full"`, `"minimal"`, or a list of field-name strings;
    raises {exc}`ValueError` for anything else."""
    if fields in ("full", "minimal"):
        return fields
    if isinstance(fields, str):
        raise ValueError(
            "fields must be 'full', 'minimal', or a list of field "
            f"names, not {fields!r}"
        )
    try:
        names = list(fields)
    except TypeError:
        raise ValueError(
            "fields must be 'full', 'minimal', or a list of field "
            f"names, not {fields!r}"
        ) from None
    for name in names:
        if not isinstance(name, str):
            raise ValueError(f"field name must be a str, not {name!r}")
    return names


def export_entries(
    entries,
    strings=None,
    unicode=True,
    expand_strings=False,
    fields="full",
    outfile=None,
    preprint=None,
):
    """Serialize `entries` (an iterable of `Entry`) to bibtex text.

    ```python
    export_entries(
        entries,
        strings=None,
        unicode=True,
        expand_strings=False,
        fields="full",
        outfile=None,
        preprint=None,
    )
    ```

    Returns the text as a `str` if `outfile` is `None`, else writes it
    (UTF-8) to `outfile` and returns `None`.

    # Arguments

    * `entries`: an iterable of {class}`bibdeskparser.entry.Entry`.
    * `strings`: an optional `dict` mapping macro name to its Unicode
      value (e.g. `library.strings`), the `@string` definitions of the
      exporting library. With `expand_strings=False`, definitions for
      the macros referenced by the selected fields are prepended to
      the output (a referenced macro not found in `strings` is
      silently skipped -- this is a best-effort self-containment
      feature, not a validator); with `expand_strings=True`, the
      mapping (extended by the standard month macros) resolves each
      reference to its value.
    * `unicode`: whether field values are written as Unicode text
      (`True`, default) or TeX-encoded as they would be written to
      the `.bib` file on disk (`False`); see the module docstring.
    * `expand_strings`: whether bare `@string` macro references are
      kept (`False`, default) or replaced by their values (`True`);
      see the module docstring.
    * `fields`: `"full"` (default), `"minimal"`, or a list of field
      names; see the module docstring. Raises {exc}`ValueError` for
      any other value.
    * `outfile`: if given, a path (`str`/`pathlib.Path`) or an
      already-open text file object (anything with a `write` method;
      if already open, it is written to but not closed).
    * `preprint`: the entry type a *preprint-only* entry (see the
      module docstring) is exported as -- `"unpublished"` or
      `"misc"` (the structured eprint forms) or `"article"` (the
      pseudo-journal form), each with the derived fields described
      in the module docstring, or `"stored"` for no transformation
      at all (used internally by
      {meth}`~bibdeskparser.Library.edit`). Defaults to the
      `preprint_export` [configuration](configuration) setting
      (`"unpublished"` unless configured). Explicit field lists are
      always exported as stored, whatever `preprint` says.

    Multiple entries are separated by a single blank line; the returned
    (or written) text always ends with exactly one trailing newline.
    """
    fields = _check_fields(fields)
    if preprint is None:
        preprint = active.preprint_export
    if preprint not in ("misc", "unpublished", "article", "stored"):
        raise ValueError(
            "preprint must be 'misc', 'unpublished', 'article', or "
            f"'stored', not {preprint!r}"
        )
    entries = list(entries)
    all_strings = {**STANDARD_MACROS, **(strings or {})}
    referenced = set()
    rendered = [
        _render_entry(
            entry,
            fields,
            unicode,
            expand_strings,
            all_strings,
            referenced,
            preprint,
        )
        for entry in entries
    ]
    pieces = []
    if not expand_strings:
        string_lines = _string_lines(referenced, strings, unicode)
        if string_lines:
            pieces.append("".join(string_lines))
            pieces.append("\n")
    pieces.append("\n".join(rendered))
    text = "".join(pieces)
    if outfile is None:
        return text
    if hasattr(outfile, "write"):
        outfile.write(text)
        return None
    with open(outfile, "w", encoding="utf-8") as fh:
        fh.write(text)
    return None
