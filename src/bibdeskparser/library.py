"""The `Library` class and the `StaleFileError` it may raise."""

import datetime
import getpass
import logging
import os
import sys
import warnings
from abc import ABCMeta
from collections.abc import MutableMapping
from contextlib import contextmanager
from pathlib import Path

import bibtexparser
from bibtexparser.model import (
    DuplicateBlockKeyBlock,
    ExplicitComment,
    ImplicitComment,
    String,
)

from . import config, editing
from .bdskfile import BibDeskFile
from .entry import Entry, _strip_enclosing
from .exporting import export_entries
from .groups import (
    is_static_groups_comment,
    parse_static_groups,
    render_static_groups,
)
from .header import make_header, parse_header, peek_timestamp, update_header
from .macros import is_valid_macro_name, normalize_macro_name
from .middleware import parse_stack
from .render import render_entries
from .search import search_entries
from .writer import bibdesk_field_order, render_library

__all__ = ["Library", "StaleFileError"]

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = []

try:
    import pwd
except ImportError:  # pragma: no cover - non-POSIX platforms
    pwd = None


class StaleFileError(RuntimeError):
    """Raised by {meth}`Library.save` when the target file is newer on
    disk than this library.

    This means the file was saved (by BibDesk, or by another process)
    after this `Library` was loaded or last saved here, so overwriting
    it now would silently discard those changes. Pass `force=True` to
    {meth}`Library.save` to overwrite anyway.
    """


# -- module-private helpers ------------------------------------------- #


@contextmanager
def _quiet_bibtexparser_block_type_logging():
    """Silence bibtexparser's per-middleware "Unknown block type"
    logging.

    Every middleware in `parse_stack` calls into
    `bibtexparser`'s `BlockMiddleware.transform_block`, which logs
    this at `WARNING` for any `ParsingFailedBlock` (e.g., a duplicate
    key or duplicate field) since it only special-cases `Entry`,
    `String`, `Preamble`, and comment blocks -- so a single failed
    block produces one log message per middleware. `Library.__init__`
    inspects `library._library.failed_blocks` itself and raises its
    own, single `UserWarning` per condition instead.
    """
    logger = logging.getLogger("bibtexparser.middlewares.middleware")
    previous_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous_level)


def _check_unparseable_blocks(failed_blocks):
    """Warn about `failed_blocks` not already covered by
    `Library.duplicate_keys`.

    * `failed_blocks`: `library._library.failed_blocks`, the
      `bibtexparser.model.ParsingFailedBlock` instances found while
      parsing.
    """
    other = [
        block
        for block in failed_blocks
        if not isinstance(block, DuplicateBlockKeyBlock)
    ]
    if other:
        details = "; ".join(str(block.error) for block in other)
        warnings.warn(
            f"{len(other)} block(s) could not be parsed and were "
            f"skipped: {details}",
            UserWarning,
            stacklevel=3,
        )


def _default_creator():
    """The OS account's full name, for a from-scratch library's header.

    Uses the Gecos "full name" field of the current user's password
    database entry (stripping a trailing comma, as sometimes found in
    macOS Gecos fields), falling back to the login name (see
    {func}`getpass.getuser`) if `pwd` is unavailable or the Gecos
    field is empty.
    """
    if pwd is not None:
        try:
            gecos = pwd.getpwuid(os.getuid()).pw_gecos
        except (KeyError, OSError):
            gecos = ""
        if gecos:
            name = gecos.split(",", 1)[0].strip()
            if name:
                return name
    return getpass.getuser()


def _is_bare_value(value):
    """Whether `value` is not enclosed in `{...}`/`"..."` (i.e. is a
    candidate bare macro reference)."""
    return not (
        len(value) >= 2
        and (
            (value[0] == "{" and value[-1] == "}")
            or (value[0] == '"' and value[-1] == '"')
        )
    )


def _bare_macro_fields(entry):
    """Yield `(field, value)` for every bare (unbraced) string-valued
    field of `entry`: candidate references to a `@string` macro.

    The `keywords` field is skipped: keywords are always literal text,
    never a macro reference, so it does not participate in macro
    validation, deletion protection, or renaming."""
    for field in entry._entry.fields:  # pylint: disable=protected-access
        value = field.value
        if (
            isinstance(value, str)
            and _is_bare_value(value)
            and field.key.lower() != "keywords"
        ):
            yield field, value


def _check_duplicate_macro_values(strings_dict):
    """Warn if two or more distinct macro names expand to the same
    value.

    * `strings_dict`: a `dict` mapping macro name to
      `bibtexparser.model.String`, as `library._library.strings_dict`.
    """
    by_value = {}
    for name, string in strings_dict.items():
        by_value.setdefault(string.value, []).append(name)
    duplicates = {
        value: sorted(names)
        for value, names in by_value.items()
        if len(names) > 1
    }
    if duplicates:
        details = "; ".join(
            f"{value!r}: {names}" for value, names in duplicates.items()
        )
        warnings.warn(
            f"distinct macros expand to the same value: {details}",
            UserWarning,
            stacklevel=3,
        )


def _delete_file(path):
    """Remove `path` from the filesystem: move it to the Trash where
    possible (macOS, with pyobjc installed), else delete it
    permanently."""
    if sys.platform == "darwin":
        try:
            # pylint: disable=import-outside-toplevel
            from Foundation import (  # pyobjc-framework-Cocoa
                NSURL,
                NSFileManager,
            )
        except ImportError:
            pass
        else:
            url = NSURL.fileURLWithPath_(str(path))
            manager = NSFileManager.defaultManager()
            # The selector name exceeds the line length limit.
            trash_item = getattr(
                manager, "trashItemAtURL_resultingItemURL_error_"
            )
            ok, _resulting_url, _error = trash_item(url, None, None)
            if ok:
                return
    os.remove(path)


def _find_header_block(raw_library):
    """Return `(header_block, creator, timestamp)` for `raw_library` (a
    `bibtexparser.Library`).

    The header, if present, is always the very first block. Returns
    `(None, None, None)` if there is no such block (e.g. a `.bib` file
    not written by BibDesk).
    """
    blocks = raw_library.blocks
    if blocks and isinstance(blocks[0], ImplicitComment):
        creator, timestamp = parse_header(blocks[0].comment)
        if creator is not None:
            return blocks[0], creator, timestamp
    return None, None, None


def _find_groups_block(raw_library):
    """Return the `ExplicitComment` block holding the `BibDesk Static
    Groups` comment, or `None`."""
    for block in raw_library.blocks:
        if isinstance(block, ExplicitComment) and is_static_groups_comment(
            block.comment
        ):
            return block
    return None


# -- views ------------------------------------------------------------- #


class _StringsView(MutableMapping):
    """Read-write `dict`-like view of {attr}`Library.strings`.

    Backed by `library._library.strings_dict`. Reading strips the
    enclosing `{...}`/`"..."` delimiters; writing re-adds them (after
    stripping any the caller redundantly supplied) and normalizes the
    macro name (validating it and lowercasing it, matching BibDesk's
    case-insensitive macro table). Deleting a macro that is still
    referenced (as a bare field value) by any entry raises
    {exc}`ValueError`.
    """

    def __init__(self, owner):
        self._owner = owner

    @property
    def _strings_dict(self):
        return self._owner._library.strings_dict

    def __getitem__(self, name):
        return _strip_enclosing(self._strings_dict[name].value)

    def __setitem__(self, name, value):
        name = normalize_macro_name(name)
        value = _strip_enclosing(value)
        strings_dict = self._strings_dict
        if name in strings_dict:
            strings_dict[name].value = "{" + value + "}"
        else:
            new_string = String(key=name, value="{" + value + "}")
            self._owner._library.add([new_string], fail_on_duplicate_key=False)
        self._owner._modified = True
        _check_duplicate_macro_values(self._strings_dict)

    def __delitem__(self, name):
        strings_dict = self._strings_dict
        if name not in strings_dict:
            raise KeyError(name)
        users = self._owner._macro_users(name)
        if users:
            raise ValueError(
                f"cannot delete macro {name!r}: in use by entries "
                f"{sorted(users)}"
            )
        self._owner._library.remove([strings_dict[name]])
        self._owner._modified = True

    def __iter__(self):
        return iter(self._strings_dict)

    def __len__(self):
        return len(self._strings_dict)

    def __repr__(self):
        # Show the full name -> value mapping, like a plain dict.
        return repr(dict(self))

    def _repr_pretty_(self, p, cycle):
        # IPython/Jupyter pretty-printing hook: same name -> value
        # mapping as `repr`, but indented across multiple lines.
        if cycle:
            p.text("{...}")
        else:
            p.pretty(dict(self))


class _GroupsView(MutableMapping):
    """Read-write `dict`-like view of {attr}`Library.groups`, mapping
    each group name to the tuple of the group's citation keys.

    A stateless facade: every operation forwards to the owning
    `Library`, which holds the group data and immediately refreshes
    the `groups` property of every affected
    {class}`Entry`. Values are always tuples, so a
    group's membership cannot be mutated in place: whole groups are
    created, replaced, or deleted through the mapping interface, and
    per-key membership changes go through
    {meth}`Library.add_to_group` / {meth}`Library.remove_from_group`.
    The `MutableMapping` mixins (`pop`, `popitem`, `clear`, `update`,
    `setdefault`) all funnel through `__setitem__`/`__delitem__`, so
    they maintain the same invariants.
    """

    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, name):
        return self._owner._group_data[name]

    def __setitem__(self, name, keys):
        self._owner._assign_group(name, keys)

    def __delitem__(self, name):
        self._owner._delete_group(name)

    def __iter__(self):
        return iter(self._owner._group_data)

    def __len__(self):
        return len(self._owner._group_data)

    def __repr__(self):
        # Show the full name -> keys mapping, like a plain dict.
        return repr(self._owner._group_data)

    def _repr_pretty_(self, p, cycle):
        # IPython/Jupyter pretty-printing hook: same name -> keys
        # mapping as `repr`, but indented across multiple lines.
        if cycle:
            p.text("{...}")
        else:
            p.pretty(self._owner._group_data)


class _KeywordsView(MutableMapping):
    """Read-write `dict`-like view of {attr}`Library.keywords`, mapping
    each keyword to the tuple of citation keys of the entries carrying
    it.

    A stateless facade: the mapping is computed on demand from the
    entries' stored `keywords` fields (keywords in first-seen entry
    order), so it is always consistent with the entries -- the
    `keywords` field is readable but not writable through the entry
    `dict` interface, and every mutation forwards to the owning
    `Library`,
    which edits the affected entries. A keyword exists only inside
    entries' `keywords` fields, so an *empty* keyword cannot be
    represented: assigning `()` is equivalent to deleting the keyword.
    """

    def __init__(self, owner):
        self._owner = owner

    def _index(self):
        index = {}
        for key, entry in self._owner._entries.items():
            for keyword in entry.keywords:
                index.setdefault(keyword, []).append(key)
        return {kw: tuple(keys) for (kw, keys) in index.items()}

    def __getitem__(self, keyword):
        return self._index()[keyword]

    def __setitem__(self, keyword, keys):
        self._owner._assign_keyword(keyword, keys)

    def __delitem__(self, keyword):
        self._owner._delete_keyword(keyword)

    def __iter__(self):
        return iter(self._index())

    def __len__(self):
        return len(self._index())

    def __repr__(self):
        # Show the full keyword -> keys mapping, like a plain dict.
        return repr(self._index())

    def _repr_pretty_(self, p, cycle):
        # IPython/Jupyter pretty-printing hook: same keyword -> keys
        # mapping as `repr`, but indented across multiple lines.
        if cycle:
            p.text("{...}")
        else:
            p.pretty(self._index())


# -- Library ------------------------------------------------------------ #


class _LibraryMeta(ABCMeta):
    """Metaclass exposing the configuration flags as `Library` class
    attributes.

    `Library.verify_types`, `Library.verify_fields`, and
    `Library.config_file` read and write the process-global
    configuration in `bibdeskparser.config` (see the
    [configuration](configuration)). They live on the metaclass so that
    plain class-attribute access -- `Library.verify_types` and
    `Library.verify_types = False` -- routes through it.
    """

    # pylint: disable=missing-function-docstring
    # (each property just forwards to `bibdeskparser.config`; the
    # class docstring above already documents all three)

    @property
    def verify_types(cls):
        return config.get_verify_types()

    @verify_types.setter
    def verify_types(cls, value):
        config.set_verify_types(bool(value))

    @property
    def verify_fields(cls):
        return config.get_verify_fields()

    @verify_fields.setter
    def verify_fields(cls, value):
        config.set_verify_fields(bool(value))

    @property
    def config_file(cls):
        return config.get_config_file()

    @config_file.setter
    def config_file(cls, value):
        config.set_config_file(value)


class Library(MutableMapping, metaclass=_LibraryMeta):
    r"""A BibDesk `.bib` database.

    ```python
    Library(path=None, creator=None)
    ```

    * `path`: path to a `.bib` file to load (UTF-8 text). If `None`
      (default), a fresh, empty, in-memory library is created instead.
    * `creator`: the name to use on the `Created for` line of a
      synthesized header (see {meth}`save`). Only relevant for a
      from-scratch library, or one loaded from a `.bib` file that has
      no BibDesk header of its own; defaults to the OS account's full
      name.

    Loading a file that contains duplicate citation keys (see
    {attr}`duplicate_keys`) emits a `UserWarning`; BibDesk itself
    tolerates such files (keeping only the first entry for each key),
    so this is a read-only, informational condition rather than an
    error.

    A `Library` presents BibDesk's view of a `.bib` database:

    - `Library` is itself a `dict`-like mapping of citation key to
      {class}`Entry`; see {attr}`entries`.
    - {attr}`timestamp`: the save time from the header comment, updated
      by {meth}`save`.
    - {attr}`strings`: a read-write view of the `@string` macro
      definitions.
    - {attr}`groups`: a read-write `dict`-like view of the "BibDesk
      Static Groups", mapping each group name to a tuple of citation
      keys. Assigning a tuple of keys creates or replaces a group
      wholesale, and `del` removes one; per-key membership changes go
      through {meth}`add_to_group` / {meth}`remove_from_group`. Every
      mutation immediately refreshes the {attr}`Entry.groups` property of
      each affected entry.
    - {attr}`keywords`: a read-write `dict`-like view mapping each
      keyword to the tuple of citation keys of the entries carrying it,
      computed on demand from the entries' stored `keywords` fields.
      Those fields are readable but not writable through the entry
      `dict` interface, so the view is always consistent with the
      entries; mutations (assignment, `del`, {meth}`add_to_keyword`,
      {meth}`remove_from_keyword`) edit the affected entries' stored
      fields.
    - {attr}`duplicate_keys`: citation keys that could not be loaded
      because they duplicate an earlier entry (read-only).
    - {meth}`save`: writes the library back to disk. Entries that were
      not modified since load are re-rendered verbatim (byte-exact
      round-trip); modified or newly added entries are written in
      BibDesk's field order. The header timestamp is only bumped if
      something actually changed. A validation pass rejects entries
      that reference an undefined `@string` macro, and warns (without
      raising) about linked files (see {attr}`Entry.files`) that no
      longer exist on disk. {exc}`StaleFileError` is raised if the
      target file was modified on disk (e.g. resaved by BibDesk) since
      this library was loaded, unless `force=True`.
    - {meth}`add_file`, {meth}`replace_file`, {meth}`unlink_file`,
      {meth}`rename_file`: manage an entry's linked files
      ({attr}`Entry.files`, itself read-only). Linked files are stored
      relative to the library's `.bib` file, which only the `Library`
      knows, so these are `Library` operations.
    - {meth}`add_url`, {meth}`replace_url`, {meth}`remove_url`: manage an
      entry's linked URLs ({attr}`Entry.urls`, itself a read-only tuple).
      These delegate to the corresponding {class}`Entry` methods (URLs
      are self-contained, so unlike linked files they need no path
      resolution).
    - {meth}`render`, {meth}`export`, {meth}`edit`, {meth}`edit_strings`:
      render a bibliography, export to bibtex text, or edit in
      `$EDITOR`, for one or more selected citation keys at once.

    Three class attributes reflect the configuration (see the
    [configuration](configuration) reference page):

    - `Library.verify_types` (default `True`): whether an unrecognized
      {attr}`Entry.entry_type` is rejected with a `ValueError`.
    - `Library.verify_fields` (default `True`): whether assigning a
      field inappropriate for an entry's type emits a `UserWarning`.
    - `Library.config_file` (default `None`): an explicit
      `bibdeskparser.toml` path that takes precedence over the
      directory-based search.

    Constructing a `Library` (re)discovers a `bibdeskparser.toml`
    (`config_file`, then the `.bib` file's own directory -- the current
    working directory for a from-scratch library -- then the XDG
    location, first found wins) and applies it. The configuration is
    process-global; with no config file present, the defaults above
    give exactly the behavior of previous versions.

    ```python
    >>> from bibdeskparser import Entry, Library
    >>> bib = Library()  # a fresh, empty, in-memory library
    >>> bib.strings["jpb"] = "J. Phys. B"
    >>> bib.strings["jpb"]
    'J. Phys. B'
    >>> entry = Entry("article", "Key2026", fields={"title": "A Title"})
    >>> bib["Key2026"] = entry
    >>> bib["Key2026"] is entry
    True
    >>> len(bib)
    1

    ```

    Deleting a macro that is still referenced by an entry is rejected:

    ```python
    >>> import warnings
    >>> with warnings.catch_warnings():
    ...     warnings.simplefilter("ignore")
    ...     entry["journal"] = "jpb"  # a bare macro reference
    >>> del bib.strings["jpb"]
    Traceback (most recent call last):
        ...
    ValueError: cannot delete macro 'jpb': in use by entries ['Key2026']

    ```

    Group membership is mutated through `Library` itself, which keeps
    {attr}`Entry.groups` in sync immediately:

    ```python
    >>> bib.groups["My Papers"] = ()  # create an empty group
    >>> bib.add_to_group("My Papers", "Key2026")
    >>> bib["Key2026"].groups
    ('My Papers',)
    >>> bib.groups
    {'My Papers': ('Key2026',)}

    ```
    """

    def __init__(self, path=None, creator=None):
        self._path = path
        self._creator = creator

        # (Re)discover and apply the configuration for this library's
        # directory (the `.bib` file's folder, or the cwd for a
        # from-scratch library): Library.config_file, then that
        # directory, then the XDG location; first found wins.
        bib_dir = Path(path).resolve().parent if path is not None else None
        config.load(bib_dir=bib_dir, config_file=type(self).config_file)

        if path is not None:
            text = Path(path).read_text(encoding="utf-8")
            with _quiet_bibtexparser_block_type_logging():
                self._library = bibtexparser.parse_string(
                    text, parse_stack=parse_stack()
                )
        else:
            self._library = bibtexparser.Library()

        self._header_block, parsed_creator, self._timestamp = (
            _find_header_block(self._library)
        )
        if self._creator is None:
            self._creator = parsed_creator or _default_creator()

        self._groups_block = _find_groups_block(self._library)
        self._group_data = (
            parse_static_groups(self._groups_block.comment)
            if self._groups_block is not None
            else {}
        )

        self._entries = {}
        # A single one-pass reverse index over the group data to seed
        # every entry's `.groups`, rather than one scan over all groups
        # per entry.
        index = {}
        for name, keys in self._group_data.items():
            for key in keys:
                index.setdefault(key, []).append(name)
        for model_entry in list(self._library.entries):
            entry = Entry._wrap(
                model_entry
            )  # pylint: disable=protected-access
            entry._groups = tuple(  # pylint: disable=protected-access
                index.get(entry.key, ())
            )
            self._entries[entry.key] = entry

        self._strings_view = _StringsView(self)
        self._groups_view = _GroupsView(self)
        self._keywords_view = _KeywordsView(self)

        _check_duplicate_macro_values(self._library.strings_dict)
        self._modified = False

        if self.duplicate_keys:
            warnings.warn(
                f"duplicate citation keys found: {self.duplicate_keys}",
                UserWarning,
                stacklevel=2,
            )
        _check_unparseable_blocks(self._library.failed_blocks)

    def __repr__(self):
        return f"Library({self._path!r})"

    # -- path ------------------------------------------------------------ #

    @property
    def path(self):
        """The `.bib` file this library was loaded from, or last saved
        to (a `pathlib.Path`, read-only).

        `None` for a from-scratch library that has not been saved yet.
        """
        return None if self._path is None else Path(self._path)

    # -- timestamp ----------------------------------------------------- #

    @property
    def timestamp(self):
        """The save time from the header comment (a timezone-aware
        `datetime.datetime`, read-only).

        `None` for a from-scratch library that has not been saved yet.
        Updated by {meth}`save` whenever the library was actually
        modified.
        """
        return self._timestamp

    # -- strings --------------------------------------------------------- #

    @property
    def strings(self):
        """Read-write `dict`-like view of the `@string` macro
        definitions.

        Assigning a name validates that it is a valid BibDesk macro
        name (a subset of ASCII, no leading digit) and raises
        `ValueError` if it is not; the name is lowercased to match
        BibDesk's case-insensitive macro table, so `strings["PRA"] =
        ...` defines the same macro as `strings["pra"] = ...`.
        Deleting a name that is still referenced by any entry's field
        raises `ValueError` instead of leaving a dangling reference;
        use {meth}`rename_string` to rename a macro everywhere it is
        used in one step.
        """
        return self._strings_view

    def _macro_users(self, name):
        """Citation keys of entries with a bare field value equal to
        `name` (case-insensitively): the entries that reference the
        macro `name`."""
        lname = name.lower()
        users = []
        for entry in self._entries.values():
            for _, value in _bare_macro_fields(entry):
                if value.lower() == lname:
                    users.append(entry.key)
                    break
        return users

    def rename_string(self, old_name, new_name):
        """Rename the macro `old_name` to `new_name`.

        Updates the `@string` definition itself, and every entry field
        that bare-references `old_name` (case-insensitively) is
        rewritten to reference `new_name` instead (marking that entry
        as modified).

        Raises {exc}`KeyError` if `old_name` is not a defined macro,
        and {exc}`ValueError` if `new_name` is not a valid macro name
        or already names a different macro.
        """
        strings_dict = self._library.strings_dict
        if old_name not in strings_dict:
            raise KeyError(old_name)
        if not is_valid_macro_name(new_name, normalized=True):
            raise ValueError(f"invalid BibDesk macro name: {new_name!r}")
        if new_name in strings_dict:
            raise ValueError(f"macro {new_name!r} already exists")
        old_string = strings_dict[old_name]
        new_string = String(key=new_name, value=old_string.value)
        self._library.replace(
            old_string, new_string, fail_on_duplicate_key=True
        )
        lname = old_name.lower()
        for entry in self._entries.values():
            for field, value in _bare_macro_fields(entry):
                if value.lower() == lname:
                    field.value = new_name
                    entry._touch()  # pylint: disable=protected-access
        self._modified = True
        _check_duplicate_macro_values(self._library.strings_dict)

    # -- groups ------------------------------------------------------ #

    @property
    def groups(self):
        """Read-write `dict`-like view of the `BibDesk Static Groups`,
        mapping each group name to the tuple of the group's citation
        keys.

        Whole-group operations use the mapping interface --
        `library.groups[name] = (key, ...)` creates or replaces a
        group (an empty tuple creates an empty group), and
        `del library.groups[name]` deletes one -- while per-key
        membership changes go through {meth}`add_to_group` /
        {meth}`remove_from_group`. Values are always tuples: a group's
        membership cannot be mutated in place, only replaced or edited
        through those methods.

        Assigned keys must be citation keys of entries in this
        library (`KeyError` otherwise); a single string is rejected
        with `TypeError` (pass a tuple or list of keys), and duplicate
        keys are silently dropped. Keys loaded from a `.bib` file
        whose entries are absent (stale groups data) are preserved.

        Every mutation immediately refreshes the `groups` property of
        each affected {class}`Entry`, so the two
        views are always consistent. Deleting an entry from the
        library (or renaming one via {meth}`rekey`) likewise updates
        the group data, so groups never accumulate dangling keys.
        """
        return self._groups_view

    def _groups_of_key(self, key):
        """The names of the groups containing `key`, in group order (a
        tuple)."""
        return tuple(
            name for name, keys in self._group_data.items() if key in keys
        )

    def _set_group(self, name, keys):
        """Create/replace (`keys` a tuple) or delete (`keys` is
        `None`) the group `name`.

        The single choke point through which every group mutation
        goes, so the `groups` property of each affected entry is
        refreshed in exactly one place."""
        old = self._group_data.get(name)
        if keys is None:
            if old is None:
                raise KeyError(name)
            del self._group_data[name]
            new = ()
        else:
            self._group_data[name] = keys
            new = keys
        for key in set(old or ()) ^ set(new):
            entry = self._entries.get(key)
            if entry is not None:
                # pylint: disable=protected-access
                entry._groups = self._groups_of_key(key)
        self._modified = True

    def _normalize_group_keys(self, keys, current=()):
        """Validate `keys` as group members; return them as a
        deduplicated tuple.

        Raises `TypeError` if `keys` is a single string (almost
        certainly a mistake: iterating it would yield characters) or
        contains a non-string, and `KeyError` for a key that does not
        correspond to an entry in this library -- except keys already
        in `current` (a group's existing members), so that stale keys
        loaded from a `.bib` file can be carried along."""
        if isinstance(keys, str):
            raise TypeError(
                "group keys must be given as an iterable of citation "
                f"keys, not a single string: {keys!r}"
            )
        current = set(current)
        result = []
        seen = set()
        for key in keys:
            if not isinstance(key, str):
                raise TypeError(
                    f"citation key must be a str, not {type(key)!r}"
                )
            if key in seen:
                continue
            seen.add(key)
            if key not in self._entries and key not in current:
                raise KeyError(
                    f"cannot add {key!r} to a group: no such entry in "
                    "this library"
                )
            result.append(key)
        return tuple(result)

    def _assign_group(self, name, keys):
        """Backing implementation of `library.groups[name] = keys`."""
        current = self._group_data.get(name, ())
        keys = self._normalize_group_keys(keys, current=current)
        if name not in self._group_data or keys != current:
            self._set_group(name, keys)

    def _delete_group(self, name):
        """Backing implementation of `del library.groups[name]`."""
        self._set_group(name, None)

    def add_to_group(self, name, *keys):
        """Add the citation `keys` to the existing group `name`.

        Keys that are already members are silently skipped. Raises
        `KeyError` if no group named `name` exists (create groups
        explicitly, via `library.groups[name] = ()`), or if any key
        does not correspond to an entry in this library. The `groups`
        property of every affected entry is refreshed immediately.
        """
        current = self._group_data[name]
        keys = self._normalize_group_keys(keys, current=current)
        merged = current + tuple(k for k in keys if k not in current)
        if merged != current:
            self._set_group(name, merged)

    def remove_from_group(self, name, *keys):
        """Remove the citation `keys` from the group named `name`.

        Keys that are not members are silently skipped. Raises
        `KeyError` if no group named `name` exists. The `groups`
        property of every affected entry is refreshed immediately.
        """
        current = self._group_data[name]
        remove = set(keys)
        remaining = tuple(k for k in current if k not in remove)
        if remaining != current:
            self._set_group(name, remaining)

    # -- keywords ------------------------------------------------------- #

    @property
    def keywords(self):
        """Read-write `dict`-like view mapping each keyword to the
        tuple of citation keys of the entries carrying it.

        The mapping is always consistent with the entries' stored
        `keywords` fields (which are readable but not writable through
        the entry `dict` interface; see {attr}`Entry.keywords`).

        Assigning `library.keywords[keyword] = (key, ...)` makes
        exactly those entries carry `keyword`; `del
        library.keywords[keyword]` removes it from every entry.
        Per-key changes go through {meth}`add_to_keyword` /
        {meth}`remove_from_keyword`. All of these edit the affected
        entries' stored `keywords` field, bumping their
        `date-modified` and marking them modified (unlike group
        mutations, which only affect the groups `@comment` block).

        A keyword exists only as part of some entry's `keywords`
        field, so an *empty* keyword cannot be represented: assigning
        `()` is equivalent to deleting the keyword.
        """
        return self._keywords_view

    @staticmethod
    def _check_keyword(keyword):
        """Validate `keyword`; return it stripped of surrounding
        whitespace.

        Raises `TypeError` for a non-string, and `ValueError` for an
        empty keyword or one containing a comma (the separator in the
        stored `keywords` field)."""
        if not isinstance(keyword, str):
            raise TypeError(f"keyword must be a str, not {type(keyword)!r}")
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword must not be empty")
        if "," in keyword:
            raise ValueError(
                f"invalid keyword {keyword!r}: the comma separates "
                "keywords in the stored keywords field"
            )
        return keyword

    def add_to_keyword(self, keyword, *keys):
        """Add `keyword` to the entries with the given citation
        `keys`.

        Edits each affected entry's stored `keywords` field (bumping
        its `date-modified` and marking it modified); entries already
        carrying `keyword` are silently skipped. A keyword that no
        entry carried before is thereby created -- keywords exist only
        inside entries, so there is no separate creation step (unlike
        groups). Raises `KeyError` (before any entry is modified) if
        any key is not in this library, and `ValueError` for an
        invalid keyword (empty, or containing a comma).
        """
        keyword = self._check_keyword(keyword)
        entries = [self._entries[key] for key in keys]
        for entry in entries:
            current = entry.keywords
            if keyword not in current:
                # pylint: disable=protected-access
                entry._set_keywords(current + (keyword,))

    def remove_from_keyword(self, keyword, *keys):
        """Remove `keyword` from the entries with the given citation
        `keys`.

        The mirror image of {meth}`add_to_keyword`: entries not
        carrying `keyword` are silently skipped, and `KeyError` is
        raised (before any entry is modified) if any key is not in
        this library.
        """
        if isinstance(keyword, str):
            keyword = keyword.strip()
        entries = [self._entries[key] for key in keys]
        for entry in entries:
            current = entry.keywords
            if keyword in current:
                # pylint: disable=protected-access
                entry._set_keywords(k for k in current if k != keyword)

    def _assign_keyword(self, keyword, keys):
        """Backing implementation of `library.keywords[keyword] =
        keys`: make exactly the entries with citation keys `keys`
        carry `keyword` (assigning an empty `keys` removes the keyword
        everywhere)."""
        keyword = self._check_keyword(keyword)
        if isinstance(keys, str):
            raise TypeError(
                "keyword keys must be given as an iterable of citation "
                f"keys, not a single string: {keys!r}"
            )
        keys = list(dict.fromkeys(keys))
        missing = [key for key in keys if key not in self._entries]
        if missing:
            raise KeyError(f"no such entries in this library: {missing}")
        current = [
            key
            for key, entry in self._entries.items()
            if keyword in entry.keywords
        ]
        self.remove_from_keyword(
            keyword, *(key for key in current if key not in keys)
        )
        self.add_to_keyword(
            keyword, *(key for key in keys if key not in current)
        )

    def _delete_keyword(self, keyword):
        """Backing implementation of `del library.keywords[keyword]`."""
        members = [
            key
            for key, entry in self._entries.items()
            if keyword in entry.keywords
        ]
        if not members:
            raise KeyError(keyword)
        self.remove_from_keyword(keyword, *members)

    # -- duplicate keys -------------------------------------------------- #

    @property
    def duplicate_keys(self):
        """Citation keys that could not be loaded because they
        duplicate an earlier entry (a `tuple`, read-only).

        BibDesk itself tolerates a `.bib` file with duplicate citation
        keys, keeping only the first entry for each one; this property
        lists the keys for which a later, duplicate entry was
        discarded this way.
        """
        return tuple(
            block.key
            for block in self._library.failed_blocks
            if isinstance(block, DuplicateBlockKeyBlock)
        )

    # -- dict interface (entries) ---------------------------------------- #

    @property
    def entries(self):
        """All entries in the library, as a `list` of
        {class}`Entry`."""
        return list(self._entries.values())

    def __getitem__(self, key):
        return self._entries[key]

    def __setitem__(self, key, entry):
        if not isinstance(entry, Entry):
            raise TypeError(f"value must be an Entry, not {type(entry)!r}")
        for existing_key, existing_entry in self._entries.items():
            if existing_entry is entry and existing_key != key:
                # `entry` is already tracked under a different key: this
                # can only be an intentional rename (e.g. `bib[new] =
                # bib[old]`), since a genuinely new/foreign Entry can
                # never be identical to one already in self._entries.
                self.rekey(existing_key, key)
                return
        if entry.key != key:
            # A brand new entry (or one from elsewhere) adopts the key
            # it is being added under. `Entry.key` itself is read-only,
            # so this bypasses the property.
            entry._entry.key = key  # pylint: disable=protected-access
            entry._touch()  # pylint: disable=protected-access
        # An Entry is assumed to belong to at most one Library; this is
        # not checked/enforced.
        if key in self._entries:
            old = self._entries[key]
            if old is not entry:
                self._library.replace(
                    old._entry,  # pylint: disable=protected-access
                    entry._entry,  # pylint: disable=protected-access
                    fail_on_duplicate_key=True,
                )
                old._groups = ()  # pylint: disable=protected-access
        else:
            self._library.add([entry._entry], fail_on_duplicate_key=True)
            # Sets date-added (only if not already set) and marks the
            # entry dirty, matching BibDesk's "adding sets date-added"
            # behavior.
            entry._touch()  # pylint: disable=protected-access
        entry._groups = (  # pylint: disable=protected-access
            self._groups_of_key(key)
        )
        self._entries[key] = entry
        self._modified = True

    def __delitem__(self, key):
        entry = self._entries.pop(key)
        self._library.remove(
            [entry._entry]
        )  # pylint: disable=protected-access
        entry._groups = ()  # pylint: disable=protected-access
        # Deleting an entry also removes its citation key from every
        # static group, so `groups` never holds dangling keys. The
        # entry was popped above, so `_set_group`'s refresh skips it.
        for name, keys in list(self._group_data.items()):
            if key in keys:
                self._set_group(name, tuple(k for k in keys if k != key))
        self._modified = True

    def rekey(self, old_key, new_key):
        """Rename the entry at `old_key` to `new_key`.

        `Entry.key` is read-only, so this is the only way to rename
        an entry that is already in the library. The entry's
        static-group memberships follow the rename: `new_key` replaces
        `old_key` in place (keeping its position) in every group that
        contained it. Raises `KeyError` if `old_key` is not present,
        or `ValueError` if `new_key` is already used by a different
        entry.
        """
        if old_key not in self._entries:
            raise KeyError(old_key)
        if new_key == old_key:
            return
        if new_key in self._entries:
            raise ValueError(
                f"key {new_key!r} is already used by another entry in "
                "this library"
            )
        # Rewrite the group data first (keeping each key's position
        # within its group), so that the `__delitem__` cascade below
        # finds nothing left to remove; `__setitem__` then restores
        # `entry.groups` from the rewritten data.
        for name, keys in list(self._group_data.items()):
            if old_key in keys:
                self._group_data[name] = tuple(
                    new_key if k == old_key else k for k in keys
                )
                self._modified = True
        self[new_key] = self.pop(old_key)

    def __iter__(self):
        return iter(self._entries)

    def __len__(self):
        return len(self._entries)

    # -- file attachments -------------------------------------------- #

    def _files_base_dir(self):
        """The directory that linked-file paths are relative to (the
        library file's directory), as a resolved `Path`.

        Raises `ValueError` if the library has no file path yet."""
        if self._path is None:
            raise ValueError(
                "cannot modify file attachments of a library that has "
                "no file path (linked files are stored relative to the "
                "library's .bib file); save the library first"
            )
        return Path(self._path).resolve().parent

    def _resolve_file_arg(self, filename, *, must_exist):
        """Resolve `filename` (a new file to be attached) to an
        absolute path, interpreting a relative path against both the
        library directory and the current working directory (see
        {meth}`add_file` for the exact rules)."""
        base_dir = self._files_base_dir()
        path = Path(filename)
        if path.is_absolute():
            if must_exist and not path.exists():
                raise FileNotFoundError(f"No such file: {path}")
            return path
        lib_candidate = base_dir / path
        cwd_candidate = Path.cwd() / path
        if lib_candidate.resolve() == cwd_candidate.resolve():
            if must_exist and not lib_candidate.exists():
                raise FileNotFoundError(f"No such file: {lib_candidate}")
            return lib_candidate
        lib_exists = lib_candidate.exists()
        cwd_exists = cwd_candidate.exists()
        if lib_exists and cwd_exists:
            raise ValueError(
                f"ambiguous filename {str(filename)!r}: exists both "
                f"relative to the library ({lib_candidate}) and to "
                f"the current working directory ({cwd_candidate}); "
                "pass an absolute path"
            )
        if cwd_exists:
            return cwd_candidate
        if must_exist and not lib_exists:
            raise FileNotFoundError(
                f"No such file: {str(filename)!r} (checked relative "
                f"to the library, {lib_candidate}, and to the current "
                f"working directory, {cwd_candidate})"
            )
        return lib_candidate

    def _match_attachment(self, entry, filename):
        """The path in `entry.files` that `filename` refers to,
        resolving a relative `filename` against both the library
        directory and the current working directory. Raises
        `ValueError` if `filename` matches no attachment of `entry`,
        or ambiguously matches two different ones."""
        base_dir = self._files_base_dir()
        by_abs_path = {}
        for rel_path in entry.files:
            by_abs_path.setdefault((base_dir / rel_path).resolve(), rel_path)
        path = Path(filename)
        if path.is_absolute():
            candidates = [path.resolve()]
        else:
            candidates = [(base_dir / path).resolve()]
            cwd_candidate = (Path.cwd() / path).resolve()
            if cwd_candidate != candidates[0]:
                candidates.append(cwd_candidate)
        matches = {
            by_abs_path[candidate]
            for candidate in candidates
            if candidate in by_abs_path
        }
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous filename {str(filename)!r}: matches "
                f"multiple linked files of entry {entry.key!r} "
                f"({sorted(matches)}); pass an absolute path"
            )
        if not matches:
            raise ValueError(
                f"{str(filename)!r} is not linked from entry " f"{entry.key!r}"
            )
        return matches.pop()

    def _remove_linked_file(self, rel_path):
        """Delete the linked file `rel_path` (relative to the library
        directory) from the filesystem, unless it is still linked
        from any entry, in which case a `UserWarning` is emitted
        instead. A file already absent from disk is silently
        ignored."""
        base_dir = self._files_base_dir()
        abs_path = (base_dir / rel_path).resolve()
        still_linked = [
            entry.key
            for entry in self._entries.values()
            if any(
                (base_dir / rel).resolve() == abs_path for rel in entry.files
            )
        ]
        if still_linked:
            warnings.warn(
                f"not removing {rel_path!r}: still linked from "
                f"entries {still_linked}",
                UserWarning,
                stacklevel=3,
            )
            return
        if abs_path.exists():
            _delete_file(abs_path)

    def add_file(self, key, filename, *, check_that_file_exists=True):
        """Attach the file `filename` to entry `key`, appending a
        `bdsk-file-N` field (see
        {attr}`Entry.files`).

        * `key`: citation key of the entry (raises `KeyError` if not
          in the library).
        * `filename`: path of the file to attach: absolute, or
          relative to the library's `.bib` directory or to the
          current working directory. A relative path that exists in
          *both* places (and they are not the same place) raises
          `ValueError`; pass an absolute path to disambiguate.
        * `check_that_file_exists`: if `True` (the default), raise
          `FileNotFoundError` if `filename` does not exist. If
          `False`, a nonexistent `filename` is recorded as-is,
          interpreted relative to the library directory, as a
          path-only attachment without a macOS bookmark (useful,
          e.g., for a file that only exists on another machine).

        The stored path is always relative to the library directory.
        For a file that exists, a macOS bookmark is generated
        automatically (requires the `bibdeskparser[macos]` extra) so
        BibDesk can still find the file if it is later moved or
        renamed; where a bookmark can't be created, the file is
        attached by path only, with a `UserWarning`.

        Raises `ValueError` if the file is already attached to the
        entry, or if this library has no file path yet (a
        from-scratch library must be saved first, so that relative
        paths are well-defined).
        """
        entry = self._entries[key]
        base_dir = self._files_base_dir()
        path = self._resolve_file_arg(
            filename, must_exist=check_that_file_exists
        )
        bdsk_file = BibDeskFile(
            path, relative_to=base_dir, must_exist=check_that_file_exists
        )
        if bdsk_file.relative_path in entry.files:
            raise ValueError(
                f"{bdsk_file.relative_path!r} is already attached to "
                f"entry {key!r}"
            )
        # pylint: disable=protected-access
        entry._set_files(entry._file_objects() + [bdsk_file])

    def replace_file(
        self,
        key,
        old_filename,
        new_filename,
        *,
        remove,
        check_that_file_exists=True,
    ):
        """Replace entry `key`'s attached file `old_filename` with
        `new_filename`, keeping its position in
        {attr}`Entry.files`.

        * `key`: citation key of the entry (raises `KeyError` if not
          in the library).
        * `old_filename`: the attachment to replace; must match one
          of the entry's linked files (else `ValueError`). A relative
          path is matched against both its library-relative and its
          CWD-relative interpretation (`ValueError` if that is
          ambiguous).
        * `new_filename`: the file to attach in its place, resolved
          exactly like the `filename` argument of {meth}`add_file`
          (raises `ValueError` if it is already attached to the
          entry).
        * `remove` (mandatory keyword argument): whether to also
          delete the old file from the filesystem -- to the Trash on
          macOS (with the `bibdeskparser[macos]` extra installed),
          else permanently. The old file is *not* deleted (a
          `UserWarning` instead) if it is still linked from any
          entry; a file already absent from disk is silently ignored.
        * `check_that_file_exists`: as in {meth}`add_file`, for
          `new_filename`.

        Raises `ValueError` if this library has no file path yet
        (see {meth}`add_file`).
        """
        entry = self._entries[key]
        base_dir = self._files_base_dir()
        old_rel = self._match_attachment(entry, old_filename)
        path = self._resolve_file_arg(
            new_filename, must_exist=check_that_file_exists
        )
        new_file = BibDeskFile(
            path, relative_to=base_dir, must_exist=check_that_file_exists
        )
        files = entry._file_objects()  # pylint: disable=protected-access
        if any(
            f.relative_path == new_file.relative_path
            for f in files
            if f.relative_path != old_rel
        ):
            raise ValueError(
                f"{new_file.relative_path!r} is already attached to "
                f"entry {key!r}"
            )
        # pylint: disable=protected-access
        entry._set_files(
            [new_file if f.relative_path == old_rel else f for f in files]
        )
        if remove:
            self._remove_linked_file(old_rel)

    def unlink_file(self, key, filename, *, remove):
        """Remove the file `filename` from entry `key`'s attachments
        ({attr}`Entry.files`).

        * `key`: citation key of the entry (raises `KeyError` if not
          in the library).
        * `filename`: the attachment to unlink, matched like the
          `old_filename` argument of {meth}`replace_file`.
        * `remove` (mandatory keyword argument): whether to also
          delete the file from the filesystem, with the exact
          semantics of {meth}`replace_file`'s `remove`.

        Raises `ValueError` if this library has no file path yet
        (see {meth}`add_file`).
        """
        entry = self._entries[key]
        rel_path = self._match_attachment(entry, filename)
        # pylint: disable=protected-access
        entry._set_files(
            [f for f in entry._file_objects() if f.relative_path != rel_path]
        )
        if remove:
            self._remove_linked_file(rel_path)

    def rename_file(self, key, old_filename, new_filename):
        """Rename (or move) entry `key`'s attached file
        `old_filename` to `new_filename` on the filesystem, updating
        *every* entry that links the file (each with a fresh macOS
        bookmark, where available).

        * `key`: citation key of an entry linking the file (raises
          `KeyError` if not in the library). Other entries linking
          the same file are updated as well, so their
          {attr}`Entry.files` never go stale.
        * `old_filename`: the attachment to rename, matched like the
          `old_filename` argument of {meth}`replace_file`; the file
          must exist on disk (else `FileNotFoundError`).
        * `new_filename`: the new name. A bare filename (no directory
          component) renames the file within its current directory;
          a relative path with a directory component is interpreted
          relative to the library's `.bib` directory; an absolute
          path is used as-is. Raises `FileExistsError` if the target
          already exists.

        Raises `ValueError` if this library has no file path yet
        (see {meth}`add_file`).
        """
        entry = self._entries[key]
        base_dir = self._files_base_dir()
        old_rel = self._match_attachment(entry, old_filename)
        old_path = (base_dir / old_rel).resolve()
        if not old_path.exists():
            raise FileNotFoundError(f"No such file: {old_path}")
        new_path = Path(new_filename)
        if not new_path.is_absolute():
            if new_path.parent == Path("."):
                new_path = old_path.parent / new_path
            else:
                new_path = base_dir / new_path
        if new_path.exists():
            raise FileExistsError(f"File already exists: {new_path}")
        os.rename(old_path, new_path)
        new_file = BibDeskFile(new_path, relative_to=base_dir)
        for other in self._entries.values():
            # pylint: disable=protected-access
            files = other._file_objects()
            changed = False
            for i, bdsk_file in enumerate(files):
                resolved = (base_dir / bdsk_file.relative_path).resolve()
                if resolved == old_path:
                    files[i] = new_file
                    changed = True
            if changed:
                other._set_files(files)

    # -- urls -------------------------------------------------------- #

    def add_url(self, key, url):
        """Attach `url` to entry `key`, appending a `bdsk-url-N` field
        (see {attr}`Entry.urls`).

        * `key`: citation key of the entry (raises `KeyError` if not in
          the library).
        * `url`: the URL to attach; must include both a scheme and a
          host (e.g. `https://example.com/paper.pdf`), or `ValueError`
          is raised. Raises `ValueError` if `url` is already linked
          from the entry.

        Unlike file attachments, URLs are self-contained (there is no
        path resolution and no on-disk file to remove), so this simply
        delegates to {meth}`Entry.add_url`.
        """
        self._entries[key].add_url(url)

    def replace_url(self, key, old_url, new_url):
        """Replace entry `key`'s linked `old_url` with `new_url`,
        keeping its position in {attr}`Entry.urls`.

        * `key`: citation key of the entry (raises `KeyError` if not in
          the library).
        * `old_url`: the linked URL to replace (raises `ValueError` if
          it is not linked from the entry).
        * `new_url`: the URL to link in its place (raises `ValueError`
          if it is not a valid URL, or is already linked from the
          entry).

        Delegates to {meth}`Entry.replace_url`.
        """
        self._entries[key].replace_url(old_url, new_url)

    def remove_url(self, key, url):
        """Remove `url` from entry `key`'s linked URLs (see
        {attr}`Entry.urls`).

        * `key`: citation key of the entry (raises `KeyError` if not in
          the library).
        * `url`: the linked URL to remove (raises `ValueError` if it is
          not linked from the entry).

        Delegates to {meth}`Entry.remove_url`.
        """
        self._entries[key].remove_url(url)

    # -- saving ------------------------------------------------------ #

    def _validate_for_save(self, path):
        """Raise/warn as documented by {meth}`save`."""
        undefined = set()
        strings_dict = self._library.strings_dict
        for entry in self._entries.values():
            for _, value in _bare_macro_fields(entry):
                if (
                    is_valid_macro_name(value, normalized=True)
                    and value not in strings_dict
                ):
                    undefined.add(value)
        if undefined:
            raise ValueError(
                "undefined macro(s) referenced by one or more entries: "
                f"{sorted(undefined)}"
            )

        base_dir = Path(path).parent
        for entry in self._entries.values():
            for rel_path in entry.files:
                if not (base_dir / rel_path).exists():
                    warnings.warn(
                        f"{entry.key}: linked file does not exist: "
                        f"{rel_path!r}",
                        UserWarning,
                        stacklevel=3,
                    )

    def save(self, path=None, force=False):
        """Write the library to `path` (default: the path it was
        loaded from).

        * `path`: destination `.bib` file. Defaults to the path this
          library was loaded from (or last saved to); raises
          {exc}`ValueError` if there is none (a from-scratch library
          that has never been given a path).
        * `force`: bypass the {exc}`StaleFileError` check (see below).

        If the library was not modified since it was loaded (no entry
        was modified, {attr}`groups` was not mutated, and no
        entries/strings were added or removed),
        the file is written byte-identical to how it was parsed (or,
        for a from-scratch library, is simply rendered), and the
        header timestamp is *not* touched. Otherwise: the header
        timestamp is updated (synthesizing a header if the library did
        not already have one), the static-groups `@comment` block is
        re-rendered from the current {attr}`groups` (synthesizing the
        block if the library did not have one but now has groups),
        dirty/new entries have their fields reordered into BibDesk's
        canonical order, and {attr}`timestamp` is updated.

        Before writing, raises {exc}`ValueError` if any entry
        references an undefined `@string` macro, and warns (without
        raising) about any linked file
        ({attr}`Entry.files`) that does not exist
        relative to `path`'s directory (such files may legitimately
        live only on another machine).

        Raises {exc}`StaleFileError` if `path` already exists and its
        header timestamp is strictly newer than {attr}`timestamp`
        (i.e., it was saved -- by BibDesk or otherwise -- after this
        library was loaded or last saved), unless `force=True`.
        """
        path = path if path is not None else self._path
        if path is None:
            raise ValueError(
                "no path given and this library was not loaded from a file"
            )
        path = Path(path)

        if path.exists():
            on_disk_timestamp = peek_timestamp(path)
            if (
                on_disk_timestamp is not None
                and self._timestamp is not None
                and on_disk_timestamp > self._timestamp
                and not force
            ):
                raise StaleFileError(
                    f"{path} has a newer save timestamp "
                    f"({on_disk_timestamp}) than this library "
                    f"({self._timestamp}); it appears to have been "
                    "modified on disk since it was loaded. Pass "
                    "force=True to overwrite anyway."
                )

        self._validate_for_save(path)

        pristine = not self._modified and not any(
            entry._dirty  # pylint: disable=protected-access
            for entry in self._entries.values()
        )

        if pristine:
            path.write_text(render_library(self._library), encoding="utf-8")
            self._path = path
            return

        # Truncated to whole seconds: that is all the header format
        # (see `bibdeskparser.header`) can represent, so keeping
        # sub-second precision in memory would make `self._timestamp`
        # diverge from what a subsequent load of this same file would
        # report.
        now = datetime.datetime.now().astimezone().replace(microsecond=0)

        if self._header_block is not None:
            self._header_block.comment = update_header(
                self._header_block.comment, now
            )
        else:
            header_block = ImplicitComment(make_header(self._creator, now))
            self._library = bibtexparser.Library(
                blocks=[header_block] + self._library.blocks
            )
            self._header_block = header_block

        # Re-render the groups comment unconditionally: when the group
        # data was not touched, this is byte-identical to the parsed
        # comment (parse/render round-trip exactly).
        if self._groups_block is not None:
            self._groups_block.comment = render_static_groups(self._group_data)
        elif self._group_data:
            groups_block = ExplicitComment(
                render_static_groups(self._group_data)
            )
            self._library.add([groups_block], fail_on_duplicate_key=False)
            self._groups_block = groups_block

        for entry in self._entries.values():
            # pylint: disable=protected-access
            if entry._dirty:
                entry._entry.fields = bibdesk_field_order(entry._entry.fields)

        self._timestamp = now
        path.write_text(render_library(self._library), encoding="utf-8")

        self._path = path
        self._modified = False
        for entry in self._entries.values():
            # `Entry` intentionally has no public "mark clean" method
            # (only its owning `Library` may reset `dirty`, once the
            # entry's current state has actually been written to
            # disk). Both modules are part of the same package, so
            # this reaches across a module boundary but not a public
            # API boundary.
            entry._dirty = False  # pylint: disable=protected-access

    # -- search/render/export/edit ---------------------------------------#

    def search(self, query, *, fields=None, match="words"):
        r"""Return a list of the entries matching `query`, best match
        first.

        ```python
        results = library.search(query, fields=None, match="words")
        ```

        For every searched field, the query is matched against the
        stored value (bare `@string` macro names like `pra` intact),
        the decoded Unicode value, and -- for a bare `@string` macro
        reference -- the macro's expansion. Thus, an entry with
        `journal = pra` is found both by searching for `"pra"` and for
        `"Phys. Rev. A"`. A query containing TeX markup is decoded
        before matching, so searching for `Schr{\"o}dinger` finds
        `Schrödinger`.

        By default, the citation key and all fields of each entry are
        searched; `fields` (an iterable of field names, or a single
        name) restricts the search, with the pseudo-field name `"key"`
        selecting the citation key. Fields an entry does not have are
        skipped.

        `match` sets the match strictness. The first four levels form
        a ladder -- each level matches everything the previous one
        does, plus more -- and are all case-insensitive:

        * `"exact"`: the query occurs verbatim (up to case) as a
          substring of a raw or decoded value.
        * `"folded"`: additionally ignores accents, including their
          transliterations: `"Schrodinger"` and `"Schroedinger"` both
          find `"Schrödinger"`.
        * `"words"` (the default): additionally matches when most of
          the query's words occur in a value, in any order (e.g. a
          title search from a partially remembered phrase).
        * `"fuzzy"`: additionally tolerates small typos in individual words.
           Two words count as a fuzzy match when they agree on about 80% of
           their letters, and at least 70% of the query's words must match.
        * `"regex"`: the query is a regular expression, tried against
          the raw and decoded values, with standard {mod}`re`
          semantics (case-sensitive unless the pattern says `(?i)`).
          An invalid pattern raises {exc}`ValueError`.

        Any other `match` value raises {exc}`ValueError`. Entries
        matching at a stricter ladder level rank above looser matches;
        ties keep the library's entry order.

        ```python
        >>> from bibdeskparser import Entry, Library
        >>> bib = Library()
        >>> bib["Schroedinger1926"] = Entry(
        ...     "article",
        ...     "Schroedinger1926",
        ...     fields={
        ...         "author": "Schrödinger, Erwin",
        ...         "title": "Quantisierung als Eigenwertproblem",
        ...     },
        ... )
        >>> [e.key for e in bib.search("Schrodinger")]
        ['Schroedinger1926']
        >>> [e.key for e in bib.search("Schroedinger", fields=["author"])]
        ['Schroedinger1926']
        >>> [e.key for e in bib.search("eigenwertproblem quantisierung")]
        ['Schroedinger1926']

        ```
        """
        return search_entries(
            self.values(),
            query,
            strings=dict(self.strings),
            fields=fields,
            match=match,
        )

    def render(self, *keys, format="markdown", style="default"):
        # pylint: disable=redefined-builtin
        """Render a bibliography for the entries with the given
        citation `keys` (at least one required).

        `format` is one of `"markdown"`, `"tex"`, or `"html"`. `style`
        controls the layout of the citations relative to one another:

        * `"paragraphs"`: each citation is a paragraph, separated by a
          blank line (for `"html"`, wrapped in `<p>...</p>` instead).
        * `"numbered list"`: a numbered list (`markdown` `1.`, `2.`;
          `tex` `enumerate`; `html` `<ol>`).
        * `"itemized list"`: a bulleted list (`markdown` `-`; `tex`
          `itemize`; `html` `<ul>`).
        * `"default"` (the default): like `"paragraphs"`, except a
          single `"html"` citation is not wrapped in `<p>...</p>`.
        """
        return render_entries(
            [self[key] for key in keys], format=format, style=style
        )

    def export(self, *keys, format="default", outfile=None):
        # pylint: disable=redefined-builtin
        """Export the entries with the given citation `keys` (at
        least one required) as bibtex text.

        `format` is one of `"default"` (Unicode, as displayed by the
        `dict` interface), `"raw"` (the literal, possibly TeX-encoded,
        stored values), or `"minimal"` (only the fields needed to
        typeset a bibliography). For `"default"`/`"raw"`, the
        `@string` macro definitions needed to make the selected
        entries self-contained are included.
        """
        return export_entries(
            [self[key] for key in keys],
            strings=dict(self.strings),
            format=format,
            outfile=outfile,
        )

    def edit(self, *keys, format="default", editor=None):
        # pylint: disable=redefined-builtin
        """Edit the entries with the given citation `keys` (at least
        one required) together, in `editor` (or `$EDITOR`), merging
        changes back into them (and into `.strings`) in place.
        """
        editing.edit_entries(
            [self[key] for key in keys],
            library=self,
            format=format,
            editor=editor,
        )

    def edit_strings(self, editor=None):
        """Edit `.strings` in `editor` (or `$EDITOR`), merging changes
        back in place.
        """
        editing.edit_strings(self, editor=editor)
