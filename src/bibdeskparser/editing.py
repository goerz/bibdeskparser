r"""`$EDITOR` round-trip editing of `Entry` objects and `Library` strings.

Provides {func}`edit_entries` and {func}`edit_strings`: pure functions that
export data to a temporary `.bib`-like file, open it in `$EDITOR` (or
pass it to a caller-supplied *function* acting as the editor -- see
below), wait for the editor to finish, re-parse the (possibly edited)
result, validate it, and merge any changes back into the *original*
{class}`bibdeskparser.entry.Entry` objects (and, optionally, a
{class}`bibdeskparser.library.Library`'s `.strings`). This includes an
entry's `keywords = {...}` line, which merges back through the entry's
keywords accessors ({attr}`bibdeskparser.entry.Entry.keywords` is not
part of the dict interface). Neither function is
a method on `Library` -- wiring those up (e.g. `Library.edit()`) is
out of scope for this module. Also provides {func}`strings_bib_text`,
which renders a `{name: value}` macro mapping as the exact `@string`
text that {func}`edit_strings` presents in the editor (used by the
command-line tool's `strings --bib` to produce a byte-identical
baseline for `edit_strings --stdin`).

The editor is always presented with the default export form (Unicode
values, `bdsk-file-N`/`bdsk-url-N` as plain paths/URLs): re-parsing
and merging back relies on that exact text shape.

In both functions, the `editor` argument may be a shell command string
(or `None`, falling back to `$EDITOR`, then `"vi"`), or a *callable*
taking the temporary file's {class}`pathlib.Path` as its only argument
and overwriting that file in place, like a text editor would (its
return value is ignored; any exception it raises propagates to the
caller). With a callable editor there is no interactive
reopen-or-abandon prompt: a validation failure raises {exc}`ValueError`
instead (see {func}`edit_entries`/{func}`edit_strings`).

## Known limitations

* {func}`edit_entries` can only edit the fields of *existing* entries
  matched by citation key: it cannot add or remove entries. An
  original entry whose key does not appear in the edited text is left
  untouched (with a `UserWarning`); an entry block in the edited text
  whose key does not match any original entry is silently ignored
  (also with a `UserWarning`). Renaming a citekey is not supported
  either, since that has wider implications (e.g. `Library` dict-key
  consistency) that are out of scope here.
* In {func}`edit_strings`, a macro whose deletion fails (because it is
  still referenced by an entry) is reported as a validation problem
  for that round and can be fixed by reopening the editor; however,
  *other* changes from that same round (new/redefined/renamed macros)
  are **not** rolled back if a later deletion in the same round fails
  -- only failed deletions are retried. This is a deliberate
  simplification (deletions are rare and usually singular); see the
  function's docstring.

A callable editor makes the round trip usable without any subprocess
or user interaction:

```python
>>> from bibdeskparser.entry import Entry
>>> from bibdeskparser.editing import edit_entries
>>> entry = Entry("article", "Key2024", fields={"title": "A Titel"})
>>> def editor(path):
...     text = path.read_text(encoding="utf-8")
...     path.write_text(text.replace("Titel", "Title"), encoding="utf-8")
>>> edit_entries([entry], editor=editor)
>>> entry["title"]
'A Title'

```

The interactive path (launching an editor subprocess and prompting to
reopen or abandon on a validation failure) cannot be exercised in a
doctest; see `tests/test_editing.py` for its coverage, using scripted
editor commands.
"""

import os
import re
import shlex
import subprocess
import tempfile
import warnings
from pathlib import Path

import bibtexparser

from .bdskfile import BibDeskFile
from .exporting import export_entries
from .macros import STANDARD_MACROS, is_valid_macro_name, normalize_macro_name

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["edit_entries", "edit_strings", "strings_bib_text"]

_DATE_KEYS = frozenset(("date-added", "date-modified"))
_BDSK_FILE_RE = re.compile(r"bdsk-file-(\d+)$", re.IGNORECASE)
_BDSK_URL_RE = re.compile(r"bdsk-url-(\d+)$", re.IGNORECASE)


# -- small local helpers (do not import the private originals) ------- #


def _strip_enclosing(value):
    """Strip one matching pair of enclosing `{...}`/`"..."` from
    `value`, if present; else return it unchanged (a bare token stays
    bare)."""
    if (
        isinstance(value, str)
        and len(value) >= 2
        and (
            (value[0] == "{" and value[-1] == "}")
            or (value[0] == '"' and value[-1] == '"')
        )
    ):
        return value[1:-1]
    return value


def _is_bare(value):
    """Whether `value` is a non-empty string with no enclosing
    `{...}`/`"..."` (a candidate bare macro reference)."""
    return isinstance(value, str) and bool(value) and value[0] not in '{"'


def _is_bdsk_field(key):
    """Whether `key` is a `bdsk-file-N`/`bdsk-url-N` field name."""
    return bool(_BDSK_FILE_RE.match(key) or _BDSK_URL_RE.match(key))


def _split_keywords(raw):
    """Split a comma-separated `keywords` field value into a tuple of
    stripped, non-empty keywords."""
    return tuple(kw.strip() for kw in raw.split(",") if kw.strip())


# -- editor invocation ------------------------------------------------- #


def _write_temp_file(text):
    """Write `text` to a new, closed temporary `.bib` file; return its
    `Path`."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".bib", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(text)
        path = Path(tmp.name)
    return path


def _run_editor(editor, path):
    """Run the editor on `path`, waiting for it to finish.

    A callable `editor` is simply called with `path` (it must edit the
    file in place; its return value is ignored). Otherwise, `editor` is
    a shell command string, resolved in the order: the explicit
    `editor` argument, else `$EDITOR`, else `"vi"`. Any exception
    raised by the callable, by a missing command, or by a non-zero
    exit status (`subprocess.CalledProcessError`) propagates to the
    caller unchanged.
    """
    if callable(editor):
        editor(path)
        return
    command = editor or os.environ.get("EDITOR") or "vi"
    if os.name == "nt":
        # shlex.split is POSIX-only: it treats backslashes as escape
        # characters and mangles Windows paths. Use posix=False and strip
        # the surrounding quotes that non-POSIX mode preserves. posix=False
        # rejects a quote mid-token (a valid way to quote just a space in a
        # Windows path), so fall back to treating the whole command as a
        # single program path in that case.
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            tokens = [command]
        args = []
        for token in tokens:
            if (
                len(token) >= 2
                and token[0] == token[-1]
                and token[0] in ('"', "'")
            ):
                token = token[1:-1]
            args.append(token)
    else:
        args = shlex.split(command)
    subprocess.run(args + [str(path)], check=True)


def _prompt_reopen_or_abandon(problems):
    """Warn about `problems` (a list of human-readable strings) and
    interactively ask whether to reopen the editor or abandon the
    edit.

    Returns `True` to reopen, `False` to abandon. If `input()` raises
    `EOFError`/`OSError` (non-interactive stdin, e.g. under pytest/CI),
    or the user's answer is anything other than `"r"`
    (case-insensitively; empty/EOF defaults to abandon), abandonment is
    chosen and an additional `"edit abandoned"` warning is emitted.
    """
    message = "Validation failed:\n" + "\n".join(problems)
    warnings.warn(message, UserWarning, stacklevel=3)
    try:
        choice = input(f"{message}\n[r]eopen editor to fix, [a]bandon edit? ")
    except (EOFError, OSError):
        choice = "a"
    choice = (choice or "a").strip().lower()
    if choice == "r":
        return True
    warnings.warn("edit abandoned", UserWarning, stacklevel=3)
    return False


# -- validation --------------------------------------------------------- #


def _failed_block_problems(parsed):
    """Problem strings for every block of `parsed`
    (`bibtexparser.Library`) that failed to parse.

    `bibtexparser.parse_string` does not raise an exception for a
    syntactically broken block (e.g. unbalanced braces, or a duplicate
    citation key): it silently turns it into a `ParsingFailedBlock` in
    `parsed.failed_blocks` instead. Surfacing those here is what makes
    such editor mistakes trigger the warn-and-reopen-or-abandon flow,
    rather than silently vanishing (as an entry simply "not found in
    the edited text").
    """
    return [
        f"could not parse block: {block.raw!r}"
        for block in parsed.failed_blocks
    ]


def _validate_parsed_entries(parsed, library):
    """Collect human-readable validation problems for a `parsed`
    `bibtexparser.Library` (from `parse_string(text, parse_stack=[])`)
    representing edited `Entry` blocks.

    * Every entry must have a non-empty `entry_type` and `key`.
    * If `library` is given, every bare field value shaped like a
      macro name must resolve to a name already in `library.strings`,
      a standard month macro (`STANDARD_MACROS`), or a name newly
      defined by an `@string` block in the edited text itself (so a
      rename/new-definition is not rejected just because it is not
      yet in `library.strings`). The `keywords` field is exempt:
      keywords are always literal text, never a macro reference.
    """
    problems = list(_failed_block_problems(parsed))
    for entry in parsed.entries:
        if not entry.entry_type:
            problems.append(f"entry {entry.key!r}: missing entry type")
        if not entry.key:
            problems.append("an entry is missing its citation key")
    if library is not None:
        defined = set(dict(library.strings)) | set(STANDARD_MACROS)
        for string in parsed.strings:
            if is_valid_macro_name(string.key, normalized=False):
                defined.add(normalize_macro_name(string.key))
        for entry in parsed.entries:
            for field in entry.fields:
                lkey = field.key.lower()
                if (
                    _is_bdsk_field(field.key)
                    or lkey in _DATE_KEYS
                    or lkey == "keywords"
                ):
                    continue
                value = field.value
                if not _is_bare(value):
                    continue
                if not is_valid_macro_name(value, normalized=False):
                    continue
                if normalize_macro_name(value) not in defined:
                    problems.append(
                        f"entry {entry.key!r}: undefined macro "
                        f"{value!r} referenced by field {field.key!r}"
                    )
    return problems


def _file_problems(parsed, entries, base_dir):
    """Problem strings for the edited `bdsk-file-N` paths of `parsed`.

    A path that does not match one of the target entry's existing
    attachments (`entry.files`) is a *changed* attachment: it must
    exist as a file relative to `base_dir` (the library's `.bib`
    directory, or the CWD when editing without a library). If the
    library has no file path at all (`base_dir` is `None`),
    attachments cannot be changed at all."""
    problems = []
    originals = {entry.key: entry for entry in entries}
    for parsed_entry in parsed.entries:
        original = originals.get(parsed_entry.key)
        if original is None:
            continue
        existing = set(original.files)
        for field in parsed_entry.fields:
            if not _BDSK_FILE_RE.match(field.key):
                continue
            path = _strip_enclosing(field.value)
            if path in existing:
                continue
            if base_dir is None:
                problems.append(
                    f"entry {parsed_entry.key!r}: cannot change "
                    f"linked file {path!r}: the library has no file "
                    "path yet (save it first)"
                )
            elif not (base_dir / path).exists():
                problems.append(
                    f"entry {parsed_entry.key!r}: linked file does "
                    f"not exist: {path!r} (relative to {base_dir})"
                )
    return problems


def _parse_and_validate_entries(text, library, entries, base_dir):
    """Parse `text` (edited `Entry` blocks) and validate it.

    Returns `(parsed_library_or_None, problems)`: a parse failure is
    caught and reported as a single problem, `parsed_library` is then
    `None`."""
    try:
        # An empty parse_stack (no middleware) keeps braces verbatim,
        # matching what export_entries() (with default parameters)
        # wrote: in particular, bdsk-file-N fields are plain path strings
        # here, not the base64 blob the normal read middleware stack
        # expects to decode, so running that stack over edited text
        # would fail or corrupt the paths. Field values are then
        # brace-stripped locally (_strip_enclosing) and fed into the
        # target Entry's normal __setitem__, which re-texifies/
        # re-braces/re-validates a plain Unicode string exactly as if
        # the user had set it directly in Python.
        parsed = bibtexparser.parse_string(text, parse_stack=[])
    except Exception as exc:  # pylint: disable=broad-except
        return None, [f"parse error: {exc}"]
    problems = _validate_parsed_entries(parsed, library)
    problems.extend(_file_problems(parsed, entries, base_dir))
    return parsed, problems


def _parse_and_validate_strings(text):
    """Parse `text` (edited `@string` blocks only) and validate it.

    Returns `(parsed_library_or_None, problems)`, like
    `_parse_and_validate_entries`; validation here only checks
    that every `@string` name is a valid BibDesk macro name."""
    try:
        parsed = bibtexparser.parse_string(text, parse_stack=[])
    except Exception as exc:  # pylint: disable=broad-except
        return None, [f"parse error: {exc}"]
    problems = _failed_block_problems(parsed)
    problems.extend(
        f"invalid macro name: {string.key!r}"
        for string in parsed.strings
        if not is_valid_macro_name(string.key, normalized=False)
    )
    return parsed, problems


# -- merging: entries --------------------------------------------------- #


def _merge_fields(original_entry, parsed_entry):
    """Merge `parsed_entry`'s normal fields into `original_entry`
    in-place: set changed/new fields, delete fields absent from the
    edited block. The `keywords` field is readable through `Entry`'s
    dict interface but not writable, so it is merged through the
    entry's dedicated keywords accessors instead."""
    parsed_by_key = {}
    for field in parsed_entry.fields:
        if _is_bdsk_field(field.key) or field.key.lower() in _DATE_KEYS:
            continue
        parsed_by_key[field.key.lower()] = (field.key, field.value)
    keywords_item = parsed_by_key.pop("keywords", None)
    new_keywords = (
        _split_keywords(_strip_enclosing(keywords_item[1]))
        if keywords_item is not None
        else ()
    )
    if new_keywords != original_entry.keywords:
        # pylint: disable=protected-access
        original_entry._set_keywords(new_keywords)
    for key in list(original_entry.keys()):
        # `keywords` is readable via the dict interface but merged
        # separately (above), so it is never deleted through the dict.
        if key.lower() == "keywords":
            continue
        if key.lower() not in parsed_by_key:
            del original_entry[key]
    for orig_key, raw_value in parsed_by_key.values():
        value = _strip_enclosing(raw_value)
        if original_entry.get(orig_key) != value:
            original_entry[orig_key] = value


def _merge_files_urls(original_entry, parsed_entry, base_dir):
    """Merge `parsed_entry`'s `bdsk-file-N`/`bdsk-url-N` fields into
    `original_entry`'s attachments/`.urls`, interpreting file paths
    relative to `base_dir` (the library's `.bib` directory, or the
    CWD when editing without a library).

    A path matching one of `original_entry`'s current attachments
    keeps that attachment's existing data (bookmark); a changed path
    gets a fresh `BibDeskFile`. Validation (`_file_problems`) has
    already ensured that every changed path exists relative to
    `base_dir` (and that `base_dir` is not `None` when anything
    changed), so `must_exist=False` here only covers the file
    disappearing between validation and merge."""
    file_items = []
    url_items = []
    for field in parsed_entry.fields:
        match = _BDSK_FILE_RE.match(field.key)
        if match:
            file_items.append(
                (int(match.group(1)), _strip_enclosing(field.value))
            )
            continue
        match = _BDSK_URL_RE.match(field.key)
        if match:
            url_items.append(
                (int(match.group(1)), _strip_enclosing(field.value))
            )
    new_files = [path for _, path in sorted(file_items)]
    new_urls = [url for _, url in sorted(url_items)]
    if new_files != original_entry.files:
        # pylint: disable=protected-access
        by_rel_path = {
            f.relative_path: f for f in original_entry._file_objects()
        }
        original_entry._set_files(
            [
                by_rel_path.get(path)
                or BibDeskFile(
                    base_dir / path,
                    relative_to=base_dir,
                    must_exist=False,
                )
                for path in new_files
            ]
        )
    if list(new_urls) != list(original_entry.urls):
        original_entry._set_urls(new_urls)  # pylint: disable=protected-access


def _merge_entries(entries, parsed, base_dir):
    """Merge every parsed entry block in `parsed` back into the
    matching (by citation key) `Entry` of `entries`; warn about keys
    that could not be matched in either direction (see the module
    docstring's "known limitations"). `base_dir` is the directory
    that `bdsk-file-N` paths are relative to (see
    `_merge_files_urls`)."""
    parsed_by_key = {entry.key: entry for entry in parsed.entries}
    original_keys = {entry.key for entry in entries}
    for entry in entries:
        parsed_entry = parsed_by_key.get(entry.key)
        if parsed_entry is None:
            warnings.warn(
                f"entry {entry.key!r} not found in the edited text; "
                "left unchanged (edit_entries cannot delete entries)",
                UserWarning,
                stacklevel=3,
            )
            continue
        if parsed_entry.entry_type != entry.entry_type:
            entry.entry_type = parsed_entry.entry_type
        _merge_fields(entry, parsed_entry)
        _merge_files_urls(entry, parsed_entry, base_dir)
    for key in parsed_by_key:
        if key not in original_keys:
            warnings.warn(
                f"entry {key!r} is new and was ignored (edit_entries "
                "cannot add entries)",
                UserWarning,
                stacklevel=3,
            )


# -- merging: @string macros ---------------------------------------------- #


def _merge_strings(library, before, parsed_strings, allow_delete):
    """Merge `parsed_strings` (`{name: value}`, from the edited text)
    into `library.strings`, comparing against `before` (`{name:
    value}`, a snapshot of `library.strings` taken before the edit).

    * Unchanged name/value pairs are ignored.
    * A name already in `before` whose value changed is redefined
      (`library.strings[name] = value`).
    * A new name whose value exactly matches an existing (and not yet
      consumed by another rename this round) macro's original value is
      treated as a rename (`library.rename_string`); otherwise it is a
      new definition.
    * If `allow_delete`, every name in `before` that is absent from
      `parsed_strings` (and was not itself consumed by a rename this
      round) is deleted (`del library.strings[name]`); a `ValueError`
      from a still-in-use macro is caught and returned as a problem
      string rather than propagated, so the caller can re-prompt for
      another editing round instead of crashing -- other changes
      already applied this round (defines/redefines/renames, and any
      *other* successful deletions) are deliberately not rolled back.

    Returns a list of problem strings (only ever non-empty when
    `allow_delete` is true and a deletion failed).
    """
    consumed = set()
    for name, value in parsed_strings.items():
        if name in before:
            if before[name] != value:
                library.strings[name] = value
            continue
        rename_from = next(
            (
                old_name
                for old_name, old_value in before.items()
                if old_name not in parsed_strings
                and old_name not in consumed
                and old_value == value
            ),
            None,
        )
        if rename_from is not None:
            library.rename_string(rename_from, name)
            consumed.add(rename_from)
        else:
            library.strings[name] = value
    problems = []
    if allow_delete:
        for name in before:
            if name in parsed_strings or name in consumed:
                continue
            try:
                del library.strings[name]
            except ValueError as exc:
                problems.append(str(exc))
    return problems


# -- public API ----------------------------------------------------------- #


def edit_entries(entries, library=None, editor=None):
    """Edit `entries` together in `$EDITOR`, merging changes back.

    ```python
    edit_entries(entries, library=None, editor=None)
    ```

    Exports `entries` (an iterable of {class}`bibdeskparser.entry.Entry`)
    to a temporary file via {func}`bibdeskparser.exporting.export_entries`,
    opens it in `editor`, waits for the editor to exit, re-parses the
    result, validates it, and merges the changes back into the
    *original* `Entry` objects (not copies) -- see the module docstring
    for the exact merge algorithm and its known limitations.

    * `entries`: an iterable of `Entry` to edit together in one file
      (also covers "edit a single entry": pass a one-element list).
    * `library`: optional {class}`bibdeskparser.library.Library`-like
      object (only `.strings` mapping semantics and
      `.rename_string(old, new)` are required -- no import of the
      `Library` class happens here). If given, its current `@string`
      definitions are included in the exported text (so it is
      self-contained) and any `@string` changes detected in the edited
      text are merged back into `library.strings` (including
      macro-rename detection via `library.rename_string`).
    * `editor`: a shell command string (may include arguments, e.g.
      `"code --wait"`), with resolution order: this argument, else
      `$EDITOR`, else `"vi"` -- or a callable taking the temporary
      file's {class}`pathlib.Path` as its only argument and
      overwriting that file in place, like a text editor would (its
      return value is ignored; any exception it raises propagates,
      and the temporary file is removed).

    If the edited text fails to parse or fails validation (see the
    module docstring), the behavior depends on the kind of `editor`:

    * With a command-string (or default) editor, a `UserWarning`
      describing the problem(s) is emitted and the user is
      interactively prompted (via `input()`) to either reopen the
      editor on the same file (preserving their partial edit) or
      abandon the edit entirely. Under non-interactive stdin
      (`input()` raising `EOFError`/`OSError`, e.g. under pytest/CI),
      the edit is silently abandoned. On abandonment,
      `entries`/`library` are left completely unchanged.
    * With a callable editor, there is no prompt: a {exc}`ValueError`
      listing the problem(s) is raised instead, and
      `entries`/`library` are left completely unchanged.

    `bdsk-file-N` paths in the edited text are interpreted relative
    to the directory of `library`'s `.bib` file (falling back to the
    current working directory when no `library` is given). A changed
    path must point to an existing file there; otherwise it is
    reported as a validation problem (see above). If `library` has no
    file path yet (never saved), any change to a `bdsk-file-N` line
    is a validation problem: linked files are stored relative to the
    library's `.bib` file, so the library must be saved first.
    """
    entries = list(entries)
    strings = dict(library.strings) if library is not None else None
    if library is None:
        base_dir = Path.cwd()
    else:
        # Reaching into `Library._path` crosses a module boundary, but
        # not a public API boundary (same package); a `library` that
        # has no such attribute is treated like a never-saved one.
        library_path = getattr(library, "_path", None)
        base_dir = (
            Path(library_path).resolve().parent
            if library_path is not None
            else None
        )
    text = export_entries(entries, strings=strings)
    path = _write_temp_file(text)
    try:
        while True:
            _run_editor(editor, path)
            edited_text = path.read_text(encoding="utf-8")
            parsed, problems = _parse_and_validate_entries(
                edited_text, library, entries, base_dir
            )
            if problems:
                if callable(editor):
                    raise ValueError(
                        "Validation failed:\n" + "\n".join(problems)
                    )
                if _prompt_reopen_or_abandon(problems):
                    continue
                return
            _merge_entries(entries, parsed, base_dir)
            if library is not None:
                parsed_strings = {
                    string.key: _strip_enclosing(string.value)
                    for string in parsed.strings
                }
                _merge_strings(
                    library, strings, parsed_strings, allow_delete=False
                )
            return
    finally:
        path.unlink(missing_ok=True)


def strings_bib_text(strings):
    """Render `strings` (a `{name: value}` mapping) as a series of
    `@string{name = {value}}` lines, sorted by name, with a trailing
    newline (the empty string for an empty mapping).

    This is exactly the text that {func}`edit_strings` presents in the
    editor, so it can serve as the baseline for a non-interactive
    (callable-editor) round trip.
    """
    text = "\n".join(
        f"@string{{{name} = {{{value}}}}}"
        for name, value in sorted(strings.items())
    )
    if text:
        text += "\n"
    return text


def edit_strings(library, editor=None):
    """Edit just `library`'s `@string` macro definitions in `$EDITOR`.

    ```python
    edit_strings(library, editor=None)
    ```

    Exports `library.strings` (only, no entries) as a series of
    `@string{name = {value}}` lines, sorted by name, opens it in
    `editor`, waits for the editor to exit, re-parses the result,
    validates it, and merges the changes back into `library.strings`
    (macro names are matched case-insensitively, normalized to
    BibDesk's canonical lowercase form):

    * A new name/value pair is defined.
    * A changed value is redefined in place.
    * A new name whose value matches a pre-existing (and not yet
      renamed-away) macro's original value is treated as a rename via
      `library.rename_string`.
    * A name that disappeared from the edited text is deleted
      (`del library.strings[name]`); if that macro is still referenced
      by an entry, the resulting `ValueError` is treated as a
      validation problem for that editing round (see the module
      docstring's "known limitations" for why other changes in the
      same round are not rolled back).

    * `library`: a {class}`bibdeskparser.library.Library`-like object
      (only `.strings` mapping semantics and `.rename_string` are
      used).
    * `editor`: as in {func}`edit_entries`.

    Validation failure (parse error, or an `@string` name that is not
    a valid BibDesk macro name per
    {func}`bibdeskparser.macros.is_valid_macro_name`, or a failed
    deletion) triggers the same warn-and-prompt-to-reopen-or-abandon
    flow as {func}`edit_entries` -- or, with a callable `editor`,
    raises {exc}`ValueError` instead of prompting. Note that a failed
    *deletion* is only detected while merging, after the other changes
    from the same round (new/redefined/renamed macros, and any other
    successful deletions) have already been applied: when catching the
    `ValueError` and continuing to use `library`, be aware that those
    changes are not rolled back.
    """
    before = dict(library.strings)
    path = _write_temp_file(strings_bib_text(before))
    try:
        while True:
            _run_editor(editor, path)
            edited_text = path.read_text(encoding="utf-8")
            parsed, problems = _parse_and_validate_strings(edited_text)
            if not problems:
                # Validation has already checked every name, so
                # normalization cannot fail here; it maps an edited
                # mixed-case name onto the same (lowercase) macro,
                # matching BibDesk's case-insensitive macro table.
                parsed_strings = {
                    normalize_macro_name(string.key): _strip_enclosing(
                        string.value
                    )
                    for string in parsed.strings
                }
                problems = _merge_strings(
                    library, before, parsed_strings, allow_delete=True
                )
                before = dict(library.strings)
            if problems:
                if callable(editor):
                    raise ValueError(
                        "Validation failed:\n" + "\n".join(problems)
                    )
                if _prompt_reopen_or_abandon(problems):
                    continue
                return
            return
    finally:
        path.unlink(missing_ok=True)
