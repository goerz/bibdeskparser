r"""The `Entry` class: a single BibDesk `.bib` record.

`Entry` wraps a `bibtexparser.model.Entry` (`entry._entry`, private) via
*composition*, presenting BibDesk's view of a bibliography record:

- A case-insensitive `dict`-like interface (`Entry` is a
  {py:class}`collections.abc.MutableMapping`) over "normal" fields, i.e.
  every field except `date-added`, `date-modified`, `keywords`, and any
  field whose key starts with `bdsk-` (case-insensitively). Values are
  Unicode strings without their enclosing `{...}`/`"..."` delimiters,
  matching what BibDesk's UI editor displays; a bare value that is a
  valid BibDesk macro name is returned in its normalized (lowercase)
  form instead, since it is a reference to a `@string` macro rather
  than literal text.
- {any}`Entry.date_added` / {any}`Entry.date_modified`: read-only
  `datetime.datetime` views of the BibDesk-managed `date-added` /
  `date-modified` fields (not accessible through the `dict` interface).
- {any}`Entry.keywords`: a read-only tuple view of the `keywords`
  field (also not accessible through the `dict` interface). Keywords
  are edited through the owning {any}`bibdeskparser.library.Library`
  (`add_to_keyword`, `remove_from_keyword`, or the
  `Library.keywords` mapping), which is what keeps that mapping and
  the entries consistent at all times. The `keywords` field is always
  literal text: unlike other fields, a bare stored value that looks
  like a macro name is never treated as a `@string` reference.
- {any}`Entry.groups`: a read-only tuple of the names of the BibDesk
  static groups the entry belongs to, maintained by the owning
  {any}`bibdeskparser.library.Library` (group data lives in the
  library, not in the entry).
- {any}`Entry.files` / {any}`Entry.urls`: structured views of the
  `bdsk-file-N` / `bdsk-url-N` fields (also not accessible through the
  `dict` interface). `files` is read-only: the stored paths are
  relative to the library's `.bib` file, which the entry itself does
  not know, so attachments are modified through the owning
  {any}`bibdeskparser.library.Library` (`add_file`, `replace_file`,
  `unlink_file`, `rename_file`) instead.
- {any}`Entry.author` / {any}`Entry.editor`: read-only structured views
  of the `author`/`editor` fields.

Every mutation (`__setitem__`, `__delitem__`, the `urls` setter, and
the `entry_type` setter) updates `date-modified` and marks the entry
{any}`Entry.dirty` (BibDesk itself does this for ordinary fields and
the entry type, but not for `bdsk-*` changes; `bibdeskparser` stamps
those too, since the entry's stored fields do change). `key` (see
{any}`Entry.key`) is the one exception: it is read-only.

Field values are TeX-encoded on write and decoded back to Unicode on
read, except for URL-like fields, which are stored/returned verbatim,
matching how BibDesk itself treats them -- so a field set through
`Entry` and one loaded from a `.bib` file behave identically.
"""

import datetime
import re
import urllib.parse
import warnings
from collections.abc import MutableMapping

from bibtexparser import model

from .bdskfile import BibDeskFile
from .macros import is_valid_macro_name, normalize_macro_name
from .names import structured_names
from .texmap import detexify, skip_texify, texify

__all__ = ["Entry", "Value"]

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = []

#: `strptime`/`strftime` format of the `date-added`/`date-modified`
#: fields, e.g. `"2026-07-04 09:04:26 -0400"`.
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"

_DATE_KEYS = frozenset(("date-added", "date-modified"))

_BDSK_FILE_RE = re.compile(r"bdsk-file-(\d+)$", re.IGNORECASE)
_BDSK_URL_RE = re.compile(r"bdsk-url-(\d+)$", re.IGNORECASE)


def _is_normal_key(key):
    """Whether `key` belongs to the `Entry` `dict` interface.

    `False` for `date-added`, `date-modified`, `keywords`, and any
    `bdsk-` prefixed key (case-insensitively); `True` for everything
    else.
    """
    lkey = key.lower()
    return (
        lkey not in _DATE_KEYS
        and lkey != "keywords"
        and not lkey.startswith("bdsk-")
    )


def _split_keywords(raw):
    """Split a comma-separated `keywords` field value into a list of
    stripped, non-empty keywords."""
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]


def _strip_enclosing(value):
    """Strip one matching pair of `{...}`/`"..."` from `value`, if
    present."""
    if len(value) >= 2 and (
        (value[0] == "{" and value[-1] == "}")
        or (value[0] == '"' and value[-1] == '"')
    ):
        return value[1:-1]
    return value


def _parse_date(value):
    """Parse a `date-added`/`date-modified` field value."""
    if not isinstance(value, str):
        return None
    return datetime.datetime.strptime(_strip_enclosing(value), _DATE_FORMAT)


class Value(str):
    r"""Force a field value to be stored as a braced BibTeX string.

    ```python
    Value(value)
    ```

    A plain `str` value assigned via `entry[field] = value` is stored
    bare (no enclosing `{...}`) when it happens to be a valid,
    normalized BibDesk macro name, since such a value is ambiguous
    with a reference to a `@string` macro of that name. Wrap the
    value in `Value` to force it to be treated as literal text
    instead, even though it would otherwise pass as a macro name:

    Both forms return the same value through the `dict` interface --
    the difference is only in how the value is *stored* (as a literal
    braced string vs. a bare macro reference), visible in the `"raw"`
    export format (see {any}`Library.export`):

    ```python
    >>> import warnings
    >>> from bibdeskparser import Library
    >>> from bibdeskparser.entry import Entry, Value
    >>> bib = Library()
    >>> entry = Entry("article", "Key2024")
    >>> entry["journal"] = Value("prl")  # forced literal text
    >>> entry["journal"]
    'prl'
    >>> bib["Key2024"] = entry
    >>> bib.export("Key2024", format="raw") == (
    ...     "@article{Key2024,\n\tjournal = {prl}\n}\n"
    ... )
    True
    >>> with warnings.catch_warnings():
    ...     warnings.simplefilter("ignore")
    ...     entry["journal"] = "prl"  # bare str: treated as a macro ref
    >>> entry["journal"]
    'prl'
    >>> bib.export("Key2024", format="raw") == (
    ...     "@article{Key2024,\n\tjournal = prl\n}\n"
    ... )
    True

    ```
    """

    __slots__ = ()


class Entry(MutableMapping):
    """A single BibDesk `.bib` entry.

    ```python
    Entry(entry_type, key, fields=None)
    ```

    Creates a new entry that is not (yet) part of any `Library`; add
    it to one with `library[key] = entry`. `fields` (if given, a
    `dict` mapping field name to a `str` or {any}`Value`) is applied
    field by field, the same way as `entry[field_key] = value` -- so a
    `keywords` field is rejected with `KeyError`, like any other key
    outside the `dict` interface: keywords are edited only through the
    owning `Library`, after the entry has been added to one.
    `date-added` and `date-modified` are set to the current time (see
    {any}`dirty`).

    An entry obtained from a `Library` (e.g. `library[key]`, or by
    iterating {any}`Library.entries`) is not constructed this way: it
    keeps the `date-added`/`date-modified` values and `dirty` state it
    had when the library was loaded, rather than being reset to "just
    created".

    See the module docstring for the full behavior of the `dict`
    interface and the other properties.
    """

    def __init__(self, entry_type, key, fields=None):
        self._entry = model.Entry(entry_type=entry_type, key=key, fields=[])
        self._groups = ()
        self._dirty = False
        for field_key, value in (fields or {}).items():
            self[field_key] = value
        self._touch()

    @classmethod
    def _wrap(cls, model_entry):
        """Wrap an already-parsed `bibtexparser.model.Entry` (internal).

        Unlike the constructor, this does not touch `model_entry`'s
        fields or dates: a freshly loaded entry is pristine (`dirty` is
        `False`) until it is modified. Used by the library loader.
        """
        self = object.__new__(cls)
        self._entry = model_entry
        self._groups = ()
        self._dirty = False
        return self

    # -- internal helpers -------------------------------------------- #

    def _find_field(self, key):
        """Return the `Field` matching `key` case-insensitively, or
        `None`."""
        lkey = key.lower()
        for field in self._entry.fields:
            if field.key.lower() == lkey:
                return field
        return None

    def _check_writable(self, key):
        """Raise `KeyError` if `key` is not writable via the `dict`
        interface."""
        lkey = key.lower()
        if lkey in _DATE_KEYS:
            raise KeyError(
                f"{key!r} is read-only; use the date_added/"
                "date_modified properties"
            )
        if lkey == "keywords":
            raise KeyError(
                "'keywords' is not accessible via the dict interface; "
                "use the read-only Entry.keywords property, or the "
                "Library methods add_to_keyword/remove_from_keyword"
            )
        if lkey.startswith("bdsk-"):
            raise KeyError(
                f"{key!r} is not accessible via the dict interface; "
                "use the urls property, or the Library methods for "
                "file attachments (add_file etc.)"
            )

    def _set_raw_field(self, key, rendered_value):
        """Set the raw (encoded) value of `key`, preserving the
        existing `Field` object (and its original key spelling) if one
        exists, else appending a new field."""
        field = self._find_field(key)
        if field is not None:
            field.value = rendered_value
        else:
            self._entry.fields.append(
                model.Field(key=key, value=rendered_value)
            )

    def _touch(self):
        """Set `date-modified` (and `date-added`, if unset) to now, and
        mark the entry {any}`dirty`."""
        now = datetime.datetime.now().astimezone()
        rendered = "{" + now.strftime(_DATE_FORMAT) + "}"
        self._set_raw_field("date-modified", rendered)
        if self._find_field("date-added") is None:
            self._set_raw_field("date-added", rendered)
        self._dirty = True

    def _decode(self, key, value):
        """Decode a raw stored field value for `__getitem__`."""
        if not isinstance(value, str):
            return value
        if len(value) >= 2 and (
            (value[0] == "{" and value[-1] == "}")
            or (value[0] == '"' and value[-1] == '"')
        ):
            inner = value[1:-1]
            return inner if skip_texify(key) else detexify(inner)
        # A bare macro-shaped `keywords` value is *not* a macro
        # reference: keywords are always literal text (BibDesk's own
        # keyword machinery expands any macro and writes back a plain
        # string on the first keyword edit).
        if key.lower() != "keywords" and is_valid_macro_name(
            value, normalized=True
        ):
            return normalize_macro_name(value)
        # bare and not a valid macro name: shouldn't normally happen for
        # well-formed data, but be defensive and return it as-is
        return value if skip_texify(key) else detexify(value)

    # -- MutableMapping interface (normal fields only) ---------------- #

    def __getitem__(self, key):
        field = self._find_field(key)
        if field is None or not _is_normal_key(field.key):
            raise KeyError(key)
        return self._decode(field.key, field.value)

    def __setitem__(self, key, value):
        self._check_writable(key)
        if isinstance(value, Value):
            text = str(value)
            text = text if skip_texify(key) else texify(text)
            rendered = "{" + text + "}"
        elif isinstance(value, str):
            if is_valid_macro_name(value, normalized=True):
                warnings.warn(
                    f"field {key!r} set to macro reference {value!r}; "
                    "ensure it is defined in library.strings",
                    UserWarning,
                    stacklevel=2,
                )
                rendered = value
            else:
                text = value if skip_texify(key) else texify(value)
                rendered = "{" + text + "}"
        else:
            raise TypeError(
                f"field value must be a str or Value, not {type(value)!r}"
            )
        self._set_raw_field(key, rendered)
        self._touch()

    def __delitem__(self, key):
        self._check_writable(key)
        field = self._find_field(key)
        if field is None or not _is_normal_key(field.key):
            raise KeyError(key)
        self._entry.fields.remove(field)
        self._touch()

    def __iter__(self):
        for field in self._entry.fields:
            if _is_normal_key(field.key):
                yield field.key

    def __len__(self):
        return sum(
            1 for field in self._entry.fields if _is_normal_key(field.key)
        )

    # -- dates --------------------------------------------------------- #

    @property
    def date_added(self):
        """`datetime.datetime` of the `date-added` field (read-only).

        `None` if the field is absent (shouldn't normally happen: the
        constructor always sets it)."""
        field = self._find_field("date-added")
        return None if field is None else _parse_date(field.value)

    @property
    def date_modified(self):
        """`datetime.datetime` of the `date-modified` field
        (read-only)."""
        field = self._find_field("date-modified")
        return None if field is None else _parse_date(field.value)

    @property
    def dirty(self):
        """Whether the entry has been modified since it was loaded
        (always `True` for a freshly constructed entry)."""
        return self._dirty

    # -- key / entry_type ------------------------------------------------ #

    @property
    def key(self):
        """The BibTeX citation key (read-only).

        Set at construction time and immutable afterwards -- an
        `Entry` cannot rename itself. An entry already in a
        {any}`bibdeskparser.library.Library` is renamed through
        {any}`bibdeskparser.library.Library.rekey`, which keeps the
        library's key-based lookups consistent.
        """
        return self._entry.key

    @property
    def entry_type(self):
        """The BibTeX entry type, e.g. `"article"`."""
        return self._entry.entry_type

    @entry_type.setter
    def entry_type(self, value):
        self._entry.entry_type = value
        self._touch()

    # -- groups ------------------------------------------------------ #

    @property
    def groups(self):
        """Names of the BibDesk static groups this entry belongs to
        (a tuple, read-only).

        Maintained by the owning `Library`: group data lives in the
        library, and every mutation of it (`library.groups[name] =
        ...`, `del library.groups[name]`,
        {any}`bibdeskparser.library.Library.add_to_group`,
        {any}`bibdeskparser.library.Library.remove_from_group`)
        immediately refreshes this property for every affected entry,
        so it is always consistent with `library.groups`. `()` if the
        entry is not (yet) attached to a `Library`, or is a member of
        no group.
        """
        return tuple(self._groups)

    # -- keywords ------------------------------------------------------ #

    @property
    def keywords(self):
        """The entry's keywords (a tuple, read-only).

        Parsed on access from the stored `keywords` field (a
        comma-separated list, not accessible through the `dict`
        interface). Keywords are edited through the owning
        {any}`bibdeskparser.library.Library`
        ({any}`bibdeskparser.library.Library.add_to_keyword`,
        {any}`bibdeskparser.library.Library.remove_from_keyword`, or
        the `Library.keywords` mapping), which is what keeps that
        mapping and the entries consistent. Unlike {any}`groups`,
        keywords are stored in the entry itself, so they are preserved
        by {any}`copy` and readable on a detached entry.
        """
        field = self._find_field("keywords")
        if field is None:
            return ()
        return tuple(_split_keywords(self._decode(field.key, field.value)))

    def _set_keywords(self, keywords):
        """Replace the stored `keywords` field with the comma-joined
        `keywords` (an iterable of strings), removing the field
        entirely if `keywords` is empty, and `_touch`.

        The public `keywords` property is read-only; this may only be
        called by the owning `Library` (and by the `editing` module,
        on the library's behalf), so that `Library.keywords` and the
        entries can never disagree."""
        keywords = list(keywords)
        field = self._find_field("keywords")
        if keywords:
            text = texify(", ".join(keywords))
            self._set_raw_field("keywords", "{" + text + "}")
        elif field is not None:
            self._entry.fields.remove(field)
        else:
            return  # no keywords before or after: nothing to change
        self._touch()

    # -- files -------------------------------------------------------- #

    def _bdsk_file_fields(self):
        """`(index, field)` pairs for all `bdsk-file-N` fields, sorted
        by `index`."""
        items = []
        for field in self._entry.fields:
            match = _BDSK_FILE_RE.match(field.key)
            if match:
                items.append((int(match.group(1)), field))
        items.sort(key=lambda item: item[0])
        return items

    @property
    def files(self):
        """Relative paths of attached files (the `bdsk-file-N` fields),
        in numeric order (1, 2, 3, ...); read-only.

        The paths are relative to the directory of the library's
        `.bib` file, which the entry itself does not know, so
        attachments can only be modified through the owning
        {any}`bibdeskparser.library.Library`: see
        {any}`bibdeskparser.library.Library.add_file`,
        {any}`bibdeskparser.library.Library.replace_file`,
        {any}`bibdeskparser.library.Library.unlink_file`, and
        {any}`bibdeskparser.library.Library.rename_file` (an entry
        must be added to a library before files can be attached to
        it).
        """
        return [f.relative_path for f in self._file_objects()]

    def _file_objects(self):
        """The entry's attachments as `BibDeskFile` objects, in
        `files` order (decoding raw field values as needed)."""
        result = []
        for _, field in self._bdsk_file_fields():
            value = field.value
            if not isinstance(value, BibDeskFile):
                value = BibDeskFile.from_field_value(value)
            result.append(value)
        return result

    def _set_files(self, bdsk_files):
        """Replace all `bdsk-file-N` fields with `bdsk_files` (a list
        of `BibDeskFile`), renumbering from 1, and `_touch`.

        The public `files` property is read-only; this may only be
        called by the owning `Library` (and by the `editing` module,
        on the library's behalf), which resolves paths relative to
        the library's `.bib` directory."""
        for _, field in self._bdsk_file_fields():
            self._entry.fields.remove(field)
        for i, bdsk_file in enumerate(bdsk_files, start=1):
            self._entry.fields.append(
                model.Field(key=f"bdsk-file-{i}", value=bdsk_file)
            )
        self._touch()

    # -- urls ---------------------------------------------------------- #

    def _bdsk_url_fields(self):
        """`(index, field)` pairs for all `bdsk-url-N` fields, sorted
        by `index`."""
        items = []
        for field in self._entry.fields:
            match = _BDSK_URL_RE.match(field.key)
            if match:
                items.append((int(match.group(1)), field))
        items.sort(key=lambda item: item[0])
        return items

    @property
    def urls(self):
        """URLs of attached links (the `bdsk-url-N` fields), in numeric
        order (1, 2, 3, ...), without their enclosing braces.

        Assign a list of URL strings to replace them; each one must
        include both a scheme and a host (e.g.
        `https://example.com/paper.pdf`), or `ValueError` is raised.
        """
        return [
            _strip_enclosing(field.value)
            for _, field in self._bdsk_url_fields()
        ]

    @urls.setter
    def urls(self, urls):
        urls = list(urls)
        for url in urls:
            parsed = urllib.parse.urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(f"not a valid URL: {url!r}")
        for _, field in self._bdsk_url_fields():
            self._entry.fields.remove(field)
        for i, url in enumerate(urls, start=1):
            self._entry.fields.append(
                model.Field(key=f"bdsk-url-{i}", value="{" + url + "}")
            )
        self._touch()

    # -- structured names ---------------------------------------------- #

    @property
    def author(self):
        """Structured view of the `author` field (read-only).

        A `list` of `NameParts` (each with `.first`, `.von`, `.last`,
        `.jr` attributes), or `[]` if the field is absent."""
        return structured_names(self.get("author", ""))

    @property
    def editor(self):
        """Structured view of the `editor` field (read-only), like
        {any}`author`."""
        return structured_names(self.get("editor", ""))

    def __repr__(self):
        return f"Entry({self.entry_type!r}, {self.key!r})"

    def _repr_pretty_(self, p, cycle):
        # IPython/Jupyter pretty-printing hook: a fuller, multi-line
        # rendering (including fields) for interactive display, while
        # __repr__ stays the compact, eval-able form.
        prefix = f"Entry({self.entry_type!r}, {self.key!r}"
        if cycle:
            p.text(prefix + ", {...})")
            return
        items = list(self.items())
        if not items:
            p.text(prefix + ")")
            return
        with p.group(4, prefix + ", {", "})"):
            for i, (field_key, value) in enumerate(items):
                if i:
                    p.text(",")
                    p.breakable()
                p.pretty(field_key)
                p.text(": ")
                p.pretty(value)

    # -- copying -------------------------------------------------------- #

    def copy(self):
        """Return an independent copy of this entry.

        Mutating the copy (or its fields) never affects the original.
        The copy is not a member of any `Library` (its `groups` is
        `()`) until you add it to one, and starts with `dirty` set to
        `False`: its fields (including `date-added`, `date-modified`,
        and `keywords`, which travels with the entry, unlike `groups`)
        are copied verbatim from the original, so the copy is a
        faithful snapshot of the original's current state, not a
        fresh, empty entry.
        """
        new_fields = [
            model.Field(key=field.key, value=field.value)
            for field in self._entry.fields
        ]
        new_entry = model.Entry(
            entry_type=self._entry.entry_type,
            key=self._entry.key,
            fields=new_fields,
        )
        return Entry._wrap(new_entry)
