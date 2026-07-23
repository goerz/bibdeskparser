"""The `Library` class and the `StaleFileError` it may raise."""

import datetime
import getpass
import logging
import os
import shutil
import sys
import warnings
from collections.abc import MutableMapping
from contextlib import contextmanager
from pathlib import Path

import bibtexparser
from bibtexparser.model import DuplicateBlockKeyBlock
from bibtexparser.model import Entry as _RawEntry
from bibtexparser.model import (
    ExplicitComment,
    ImplicitComment,
    ParsingFailedBlock,
    String,
)

from . import editing, specifiers
from .bdskfile import BibDeskFile
from .config import active
from .entry import Entry, _strip_enclosing
from .exporting import export_entries
from .groups import (
    is_groups_comment,
    is_static_groups_comment,
    parse_static_groups,
    render_static_groups,
)
from .header import make_header, parse_header, peek_timestamp, update_header
from .importing import import_entries
from .macros import (
    STANDARD_MACROS,
    MacroString,
    ValueString,
    is_valid_macro_name,
    normalize_macro_name,
)
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


def _expand_macros(entry, strings):
    """Return a copy of `entry` with every field that is a bare
    `@string` macro reference replaced by its literal value from
    `strings` (an undefined macro is left as the macro name).

    Used by {meth}`Library.render` so that a citation shows the resolved
    value (e.g. the full journal name) rather than the macro name.
    """
    expanded = entry.copy()
    for key in list(entry):
        value = entry[key]
        if isinstance(value, MacroString):
            resolved = strings.get(str(value), str(value))
            expanded[key] = ValueString(resolved)
    return expanded


def _has_field(entry, name):
    """Whether field `name` is defined on `entry` with a non-empty
    (not whitespace-only) value.

    A defined-but-empty field counts as missing everywhere, because
    BibDesk deletes empty fields when it saves a `.bib` file, so an
    empty value cannot carry information.
    """
    try:
        value = entry[name]
    except KeyError:
        return False
    return bool(str(value).strip())


def _names(value):
    """The argument `value` (`None`, a single string, or an iterable
    of strings) as a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


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


def _is_groups_comment_block(block):
    """Whether `block` is any of BibDesk's group-storing `@comment`
    blocks (static, smart, URL, or script groups)."""
    return isinstance(block, ExplicitComment) and is_groups_comment(
        block.comment
    )


def _hoist_last_block_above_groups(raw_library):
    """Move the just-appended last block of `raw_library` up, directly
    above the first BibDesk group `@comment` block (no-op if there is
    none).

    `bibtexparser.Library.add` always appends, but BibDesk's canonical
    layout keeps the group `@comment` blocks at the very end of the
    file, so a newly added entry (or a newly synthesized static-groups
    block) must be placed above them. `raw_library.blocks` is the
    library's actual block list, so it can be reordered in place;
    reordering does not affect bibtexparser's by-key lookups.
    """
    blocks = raw_library.blocks
    for i, block in enumerate(blocks[:-1]):
        if _is_groups_comment_block(block):
            blocks.insert(i, blocks.pop())
            return


def _place_string_block(raw_library):
    """Move the just-appended `@string` block of `raw_library` to its
    canonical position.

    BibDesk keeps all `@string` definitions in a single alphabetically
    sorted run between the header and the first entry. The new block
    goes at its sorted position within the existing `@string` blocks;
    if there are none, it goes above the first entry (a failed block,
    e.g. for a duplicate key, counts as an entry) or, failing that,
    above the group `@comment` blocks. See
    `_hoist_last_block_above_groups` for why in-place reordering of
    `raw_library.blocks` is safe.
    """
    blocks = raw_library.blocks
    key = blocks[-1].key.lower()
    string_indices = [
        i for i, block in enumerate(blocks[:-1]) if isinstance(block, String)
    ]
    if string_indices:
        target = string_indices[-1] + 1  # after the last `@string`
        for i in string_indices:
            if blocks[i].key.lower() > key:
                target = i
                break
        blocks.insert(target, blocks.pop())
        return
    for i, block in enumerate(blocks[:-1]):
        if isinstance(
            block, (_RawEntry, ParsingFailedBlock)
        ) or _is_groups_comment_block(block):
            blocks.insert(i, blocks.pop())
            return


# -- views ------------------------------------------------------------- #


class _StringsView(MutableMapping):
    """Read-write `dict`-like view of {attr}`Library.strings`.

    Backed by `library._library.strings_dict`, whose keys are always
    in BibDesk's canonical lowercase form (parsing normalizes them,
    see `bibdeskparser.middleware.NormalizeMacroNamesMiddleware`).
    Lookups (reading, `in`, deleting) lowercase the requested name, so
    the whole view matches BibDesk's case-insensitive macro table.
    Reading strips the enclosing `{...}`/`"..."` delimiters; writing
    re-adds them (after stripping any the caller redundantly supplied)
    and normalizes the macro name (validating it and lowercasing it).
    Deleting a macro that is still referenced (as a bare field value)
    by any entry raises {exc}`ValueError` -- except for an override of
    a standard month macro (`STANDARD_MACROS`), whose references fall
    back to the built-in month name.
    """

    def __init__(self, owner):
        self._owner = owner

    @property
    def _strings_dict(self):
        return self._owner._library.strings_dict

    def __getitem__(self, name):
        # A non-str key falls through to a dict-like KeyError.
        if isinstance(name, str):
            name = name.lower()
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
            _place_string_block(self._owner._library)
        self._owner._modified = True
        _check_duplicate_macro_values(self._strings_dict)

    def __delitem__(self, name):
        # A non-str key falls through to a dict-like KeyError.
        if isinstance(name, str):
            name = name.lower()
        strings_dict = self._strings_dict
        if name not in strings_dict:
            raise KeyError(name)
        # Deleting an override of a standard month macro never leaves
        # a dangling reference: it falls back to the built-in value.
        if name not in STANDARD_MACROS:
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


class Library(MutableMapping):
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
      {class}`Entry`; see {attr}`entries`. {meth}`keys` returns the
      citation keys as a `tuple`, optionally filtered by entry type,
      by which fields are present or missing, and by static-group
      membership.
    - {attr}`path`: the `.bib` file the library was loaded from or last
      saved to (read-only; `None` for an unsaved from-scratch library).
    - {attr}`timestamp`: the save time from the header comment, updated
      by {meth}`save`.
    - {attr}`strings`: a read-write view of the `@string` macro
      definitions. {meth}`rename_string` renames a macro, rewriting
      every entry field that references it. The twelve BibTeX month
      macros (`jan` ... `dec`) are always defined as a built-in
      fallback (like in BibDesk), without appearing in the view.
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
    - {meth}`search`: full-text search over the entries, returning the
      matches best first.
    - {meth}`rekey`: rename an entry ({attr}`Entry.key` itself is
      read-only), either to an explicitly given key or to one generated
      from an auto-key format in BibDesk's
      [format-specifier language](format-specifiers).
      {meth}`eval_format_spec` evaluates such a format -- as a citation
      key or as an attachment file name -- without renaming or moving
      anything.
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
    - {meth}`import_bibtex`: import the entries of a BibTeX snippet,
      sanitized and normalized. {meth}`add` fetches bibliographic data
      for an arXiv identifier, DOI, or free-form query from the
      appropriate online source and imports it as a new entry.
      {meth}`add_abstract` fetches an entry's abstract from the best
      available source (including the entry's first attached PDF) and
      stores it in the `abstract` field, {meth}`add_preprint`
      records an entry's matching arXiv preprint (given explicitly,
      or found by searching arXiv) in the `eprint` field, and
      {meth}`add_doi` records an entry's DOI (given explicitly,
      recorded on arXiv for the entry's `eprint`, or found by
      searching Crossref) in the `doi` field. All three maintain the
      configured known-missing groups, recording which entries are
      verified to have no abstract, preprint, or DOI (see the
      `[known_missing]` table of the configuration).

    The process-global configuration (see the
    [configuration](configuration) reference page) is exposed as the
    `Library.config` class attribute -- equally readable from any
    instance, as `bib.config`. Its attributes can be assigned for an
    in-process override (which never writes back to the configuration
    file); the most important ones are:

    - `Library.config.verify_types` (default `True`): whether an
      unrecognized {attr}`Entry.entry_type` is rejected with a
      `ValueError`.
    - `Library.config.verify_fields` (default `True`): whether
      assigning a field inappropriate for an entry's type emits a
      `UserWarning`.
    - `Library.config.config_file` (default `None`): an explicit
      `bibdeskparser.toml` path that takes precedence over the
      directory-based search.
    - `Library.config.auto_key.format_spec` (default `None`): the
      auto-key format for {meth}`rekey`/{meth}`eval_format_spec` -- a
      single format string in BibDesk's
      [format-specifier language](format-specifiers), or a per-type
      `dict` mapping entry-type names (with `""` as the fallback) to
      format strings. Assigning a spec validates every format string
      in it.

    Constructing a `Library` (re)discovers a `bibdeskparser.toml`
    (`config.config_file`, then the `.bib` file's own directory -- the
    current working directory for a from-scratch library -- then the
    XDG location, first found wins) and applies it, replacing any
    in-process overrides. With no config file present, the defaults
    above apply.

    Loading an existing library (here, the example database shipped
    in the `bibdeskparser` repository as `tests/Refs/refs.bib`):

    ```python
    >>> from bibdeskparser import Entry, Library
    >>> bib = Library("tests/Refs/refs.bib")
    >>> len(bib)
    61
    >>> bib["GoerzQ2022"]["title"]
    'Quantum Optimal Control via Semi-Automatic Differentiation'
    >>> [e.key for e in bib.search("tractor atom interferometry")]
    ['RaithelQST2022']

    ```

    A library can also be built from scratch, in memory:

    ```python
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

    config = active
    """The process-global configuration (documented in the class
    docstring above): the single `bibdeskparser.config.active` object,
    which `load()`/`reset()` mutate in place."""

    def __init__(self, path=None, creator=None):
        self._path = path
        self._creator = creator

        # (Re)discover and apply the configuration for this library's
        # directory (the `.bib` file's folder, or the cwd for a
        # from-scratch library): config.config_file, then that
        # directory, then the XDG location; first found wins.
        bib_dir = Path(path).resolve().parent if path is not None else None
        active.load(bib_dir=bib_dir)

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

        Macro names are case-insensitive, matching BibDesk's macro
        table: they are stored (and iterated) in their canonical
        lowercase form -- names from the parsed `.bib` file are
        lowercased on load -- and every lookup (reading, `in`,
        deleting) lowercases the requested name, so `strings["PRA"]`
        and `strings["pra"]` are the same macro. Assigning a name
        additionally validates that it is a valid BibDesk macro name
        (a subset of ASCII, no leading digit) and raises `ValueError`
        if it is not.
        Deleting a name that is still referenced by any entry's field
        raises `ValueError` instead of leaving a dangling reference;
        use {meth}`rename_string` to rename a macro everywhere it is
        used in one step.

        The view contains only the macros defined in the `.bib` file
        itself. Like BibDesk, the twelve BibTeX month macros
        (`jan` ... `dec`, expanding to `"January"` ... `"December"`)
        are additionally always defined as a built-in fallback:
        a `month = jan` field resolves (in {meth}`render`,
        {meth}`search`, and format specifiers) without a `@string`
        definition, and does not count as an undefined macro when
        saving. A `@string` definition of the same name overrides the
        built-in value, and (unlike other in-use macros) can be
        deleted even while referenced, since the reference then falls
        back to the built-in month name.
        """
        return self._strings_view

    def _all_strings(self):
        """{attr}`strings` as a plain `dict`, with the standard month
        macros merged in as the lowest-priority fallback -- the mapping
        to resolve a bare macro reference against (BibDesk's
        `allMacroDefinitions`)."""
        return {**STANDARD_MACROS, **self.strings}

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
        as modified). Both names are treated case-insensitively,
        matching BibDesk's macro table: `old_name` is looked up by its
        lowercase form, and `new_name` is normalized to lowercase. A
        rename onto the same macro (`new_name` differing from
        `old_name` at most in case) is a no-op.

        Raises {exc}`KeyError` if `old_name` is not a defined macro,
        and {exc}`ValueError` if `new_name` is not a valid macro name
        or already names a different macro.
        """
        old_name = old_name.lower()
        strings_dict = self._library.strings_dict
        if old_name not in strings_dict:
            raise KeyError(old_name)
        new_name = normalize_macro_name(new_name)
        if new_name == old_name:
            return
        if new_name in strings_dict:
            raise ValueError(f"macro {new_name!r} already exists")
        old_string = strings_dict[old_name]
        new_string = String(key=new_name, value=old_string.value)
        self._library.replace(
            old_string, new_string, fail_on_duplicate_key=True
        )
        for entry in self._entries.values():
            for field, value in _bare_macro_fields(entry):
                if value.lower() == old_name:
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

        BibDesk's *smart* groups (saved searches) are not included:
        they are queries, not lists of citation keys, and are
        preserved in the file verbatim without being interpreted
        (as are BibDesk's URL and script groups).
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

    # -- known-missing groups -------------------------------------------- #

    def _known_missing_group(self, field):
        """The name of the known-missing group configured for
        `field` in `config.known_missing`, or `None`."""
        return active.known_missing.get(field)

    def _is_known_missing(self, field, key):
        """Whether entry `key` is a member of the known-missing group
        configured for `field` (`False` when no group is configured,
        or no group of that name exists)."""
        group = self._known_missing_group(field)
        if group is None:
            return False
        return key in self._group_data.get(group, ())

    def _mark_known_missing(self, field, key):
        """Add entry `key` to the known-missing group configured for
        `field`, creating the group if needed. Returns whether the
        membership actually changed (`False` when no group is
        configured, or the key already was a member)."""
        group = self._known_missing_group(field)
        if group is None or key in self._group_data.get(group, ()):
            return False
        if group not in self._group_data:
            self._set_group(group, ())
        self.add_to_group(group, key)
        return True

    def _clear_known_missing(self, field, key):
        """Remove entry `key` from the known-missing group configured
        for `field`; a no-op when no group is configured, no group of
        that name exists, or the key is not a member."""
        group = self._known_missing_group(field)
        if group is not None and group in self._group_data:
            self.remove_from_group(group, key)

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

    def keys(
        self,
        *,
        types=None,
        has=None,
        missing=None,
        group=None,
        not_group=None,
        with_files=None,
    ):
        """Citation keys of the entries, as a `tuple`, optionally
        filtered.

        ```python
        keys = library.keys(
            types=None,
            has=None,
            missing=None,
            group=None,
            not_group=None,
            with_files=None,
        )
        ```

        Without arguments, all citation keys, in library order. The
        keyword arguments narrow the result; each accepts a single
        name or an iterable of names. Type and field names are
        matched case-insensitively, group names exactly:

        * `types`: keep only entries whose {attr}`Entry.entry_type`
          is one of the given types.
        * `has`: keep only entries where every given field is defined
          with a non-empty value.
        * `missing`: keep only entries where none of the given fields
          has a non-empty value.
        * `group`: keep only entries that are members of every given
          static group (see {attr}`groups`).
        * `not_group`: keep only entries that are members of none of
          the given static groups.
        * `with_files`: a tri-state filter on file attachments (the
          `bdsk-file-N` fields, see {attr}`Entry.files`). `None` (the
          default) does not filter; `True` keeps only entries with at
          least one attachment; `False` keeps only entries with none.

        For any field, exactly one of `has` and `missing` holds. A
        field that is defined with an empty (or whitespace-only)
        value counts as missing, since BibDesk deletes empty fields
        when it saves a `.bib` file (see
        [Empty fields](bibdesk-empty-fields)).

        Raises {exc}`KeyError` for a group name (in `group` or
        `not_group`) that does not exist in the library.

        ```python
        >>> from bibdeskparser import Entry, Library
        >>> bib = Library()
        >>> bib["Key2026"] = Entry(
        ...     "article", "Key2026", fields={"title": "A Title"}
        ... )
        >>> bib.keys()
        ('Key2026',)
        >>> bib.keys(types="book")
        ()
        >>> bib.keys(has="title", missing="doi")
        ('Key2026',)
        >>> bib.keys(with_files=True)   # no attachment yet
        ()
        >>> bib.keys(with_files=False)
        ('Key2026',)
        >>> bib.groups["My Papers"] = ("Key2026",)
        >>> bib.keys(group="My Papers")
        ('Key2026',)
        >>> bib.keys(not_group="My Papers")
        ()

        ```
        """
        types = {t.lower() for t in _names(types)}
        required = [(True, name) for name in _names(has)]
        required += [(False, name) for name in _names(missing)]

        def _members(name):
            if name not in self._group_data:
                raise KeyError(name)
            return set(self._group_data[name])

        include = [_members(name) for name in _names(group)]
        exclude = [_members(name) for name in _names(not_group)]
        result = []
        for key, entry in self._entries.items():
            if types and entry.entry_type.lower() not in types:
                continue
            if with_files is not None and bool(entry.files) != with_files:
                continue
            if not all(key in members for members in include):
                continue
            if any(key in members for members in exclude):
                continue
            if all(
                _has_field(entry, name) is state for state, name in required
            ):
                result.append(key)
        return tuple(result)

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
            _hoist_last_block_above_groups(self._library)
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

    def rekey(self, old_key, new_key=None, *, format_spec=None):
        """Rename the entry at `old_key`; returns the new key.

        `Entry.key` is read-only, so this is the only way to rename
        an entry that is already in the library. The entry's
        static-group memberships follow the rename: `new_key` replaces
        `old_key` in place (keeping its position) in every group that
        contained it.

        With `new_key` omitted (or `None`), a key is **generated** from
        an auto-key format in BibDesk's
        [format-specifier language](format-specifiers): the
        `format_spec` argument if given, or else the configured
        `config.auto_key.format_spec` (from the `[auto_key]` table of
        `bibdeskparser.toml`; see the
        [configuration](configuration)). `format_spec` is either a
        single format string or a per-type `dict` mapping entry-type
        names (with `""` as the fallback) to format strings; the entry's
        own type selects the format. A key that already matches the
        format is kept as is, so regenerating is idempotent; a
        `%u`/`%U`/`%n` specifier in the format resolves collisions
        with the other entries in the library.

        Raises `KeyError` if `old_key` is not present, and
        `ValueError` if `new_key` is already used by a different
        entry, if both `new_key` and `format_spec` are given, if no
        auto-key format is available for the entry's type or the entry
        lacks a field the format requires, or if the generated key
        would equal the entry's own `crossref` value.

        To preview the key a format would generate, without renaming
        anything, use {meth}`eval_format_spec`.
        """
        if old_key not in self._entries:
            raise KeyError(old_key)
        if new_key is None:
            new_key = self._generate_key(old_key, format_spec)
        elif format_spec is not None:
            raise ValueError("give either new_key or format_spec, not both")
        if new_key == old_key:
            return new_key
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
        return new_key

    def eval_format_spec(self, key, format_spec=None, *, filename=None):
        """Evaluate a format specification for the entry at `key`;
        returns the resulting citation key or file name without
        renaming or moving anything.

        `format_spec` is a format in BibDesk's
        [format-specifier language](format-specifiers), or a per-type
        `dict` mapping entry-type names (with `""` as the fallback) to
        format strings; the entry's own type selects the format.

        Without `filename` (i.e. `filename=None`), the format is
        evaluated as a **citation key**: exactly the key that
        {meth}`rekey` without a `new_key` would generate. A
        `format_spec` of `None` falls back to the configured
        `config.auto_key.format_spec` (from the `[auto_key]` table of
        `bibdeskparser.toml`; see the [configuration](configuration)).

        With any `filename` (including the empty string `""`), the
        format is evaluated as a **file name**, in the
        [file-name dialect](specifiers-files): `format_spec` falls
        back to `config.auto_file.format_spec` (the `[auto_file]`
        table). `filename` only supplies the original-name specifiers
        `%l`/`%L`/`%e`/`%E` (e.g. its extension); it need not exist or
        be one of the entry's attachments, and `""` is fine when the
        format uses none of those specifiers. If `filename` *is* an
        attachment's current library-relative path (as listed by
        {attr}`Entry.files`) and already matches the format, it
        evaluates to itself (the same idempotency as the key context),
        so the attachments that do not follow a given format are
        exactly those where the result differs from the current path.

        Raises `KeyError` if `key` is not present, and `ValueError`
        if no format is available for the entry's type, if the entry
        lacks a field the format requires, or (in the key context) if
        the resulting key would equal the entry's own `crossref` value.
        """
        if key not in self._entries:
            raise KeyError(key)
        if filename is None:
            return self._generate_key(key, format_spec)
        entry, fmt = self._compile_file_format(key, format_spec)
        # Evaluate in the same location-relative frame that filing uses:
        # `filename` is library-relative, but the format renders a name
        # relative to `auto_file.location`, and the result is stored
        # library-relative again (see `_generate_filename`). A library
        # with no path yet cannot resolve a location (and cannot be
        # filed at all), so it falls back to a plain, location-less
        # render (equivalent to `location="."`).
        base_dir = None if self._path is None else self._files_base_dir()
        loc_dir = None
        if base_dir is not None:
            loc_dir = self._auto_file_location_dir(active.auto_file.location)
        current_name = None
        render_filename = filename
        if loc_dir is not None and filename:
            abs_name = os.path.normpath(base_dir / filename)
            render_filename = str(abs_name)
            rel = os.path.relpath(abs_name, loc_dir)
            if not rel.startswith(os.pardir):
                current_name = Path(rel).as_posix()
        else:
            current_name = filename or None
        new_name = specifiers.render_format(
            fmt,
            entry,
            strings=self._all_strings(),
            initials=active.initials,
            lowercase=active.auto_file.lowercase,
            clean=active.auto_file.clean,
            current_key=key,
            document_name=(
                Path(self._path).stem if self._path is not None else None
            ),
            filename=render_filename,
            current_name=current_name,
        )
        if loc_dir is None:
            return new_name
        return Path(os.path.relpath(loc_dir / new_name, base_dir)).as_posix()

    @staticmethod
    def _resolve_format_spec(format_spec, entry_type, *, context="key"):
        """Resolve `format_spec` (or, if it is `None`, the configured
        `config.auto_key.format_spec` / `config.auto_file.format_spec`,
        depending on `context`) to a single format string for an entry
        of `entry_type`, picking the per-type entry (or the `""`
        fallback) from a `dict` spec."""
        if context == "file":
            what, kind, table = "file name", "auto-file", "[auto_file]"
            configured = active.auto_file.format_spec
        else:
            what, kind, table = "citation key", "auto-key", "[auto_key]"
            configured = active.auto_key.format_spec
        if format_spec is None:
            format_spec = configured
        if format_spec is None:
            raise ValueError(
                f"cannot generate a {what}: no {kind} format is "
                f"configured (set 'format_spec' in the {table} table "
                "of bibdeskparser.toml, or pass a format explicitly)"
            )
        if isinstance(format_spec, str):
            return format_spec
        if entry_type in format_spec:
            return format_spec[entry_type]
        if "" in format_spec:
            return format_spec[""]
        raise ValueError(
            f"cannot generate a {what}: the {kind} format_spec "
            f"has no entry for type {entry_type!r} and no '' fallback"
        )

    def _generate_key(self, key, format_spec=None):
        """Generate a citation key for the entry at `key`, from
        `format_spec` or (if that is `None`) the configured
        `config.auto_key.format_spec`; backs {meth}`rekey` and
        {meth}`eval_format_spec`."""
        entry = self._entries[key]
        format_string = self._resolve_format_spec(
            format_spec, entry.entry_type
        )
        fmt = specifiers.compile_format(format_string)
        missing = specifiers.missing_required_fields(fmt, entry)
        if missing:
            raise ValueError(
                f"cannot generate a citation key for {key!r}: the "
                f"format {format_string!r} requires the missing "
                f"field(s) {', '.join(sorted(missing))}"
            )
        new_key = specifiers.render_format(
            fmt,
            entry,
            strings=self._all_strings(),
            initials=active.initials,
            lowercase=active.auto_key.lowercase,
            clean=active.auto_key.clean,
            current_key=key,
            is_free=lambda k: k == key or k not in self._entries,
            document_name=(
                Path(self._path).stem if self._path is not None else None
            ),
        )
        # a key must never equal the entry's own crossref parent
        # (BibDesk skips generation for such entries)
        if new_key == str(entry.get("crossref", "") or ""):
            raise ValueError(
                f"the generated key {new_key!r} for {key!r} would "
                "equal the entry's own crossref"
            )
        return new_key

    def _compile_file_format(self, key, format_spec):
        """Resolve and compile a file-name `format_spec` (or, if it is
        `None`, the configured `config.auto_file.format_spec`) for entry
        `key`, checking that the entry has every field the format
        requires. Returns the `(entry, fmt)` pair; backs
        {meth}`_generate_filename` and {meth}`eval_format_spec`."""
        entry = self._entries[key]
        format_string = self._resolve_format_spec(
            format_spec, entry.entry_type, context="file"
        )
        fmt = specifiers.compile_format(format_string, context="file")
        missing = specifiers.missing_required_fields(fmt, entry)
        if missing:
            raise ValueError(
                f"cannot generate a file name for {key!r}: the "
                f"format {format_string!r} requires the missing "
                f"field(s) {', '.join(sorted(missing))}"
            )
        return entry, fmt

    def _auto_file_location_dir(self, location):
        """Resolve an auto-file `location` (relative to the library
        directory, or absolute) to an absolute, resolved `Path`."""
        loc_dir = Path(os.path.expandvars(str(location))).expanduser()
        if not loc_dir.is_absolute():
            loc_dir = self._files_base_dir() / loc_dir
        return loc_dir.resolve()

    def _generate_filename(self, key, old_path, format_spec, location):
        """Generate the auto-file target for entry `key`'s attachment
        at `old_path` (an absolute, resolved `Path`), from
        `format_spec` or (if that is `None`) the configured
        `config.auto_file.format_spec`, under the directory `location`
        (relative to the library directory, or absolute). Returns the
        absolute target `Path`; backs the auto-file modes of
        {meth}`rename_file` and {meth}`add_file`."""
        if not str(location):
            raise ValueError(
                "cannot generate a file name: auto_file_location must "
                "not be empty"
            )
        loc_dir = self._auto_file_location_dir(location)
        entry, fmt = self._compile_file_format(key, format_spec)
        try:
            # feeds the idempotency check: a file already under
            # `location` with a name matching the format keeps it
            current_name = old_path.relative_to(loc_dir).as_posix()
        except ValueError:
            current_name = None

        def is_free(name):
            # a candidate is taken iff another file exists there (the
            # file being filed may itself sit at the target already)
            target = loc_dir / name
            if target.exists():
                return old_path.exists() and os.path.samefile(target, old_path)
            return True

        new_name = specifiers.render_format(
            fmt,
            entry,
            strings=self._all_strings(),
            initials=active.initials,
            lowercase=active.auto_file.lowercase,
            clean=active.auto_file.clean,
            current_key=key,
            is_free=is_free,
            document_name=(
                Path(self._path).stem if self._path is not None else None
            ),
            filename=str(old_path),
            current_name=current_name,
        )
        return loc_dir / new_name

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

    def add_file(
        self,
        key,
        filename,
        *,
        check_that_file_exists=True,
        format_spec=None,
        auto_file_location=None,
    ):
        """Attach the file `filename` to entry `key`, appending a
        `bdsk-file-N` field (see {attr}`Entry.files`); returns the
        stored library-relative path.

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
          Incompatible with auto-filing (`ValueError`), which must
          move the file.
        * `format_spec`, `auto_file_location`: control **auto-filing**
          (see below); they default to the `[auto_file]` configuration
          (`config.auto_file.format_spec` /
          `config.auto_file.location`; see the
          [configuration](configuration)).

        When auto-filing is in effect, the file is not attached under
        its original name: it is *moved* into the `auto_file_location`
        directory (relative to the library's `.bib` directory, or
        absolute) and renamed according to `format_spec`, a file-name
        format in BibDesk's
        [format-specifier language](format-specifiers). Auto-filing
        is in effect if `auto_file_location` is given non-empty, if
        `format_spec` is given, or if the configuration sets
        `file_automatically = true` in its `[auto_file]` table; pass
        `auto_file_location=""` to force a plain attach regardless of
        the configuration. The move itself (and the update of every
        entry linking the file) is exactly {meth}`rename_file`.

        The stored path is always relative to the library directory.
        For a file that exists, a macOS bookmark is generated
        automatically (requires the `bibdeskparser[macos]` extra) so
        BibDesk can still find the file if it is later moved or
        renamed; where a bookmark can't be created, the file is
        attached by path only, with a `UserWarning`.

        Raises `ValueError` if the file is already attached to the
        entry, if auto-filing cannot generate a name (no format
        configured, or a required field is missing), or if this
        library has no file path yet (a from-scratch library must be
        saved first, so that relative paths are well-defined).
        """
        entry = self._entries[key]
        base_dir = self._files_base_dir()
        if auto_file_location is None:
            if format_spec is not None or active.auto_file.file_automatically:
                auto_file_location = active.auto_file.location
            else:
                auto_file_location = ""
        auto_file = str(auto_file_location) != ""
        if not auto_file and format_spec is not None:
            raise ValueError(
                "format_spec has no effect when auto-filing is "
                "disabled (auto_file_location='')"
            )
        if auto_file and not check_that_file_exists:
            raise ValueError(
                "cannot auto-file with check_that_file_exists=False: "
                "moving a file requires it to exist"
            )
        path = self._resolve_file_arg(
            filename, must_exist=check_that_file_exists
        )
        new_path = None
        if auto_file:
            # generate (and thereby validate) the target *before*
            # attaching, so a failure leaves the entry unchanged
            new_path = self._generate_filename(
                key, path.resolve(), format_spec, auto_file_location
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
        if new_path is not None:
            return self.rename_file(
                key, bdsk_file.relative_path, os.fspath(new_path)
            )
        return bdsk_file.relative_path

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

    def rename_file(
        self,
        key,
        old_filename,
        new_filename=None,
        *,
        format_spec=None,
        auto_file_location=None,
    ):
        """Rename (or move) entry `key`'s attached file
        `old_filename` on the filesystem, updating *every* entry that
        links the file (each with a fresh macOS bookmark, where
        available); returns the new library-relative path.

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
          already exists. Missing directories in the target path are
          created.

        With `new_filename` omitted (or `None`), the target is
        **generated**: the file is moved into the
        `auto_file_location` directory (relative to the library's
        `.bib` directory, or absolute) and renamed according to
        `format_spec`, a file-name format in BibDesk's
        [format-specifier language](format-specifiers) (a single
        format string, or a per-type `dict` like in {meth}`rekey`).
        Both default to the `[auto_file]` configuration
        (`config.auto_file.format_spec` / `config.auto_file.location`;
        see the [configuration](configuration)). A file whose name
        already matches the format is left in place, so re-filing is
        idempotent; the format's required `%u`/`%U`/`%n` specifier
        resolves collisions with existing files at the target
        location. To preview the generated path without moving
        anything, use {meth}`eval_format_spec` with a `filename`.

        Renaming a file to itself (`new_filename` naming the same
        file, or a generated name that already matches) is a no-op.

        Raises `ValueError` if `new_filename` is given together with
        `format_spec` or `auto_file_location`, if no auto-file format
        is available for the entry's type, if the entry lacks a field
        the format requires, or if this library has no file path yet
        (see {meth}`add_file`).
        """
        entry = self._entries[key]
        base_dir = self._files_base_dir()
        old_rel = self._match_attachment(entry, old_filename)
        old_path = (base_dir / old_rel).resolve()
        if not old_path.exists():
            raise FileNotFoundError(f"No such file: {old_path}")
        if new_filename is None:
            if auto_file_location is None:
                auto_file_location = active.auto_file.location
            new_path = self._generate_filename(
                key, old_path, format_spec, auto_file_location
            )
        else:
            if format_spec is not None or auto_file_location is not None:
                raise ValueError(
                    "give either new_filename or format_spec/"
                    "auto_file_location, not both"
                )
            new_path = Path(new_filename)
            if not new_path.is_absolute():
                if new_path.parent == Path("."):
                    new_path = old_path.parent / new_path
                else:
                    new_path = base_dir / new_path
        if new_path.exists():
            if os.path.samefile(new_path, old_path):
                return old_rel  # no-op: already the same file
            raise FileExistsError(f"File already exists: {new_path}")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        # `shutil.move` (unlike `os.rename`) also works across
        # filesystems, e.g. for an absolute auto-file location on
        # another volume
        shutil.move(os.fspath(old_path), os.fspath(new_path))
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
        return new_file.relative_path

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
                    and value not in STANDARD_MACROS
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
        * `force`: bypass the {exc}`StaleFileError` and
          {exc}`FileExistsError` checks (see below).

        If the library was not modified since it was loaded (no entry
        was modified, {attr}`groups` was not mutated, and no
        entries/strings were added or removed),
        the file is written byte-identical to how it was parsed, and
        the header timestamp is *not* touched. The one exception to
        byte-identity: a hand-edited mixed-case macro name (a
        `@string{JAN = ...}` definition or a bare `month = JAN`
        reference) is normalized on load and written back in its
        canonical lowercase form. Otherwise (including the first save
        of a from-scratch library, even an empty one): the header
        timestamp is updated (synthesizing a header if the library did
        not already have one), the static-groups `@comment` block is
        re-rendered from the current {attr}`groups` (synthesizing the
        block if the library did not have one but now has groups),
        dirty/new entries have their fields reordered into BibDesk's
        canonical order, and {attr}`timestamp` is updated.

        Before writing, raises {exc}`ValueError` if any entry
        references an undefined `@string` macro (the standard month
        macros `jan` ... `dec` are always defined, see
        {attr}`strings`), and warns (without
        raising) about any linked file
        ({attr}`Entry.files`) that does not exist
        relative to `path`'s directory (such files may legitimately
        live only on another machine).

        Raises {exc}`StaleFileError` if `path` already exists and its
        header timestamp is strictly newer than {attr}`timestamp`
        (i.e., it was saved -- by BibDesk or otherwise -- after this
        library was loaded or last saved), unless `force=True`.

        For a from-scratch library that has never been saved, there is
        no baseline timestamp for the {exc}`StaleFileError` check;
        instead, raises {exc}`FileExistsError` if `path` already
        exists, unless `force=True`.
        """
        from_scratch = self._path is None
        path = path if path is not None else self._path
        if path is None:
            raise ValueError(
                "no path given and this library was not loaded from a file"
            )
        path = Path(path)

        if path.exists():
            if from_scratch:
                if not force:
                    raise FileExistsError(
                        f"{path} already exists; not overwriting it "
                        "with a from-scratch library. Pass force=True "
                        "to overwrite anyway."
                    )
            else:
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

        pristine = (
            not from_scratch
            and not self._modified
            and not any(
                entry._dirty  # pylint: disable=protected-access
                for entry in self._entries.values()
            )
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
            # BibDesk writes the static-groups block as the first of
            # its group `@comment` blocks (before smart/URL/script
            # groups).
            _hoist_last_block_above_groups(self._library)
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
            strings=self._all_strings(),
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

        A *preprint-only* entry -- a `misc` or `unpublished`
        entry with an `eprint` from a recognized preprint archive,
        or any entry whose `journal` is a preprint pseudo-journal
        like `arXiv:2205.15044` -- renders its preprint reference
        (with the category tag from `primaryclass`, e.g.
        `arXiv:2205.15044 [quant-ph]`) in the journal position,
        linked to the DOI, the entry's first URL, or the archive's
        page for the identifier. Any *other* entry's `eprint` is
        rendered as a separate link into its preprint archive after
        the journal reference (the "published, with preprint"
        form).
        """
        strings = self._all_strings()
        entries = [_expand_macros(self[key], strings) for key in keys]
        return render_entries(entries, format=format, style=style)

    def export(
        self,
        *keys,
        unicode=True,
        expand_strings=False,
        fields="full",
        outfile=None,
        preprint=None,
    ):
        """Export the entries with the given citation `keys` (at
        least one required) as bibtex text.

        Three independent parameters control the output:

        * `unicode`: with `True` (default), field values are the
          Unicode text also returned by the `Entry` dict interface;
          with `False`, they are TeX-encoded, exactly as they would
          be written to the `.bib` file on disk.
        * `expand_strings`: with `False` (default), a field value
          referencing an `@string` macro stays a bare reference, and
          the `@string` definitions needed by the selected entries
          are included, so the export is self-contained; with `True`,
          each reference is replaced by the macro's value (the
          standard BibTeX month macros `jan` ... `dec` also resolve),
          and no `@string` definitions are emitted. An undefined
          macro stays a bare reference, with a `UserWarning`.
        * `fields`: `"full"` (default: every field except the
          `date-added`/`date-modified` bookkeeping fields, with
          file attachments and URLs as plain paths/URLs),
          `"minimal"` (only the fields needed to typeset a
          bibliography), or a list of field names (in the given
          order; names not defined on an entry are omitted).

        A *preprint-only* entry -- a `misc` or `unpublished`
        entry with an `eprint` from a recognized preprint archive,
        or any entry whose `journal` is a preprint pseudo-journal
        like `arXiv:2205.15044` -- is exported in the form selected
        by
        `preprint`, independent of its stored form:

        * `"unpublished"` (the default, via the `preprint_export`
          [configuration](configuration) setting): an `@unpublished`
          entry with the structured `eprint`/`archiveprefix` fields
          (derived from the pseudo-journal if not stored) -- for
          BibTeX styles that render the `eprint` field (REVTeX,
          `elsarticle`, biblatex); under REVTeX, the eprint renders
          in the journal position. A minimal export guarantees the
          type's required `note` field (the stored `note`, or the
          text "preprint").
        * `"misc"`: the same structured form, as a `@misc` entry
          (no required fields, no `note` handling).
        * `"article"`: an `@article` whose `journal` is the
          pseudo-journal and whose `url` is the DOI-resolver
          address, without the `eprint`/`doi` fields -- for classic
          styles (`plain`, `unsrt`, `IEEEtran`, ...) that would
          silently drop an `eprint`.
        * `"stored"`: no transformation.

        For a non-arXiv archive with a `<base>/{id}` URL template
        (HAL, bioRxiv, medRxiv), the structured forms also emit an
        `archive` field holding the link base that REVTeX's styles
        use for the rendered eprint; full and minimal exports of
        *published* entries with such an `eprint` gain the same
        field.

        A minimal export of a preprint-only entry reduces to the
        essential fields of the respective form; an explicit list of
        field names is always exported as stored, and the stored
        entry is never modified. See the
        [preprints](preprints-convention) documentation for how
        each form renders.

        The output layout is always the same (4-space indent,
        capitalized field names, a comma after every field); it is
        *not* the byte-exact layout of the `.bib` file on disk, and
        even with `unicode=False` the export is not a byte-faithful
        slice of the file (`bdsk-file-N` values are plain paths, not
        the stored binary plist data).

        With `outfile`, the text is written (UTF-8) to that path or
        open file object instead of being returned.
        """
        return export_entries(
            [self[key] for key in keys],
            strings=dict(self.strings),
            unicode=unicode,
            expand_strings=expand_strings,
            fields=fields,
            outfile=outfile,
            preprint=preprint,
        )

    def edit(self, *keys, editor=None):
        """Edit the entries with the given citation `keys` (at least
        one required) together, in `editor` (or `$EDITOR`), merging
        changes back into them (and into `.strings`) in place.

        `editor` may be a shell command string (e.g. `"code
        --wait"`), or a callable taking the temporary file's
        {class}`pathlib.Path` as its only argument and overwriting
        that file in place, like a text editor would -- for
        non-interactive use (scripts, tests). With a callable
        `editor`, a validation failure raises {exc}`ValueError`
        (listing the problems, and leaving the library unchanged)
        instead of interactively prompting to reopen the editor.
        """
        editing.edit_entries(
            [self[key] for key in keys],
            library=self,
            editor=editor,
        )

    def edit_strings(self, editor=None):
        """Edit `.strings` in `editor` (or `$EDITOR`), merging changes
        back in place.

        `editor` may be a shell command string or a callable, as in
        {meth}`edit`. With a callable `editor`, a validation failure
        raises {exc}`ValueError` instead of interactively prompting;
        note that deleting a macro that is still referenced by an
        entry is only detected while merging, so other changes from
        the same edit may already have been applied to `.strings`
        when the exception is raised.
        """
        editing.edit_strings(self, editor=editor)

    def import_bibtex(
        self,
        text,
        *,
        keep_keys=False,
        fix_uppercase=False,
        keep_journals=False,
    ):
        """Import the entries of the BibTeX snippet `text`, sanitized
        and normalized, into the library.

        Every entry of `text` (which may also contain `@string`
        definitions and comments, e.g. a complete `.bib` file or the
        output of {meth}`export`) is cleaned up as follows:

        * The `journal` is replaced by an `@string` macro reference:
          a macro already in {attr}`strings` (matched by value), a
          macro configured in the `[journal_macros]` table of the
          [configuration](configuration) (its `@string` definition is
          added to the library as needed), or -- with a `UserWarning`
          -- a newly created macro named by the journal's lowercased
          initials (honoring `[initials.journal]` exceptions). A
          pseudo-journal whose archive is *not* recognized is
          rejected, since it must not be turned into a macro.
        * A *preprint-only* entry -- one whose `journal` is a
          preprint pseudo-journal like `arXiv:2205.15044` (any
          archive from the `preprint_archives`
          [configuration](configuration): arXiv, bioRxiv, medRxiv,
          ChemRxiv, HAL, and SSRN by default), or a `misc` entry
          with an `eprint` from a recognized archive (e.g. arXiv's
          own BibTeX export) -- is normalized to its canonical
          stored form: an `@unpublished` entry with the
          pseudo-journal in the archive's canonical spelling
          (`hal:` becomes `HAL:`; synthesized from the `eprint` if
          absent), the `eprint` and `archiveprefix` fields derived
          from the pseudo-journal if missing, and the `doi`
          extracted from a `https://doi.org/...` value in the `url`
          field (dropping that `url`) or, for arXiv, derived as
          `10.48550/arXiv.<id>`. A `url` that merely restates the
          archive's page for the identifier is dropped when the
          entry carries a `doi`. A `note` is *never* synthesized: a
          missing publication-status note is a signal to fill it in
          by hand. See the [preprints](preprints-convention)
          documentation.
        * `keep_journals=True` skips both of the above: every
          `journal` is preserved as-is, and the entry keeps its
          incoming type (preprint-only entries are still recognized
          for the `eprint`/`archiveprefix` derivation and the
          citation key).
        * Capitalized words inside the `title` (assumed to be proper
          nouns) are wrapped in braces to protect their
          capitalization, unless the title looks like it is already
          in (English) title case; any of the configured
          `protected_words` are brace-protected in every title.
        * A `doi` is normalized to its bare, lowercase form (no
          `https://doi.org/` or `doi:` prefix).
        * An `archive` field holding the link base derivable from
          the entry's `eprint`/`archiveprefix` is dropped (exports
          regenerate it), for preprint-only and published entries
          alike.
        * For an `@article`, a `pages` range collapses to its first
          page, the fields `month`, `day`, `publisher`, `address`,
          `numpages`, and `issn` are dropped, and a `url` is dropped
          when there is a `doi`. For other entry types, page ranges
          are kept, with the dash normalized to `--`.
        * Every entry gets a newly generated citation key (unless
          `keep_keys` is given): from the `[auto_key]` format of the
          [configuration](configuration) if one is set, else
          `%p1%c{journal}0%Y%u0` for an article (e.g.
          `GoerzPRA2014`), `%p1%c{booktitle}0%Y%u0` for
          inproceedings/incollection, and `%p1%Y%u0` for any other
          type. Preprint-only entries (a recognized pseudo-journal)
          always use `%p1%f{eprint}[.]` (e.g. `Goerz2205.15044`). An
          incoming key that already matches the format is kept.
        * TeX-encoded accents (`Schr{\\"o}dinger`) are decoded to
          Unicode, exactly as if the values had been read from a
          `.bib` file (saving re-encodes them).

        With `fix_uppercase=True`, all-uppercase `author`/`editor`
        names and `title` values (as found in some publisher data)
        are down-cased to name case/sentence case first; the result
        may need manual correction. `keep_keys=True` keeps the
        incoming citation keys instead of generating new ones.
        `keep_journals=True` preserves every incoming `journal` field
        as-is instead of converting it to an `@string` macro
        reference.

        An entry whose `doi` or `eprint` is already in the library is
        rejected. `keywords`, `bdsk-url-N`, and `date-added` fields
        are preserved; `bdsk-file-N` fields must hold plain file
        paths (as written by {meth}`export`) that exist relative to
        the library's `.bib` directory, and become regular file
        attachments. Inappropriate fields for an entry's type are
        kept, with a `UserWarning` (see the
        [configuration](configuration)).

        Returns the list of citation keys of the added entries, in
        snippet order. Raises {exc}`ValueError`, listing *all*
        problems, if anything about `text` is not acceptable -- the
        library is guaranteed unmodified in that case. Like any other
        modification, an import only becomes permanent with
        {meth}`save`.

        ```python
        >>> from bibdeskparser import Library
        >>> bib = Library()
        >>> bib.strings["pra"] = "Phys. Rev. A"
        >>> keys = bib.import_bibtex('''
        ... @article{PhysRevA.89.032334,
        ...     Author = {Goerz, Michael and Reich, Daniel M.},
        ...     Title = {Optimal control theory for a quantum gate},
        ...     Journal = {Phys. Rev. A},
        ...     Year = {2014},
        ...     Doi = {10.1103/PhysRevA.89.032334},
        ...     Pages = {032334},
        ...     Volume = {89},
        ... }''')
        >>> keys
        ['GoerzPRA2014']
        >>> bib["GoerzPRA2014"]["journal"]
        'pra'
        >>> bib["GoerzPRA2014"]["doi"]
        '10.1103/physreva.89.032334'

        ```
        """
        return import_entries(
            self,
            text,
            keep_keys=keep_keys,
            fix_uppercase=fix_uppercase,
            keep_journals=keep_journals,
        )

    def add(
        self,
        query,
        *,
        fix_uppercase=None,
        add_abstract=None,
        add_preprint=None,
    ):
        """Fetch bibliographic data for `query` from the appropriate
        online source and add it to the library as a new, sanitized
        entry (via {meth}`import_bibtex`, see there for the
        normalization applied and for `fix_uppercase`).

        `query` is one of:

        * an arXiv identifier (`2205.15044`, `quant-ph/0106057`), or
          any string containing `arXiv` followed by an identifier
          (e.g. an `https://arxiv.org/abs/...` URL) -- fetched from
          the [arXiv API](https://info.arxiv.org/help/api/), added as
          a preprint-only `@misc` entry with a literal `arXiv:...`
          pseudo-journal and the structured eprint fields;
        * a DOI (`10.1103/PhysRevA.89.032334`), or a URL containing
          one (e.g. `https://doi.org/...` or most publisher article
          pages) -- fetched from
          [Crossref](https://www.crossref.org);
        * any other free-form text (anything containing a space) --
          a Crossref bibliographic search, using the best match
          (typically: a paper's title, or a formatted citation).

        An arXiv identifier wins over a DOI when `query` contains
        both. Crossref works of a type with no BibTeX equivalent are
        retrieved as publisher BibTeX via DOI content negotiation and
        imported as-is (still sanitized).

        The keyword arguments default to the `[add]` table of the
        [configuration](configuration) (`config.add.fix_uppercase`,
        `config.add.add_abstract`, `config.add.add_preprint`; all
        `False` unless configured); passing an explicit boolean
        overrides the configured default.

        With `add_abstract=True`, the abstract that the source
        returns alongside the metadata (the publisher's Crossref
        deposit, or the arXiv summary) is included as the new entry's
        `abstract` field, cleaned to plain-unicode prose (math markup
        converted to unicode, copyright trailers stripped) and
        validated. Because it arrives with the metadata from the same
        source, identified by the same DOI or arXiv identifier, it is
        high-confidence by construction -- the `min_confidence`
        threshold of {meth}`add_abstract` does not apply here. An
        abstract that fails validation -- or a source that provides
        none -- is silently omitted, so the new entry remains matched
        by `keys --missing abstract` for a later {meth}`add_abstract`
        pass; `add` itself never records a verified absence in a
        known-missing group (only {meth}`add_abstract`, which
        consults more sources, completes that audit).

        With `add_preprint=True`, {meth}`add_preprint` is called for
        the new entry (with its configured defaults, see there),
        searching arXiv for a matching preprint and recording it in
        the entry's `eprint` field -- unless the entry already has an
        `eprint` (an entry fetched from an arXiv query always does).

        Returns the citation key of the added entry. Raises
        {exc}`ValueError` if the data cannot be fetched (network
        errors, no match for the query) or fails import validation
        (e.g. its `doi`/`eprint` is already in the library). Like any
        other modification, the new entry only becomes permanent with
        {meth}`save`.
        """
        # Imported lazily: the fetch module pulls in the network
        # dependencies (habanero/arxiv/httpx), which nothing else in
        # the package needs.
        from . import fetch  # pylint: disable=import-outside-toplevel

        if fix_uppercase is None:
            fix_uppercase = active.add.fix_uppercase
        if add_abstract is None:
            add_abstract = active.add.add_abstract
        if add_preprint is None:
            add_preprint = active.add.add_preprint
        key = self.import_bibtex(
            fetch.fetch_bibtex(query, include_abstract=add_abstract),
            fix_uppercase=fix_uppercase,
        )[0]
        if add_preprint and not str(self._entries[key].get("eprint") or ""):
            self.add_preprint(key)
        return key

    def add_abstract(self, key, *, min_confidence=None, overwrite=False):
        """Fetch the abstract of entry `key` from the best available
        source and store it in the entry's `abstract` field.

        Candidate abstracts are gathered from
        [Crossref](https://www.crossref.org) (the publisher's
        deposit, via the entry's `doi`), from the text of the entry's
        first attached PDF (extracted with the
        [poppler](https://poppler.freedesktop.org) `pdftotext`
        command-line tool, which must be on `PATH`; this source is
        skipped otherwise), from the [arXiv
        API](https://info.arxiv.org/help/api/) (via the entry's
        `eprint`, or an arXiv identifier contained in the citation
        key), and from [Semantic
        Scholar](https://www.semanticscholar.org) as a last resort.
        Every candidate is cleaned to plain-unicode prose (LaTeX/JATS
        math markup to unicode, ligature and hyphenation repair,
        publisher copyright trailers stripped) and validated with
        heuristic garble checks. The candidates are then combined
        into a single result with a *confidence* level:

        * `"high"`: an online abstract identified by the entry's
          `doi`/`eprint` (and agreeing with the PDF text, where both
          exist -- the identifier guarantees the paper, the agreement
          guards against a wrong or garbled deposit), or an
          unambiguous PDF extraction;
        * `"medium"`: a single unconfirmed source: only the PDF text,
          or an online lookup via an arXiv identifier merely guessed
          from the citation key;
        * `"low"`: the PDF text and an online source *disagree*. The
          PDF text is reported (it belongs to the given file), but
          one of the two sources probably grabbed the wrong text --
          review manually;
        * `"none"`: no valid abstract found anywhere.

        The fetched abstract is stored in the entry only if its
        confidence is at least `min_confidence` (`"high"`,
        `"medium"`, or `"low"`; defaulting to the `[add_abstract]`
        table of the [configuration](configuration),
        `config.add_abstract.min_confidence`, `"high"` unless
        configured). If the entry already has a non-empty abstract,
        nothing is fetched and the existing text is returned with
        source `"existing"`, unless `overwrite=True`.

        With a known-missing group configured for `abstract` (the
        `[known_missing]` table of the configuration), the group
        records which entries are verified to have no findable
        abstract, and the method operates in one of two modes. By
        default (routine fill-in), an entry that is a member is
        skipped without any search (source `"known-missing"`); a
        search that runs cleanly against every source and finds
        nothing adds the entry to the group (creating the group on
        first use); and storing an abstract removes the entry from
        the group again -- so repeated fill-in passes never re-query
        the sources for an entry already searched. With
        `overwrite=True`, the membership is ignored and the search
        re-runs: an explicit re-audit, for when an abstract may have
        become available since the last check; select exactly the
        group members with {meth}`keys` (`group="No Abstract"`). A
        re-audited entry that still yields nothing simply stays in
        the group. A search during which any source failed (source
        `"error"`: an unreachable API, or an attached PDF that could
        not be read) never marks the entry, so a re-run picks it up.
        Without the configuration, none of this bookkeeping happens.

        Returns a named tuple `(abstract, source, confidence, note,
        applied)`: the abstract text (`""` if none was found), the
        source it came from (`"crossref"`, `"pdf"`, `"arxiv"`,
        `"semanticscholar"`, `"none"`, `"error"`, `"existing"`, or
        `"known-missing"`), the confidence level, a short diagnostic
        trace of the source selection (`note`), and whether the
        library was modified -- the entry's `abstract` field, or its
        known-missing group membership (`applied`).

        Like any other modification, changes only become permanent
        with {meth}`save`. Raises {exc}`KeyError` if `key` is not in
        the library and {exc}`ValueError` for an invalid
        `min_confidence`. Network problems never raise: an
        unreachable source is skipped (see `note`). Requires network
        access for the online sources.
        """
        # Imported lazily: the abstracts module pulls in the network
        # dependencies and pylatexenc, needed nowhere else.
        from . import abstracts  # pylint: disable=import-outside-toplevel

        entry = self._entries[key]
        group = self._known_missing_group("abstract")
        if not overwrite and self._is_known_missing("abstract", key):
            return abstracts.AbstractResult(
                abstract="",
                source="known-missing",
                confidence="none",
                note=f"in group {group!r} (overwrite to re-search)",
                applied=False,
            )
        pdf_path = None
        if self._path is not None:
            base_dir = self._files_base_dir()
            for rel_path in entry.files:
                path = base_dir / rel_path
                if path.suffix.lower() == ".pdf" and path.is_file():
                    pdf_path = path
                    break
        result = entry._add_abstract(
            min_confidence=min_confidence,
            overwrite=overwrite,
            pdf_path=pdf_path,
        )
        if result.applied and result.abstract:
            self._clear_known_missing("abstract", key)
        elif result.source == "none" and self._mark_known_missing(
            "abstract", key
        ):
            result = result._replace(applied=True)
        return result

    def add_preprint(self, key, eprint=None, *, overwrite=False):
        """Record the arXiv preprint of entry `key` in its `eprint`
        field -- an explicitly given identifier, or one found by
        searching arXiv (the only supported preprint server).

        With `eprint` given (e.g. `"2205.15044"`,
        `"quant-ph/0106057"`, or `"arXiv:2205.15044"`), the
        identifier is validated and normalized (prefix and version
        suffix stripped) and stored without any network access -- the
        caller asserts the match, e.g. after manually reviewing a
        candidate the search rejected.

        With `eprint=None`, the [arXiv
        API](https://info.arxiv.org/help/api/) is searched for the
        entry, by title and first author, precise queries first. A
        result is accepted only when it confidently matches the
        entry: its arXiv DOI equals the entry's `doi`, its title is a
        near-exact match, or a good title match is corroborated by
        the first author's last name. A title-based match whose arXiv
        submission postdates the entry's `year` by more than a year
        is rejected unless its journal reference names that year
        (guarding against unrelated papers sharing a generic title);
        such a rejected candidate is reported in the result's `note`
        as `postdated-unverified(...)` and can, after review, be
        applied by passing its identifier as `eprint`.

        Whenever a non-empty `eprint` is stored, an
        `archiveprefix = arXiv` field is added alongside it (unless
        the entry already has an `archiveprefix`). A search match
        additionally stores the preprint's arXiv primary category
        (e.g. `quant-ph`) in the `primaryclass` field, replacing any
        existing value (which, with `overwrite=True`, described the
        replaced identifier); an explicitly given identifier stores
        no `primaryclass`, since without network access the category
        is unknown.

        If the entry already has a non-empty `eprint`, nothing is
        searched and the existing identifier is returned with match
        `"existing"`, unless `overwrite=True`.

        With a known-missing group configured for `eprint` (the
        `[known_missing]` table of the
        [configuration](configuration)), the group records which
        entries are verified to have no preprint, and the method
        operates in one of two modes. By default (routine fill-in),
        a member entry is skipped without any search (match
        `"known-missing"`); a search that runs cleanly and finds no
        preprint adds the entry to the group (creating the group on
        first use); and storing an identifier (a search match, or an
        explicitly given `eprint`) removes the entry from the group
        again -- so repeated fill-in passes never re-query arXiv for
        an entry already searched. With `overwrite=True`, the
        membership is ignored and the search re-runs: an explicit
        re-audit. Membership means "searched, nothing found at the
        time", not "does not exist" -- the earlier match may have
        failed, or a preprint may have been posted since the last
        check -- so re-audit periodically, selecting exactly the
        group members with {meth}`keys` (`group="No Eprint"`). A
        re-audited entry with another clean no-match simply stays in
        the group; a match stores the identifier and unmarks. A
        failed search (match `"error"`) never marks the entry, so a
        re-run picks it up. Without the configuration, none of this
        bookkeeping happens.

        Returns a named tuple `(eprint, match, ratio, note, applied,
        primaryclass)`: the stored (or existing) arXiv identifier
        (`""` if none), how it was matched (`"doi"`, `"title"`, or
        `"title+author"` for a search match, in decreasing order of
        strength; `"explicit"` for a given identifier; `"none"` for a
        clean no-match; `"error"` when the search could not run --
        network/API failure, or an entry without a title;
        `"existing"` or `"known-missing"` when the entry was
        skipped), the title-similarity ratio of the best search
        result (`None` when no search ran), a short diagnostic trace
        (`note`), whether the library was modified -- the entry's
        fields, or its known-missing group membership (`applied`),
        and the primary category of a search match (`""` otherwise).

        Like any other modification, changes only become permanent
        with {meth}`save`. Raises {exc}`KeyError` if `key` is not in
        the library and {exc}`ValueError` if an explicitly given
        `eprint` is not a valid arXiv identifier. Network problems
        never raise. The search respects the arXiv API's rate limit
        (one request every three seconds, shared across all searches
        in the process), so budget time accordingly for large batch
        runs.
        """
        # Imported lazily: the preprints module pulls in the network
        # dependencies, needed nowhere else.
        from . import preprints  # pylint: disable=import-outside-toplevel

        entry = self._entries[key]
        if eprint is None and not overwrite:
            group = self._known_missing_group("eprint")
            if self._is_known_missing("eprint", key):
                return preprints.PreprintResult(
                    eprint="",
                    match="known-missing",
                    ratio=None,
                    note=f"in group {group!r} (overwrite to re-search)",
                    applied=False,
                    primaryclass="",
                )
        result = entry._add_preprint(eprint, overwrite=overwrite)
        if result.applied and result.eprint:
            self._clear_known_missing("eprint", key)
        elif result.match == "none" and self._mark_known_missing(
            "eprint", key
        ):
            result = result._replace(applied=True)
        return result

    def add_doi(self, key, doi=None, *, overwrite=False):
        """Record the DOI of entry `key` in its `doi` field -- an
        explicitly given DOI, or one found online.

        With `doi` given (e.g. `"10.1103/PhysRevA.89.032334"`, a
        `doi:`-prefixed value, or a `https://doi.org/...` resolver
        address), the DOI is validated and normalized (prefix or
        resolver address stripped, lowercased -- DOIs are defined to
        be case-insensitive) and stored without any network access --
        the caller asserts the match, e.g. after manually reviewing a
        candidate the search rejected.

        With `doi=None`, the DOI is looked up online, from two
        sources. If the entry has an arXiv `eprint`, the [arXiv
        API](https://info.arxiv.org/help/api/) is consulted first:
        the DOI that arXiv records for the identifier names the
        published version of exactly this paper (an arXiv-issued
        `10.48550/...` DataCite DOI, which merely restates the arXiv
        identifier, does not count as a DOI on record). Otherwise --
        no `eprint`, or no DOI recorded on arXiv --
        [Crossref](https://www.crossref.org) is searched for the
        entry, by title and first author. A search result is accepted
        only when it confidently matches the entry: its title is a
        near-exact match, or a good title match is corroborated by
        the first author's last name. A title-based match whose
        publication year differs from the entry's `year` by more than
        one is rejected (guarding against unrelated papers sharing a
        generic title), reported in the result's `note` as
        `year-mismatch(...)`; and an amendment record -- an erratum,
        corrigendum, retraction, comment, or reply, whose title
        embeds the original title -- never matches an entry that is
        not itself such an amendment. A rejected candidate can, after
        review, be applied by passing its DOI as `doi`.

        A *preprint-only* entry (see the
        [preprints](preprints-convention) documentation) is skipped
        without any lookup (match `"preprint"`): the search
        would find the DOI of the *published version*, which does not
        belong on a preprint reference. To record it deliberately,
        pass it as `doi` -- but consider replacing the entry with the
        published version (via {meth}`add`) instead.

        If the entry already has a non-empty `doi`, nothing is
        searched and the existing DOI is returned with match
        `"existing"`, unless `overwrite=True`.

        With a known-missing group configured for `doi` (the
        `[known_missing]` table of the
        [configuration](configuration)), the group records which
        entries are verified to have no DOI, and the method operates
        in one of two modes. By default (routine fill-in), a member
        entry is skipped without any lookup (match
        `"known-missing"`); a lookup that runs cleanly and finds no
        DOI adds the entry to the group (creating the group on first
        use); and storing a DOI (a match, or an explicitly given
        `doi`) removes the entry from the group again -- so repeated
        fill-in passes never re-query the sources for an entry
        already searched. With `overwrite=True`, the membership is
        ignored and the lookup re-runs: an explicit re-audit.
        Membership means "searched, nothing found at the time", not
        "does not exist" -- the earlier match may have failed, or a
        DOI may have been registered since the last check -- so
        re-audit periodically, selecting exactly the group members
        with {meth}`keys` (`group="No DOI"`). A re-audited entry with
        another clean no-match simply stays in the group; a match
        stores the DOI and unmarks. A failed lookup (match `"error"`)
        never marks the entry, so a re-run picks it up. Membership
        also makes the `check` command accept an `article` without a
        `doi`. Without the configuration, none of this bookkeeping
        happens.

        Returns a named tuple `(doi, match, ratio, note, applied)`:
        the stored (or existing) DOI (`""` if none), how it was found
        (`"eprint"` for the DOI recorded on arXiv for the entry's
        eprint; `"title"` or `"title+author"` for a Crossref search
        match, in decreasing order of strength; `"explicit"` for a
        given DOI; `"none"` for a clean no-match; `"error"` when the
        lookup could not run to completion -- network/API failure, or
        an entry without a title; `"existing"`, `"known-missing"`, or
        `"preprint"` when the entry was skipped), the title-similarity
        ratio of the best Crossref result (`None` when no search
        ran), a short diagnostic trace (`note`), and whether the
        library was modified -- the entry's `doi` field, or its
        known-missing group membership (`applied`).

        Like any other modification, changes only become permanent
        with {meth}`save`. Raises {exc}`KeyError` if `key` is not in
        the library and {exc}`ValueError` if an explicitly given
        `doi` is not a valid DOI. Network problems never raise. An
        `eprint` lookup respects the arXiv API's rate limit (one
        request every three seconds, shared with {meth}`add_preprint`
        searches), so budget time accordingly for large batch runs.
        """
        # Imported lazily: the dois module pulls in the network
        # dependencies, needed nowhere else.
        from . import dois  # pylint: disable=import-outside-toplevel

        entry = self._entries[key]
        if doi is None and not overwrite:
            group = self._known_missing_group("doi")
            if self._is_known_missing("doi", key):
                return dois.DoiResult(
                    doi="",
                    match="known-missing",
                    ratio=None,
                    note=f"in group {group!r} (overwrite to re-search)",
                    applied=False,
                )
        result = entry._add_doi(doi, overwrite=overwrite)
        if result.applied and result.doi:
            self._clear_known_missing("doi", key)
        elif result.match == "none" and self._mark_known_missing("doi", key):
            result = result._replace(applied=True)
        return result
