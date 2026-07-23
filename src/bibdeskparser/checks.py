"""Standing audits backing the `check` CLI command.

Inspection of a loaded {class}`bibdeskparser.Library`: each function
returns {class}`Problem` records and never modifies the library. Most
audits look only at the parsed data; the opt-in files audit
additionally *reads* the filesystem to check that linked attachments
resolve on disk. The CLI command turns the records into a report and a
pass/fail exit code.
"""

import os
import posixpath
from collections import namedtuple

from bibtexparser.model import DuplicateBlockKeyBlock

from .config import active
from .identifiers import _entry_preprint, _preprint_journal
from .library import _bare_macro_fields, _has_field
from .macros import MacroString
from .render import _can_initialize

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["Problem", "collect_problems"]


#: One audit finding. `check` names the audit (`"parse"`,
#: `"duplicate_keys"`, `"doi"`, `"empty_fields"`, `"known_missing"`,
#: `"journal"`, `"names"`, `"unused_strings"`, or `"files"`), `key` is
#: the citation key the problem is tied to (`None` for a problem that
#: concerns the file as a whole), and `message` describes the problem.
Problem = namedtuple("Problem", ["check", "key", "message"])


def collect_problems(library, keys=None, audit_files=False):
    """Every standing-audit problem in `library`, as a `list` of
    {class}`Problem`.

    Without `keys`, all audits run over the entire library. With
    `keys` (an iterable of citation keys, all of which must exist in
    `library`), the doi, journal, and names audits cover only those
    entries, the duplicate-keys audit reports only those keys, and
    the unused-macros audit is skipped; problems parsing the file
    itself are always included.

    With `audit_files`, an additional per-entry audit checks that each
    linked attachment (`bdsk-file-N` field) resolves to a real path on
    disk, relative to the library's `.bib` directory, matching case
    exactly. It is off by default because attachments may legitimately
    live only on another machine.
    """
    problems = _parse_problems(library)
    if keys is None:
        duplicates = library.duplicate_keys
        entries = library.entries
    else:
        keys = list(dict.fromkeys(keys))
        duplicates = [key for key in library.duplicate_keys if key in keys]
        entries = [library[key] for key in keys]
    problems += [
        Problem("duplicate_keys", key, "duplicate citation key")
        for key in duplicates
    ]
    # pylint: disable-next=protected-access
    base_dir = library._files_base_dir() if audit_files else None
    listdir_cache = {}
    for entry in entries:
        problems += _entry_problems(entry, library)
        if audit_files:
            problems += _file_problems(entry, base_dir, listdir_cache)
    if keys is None:
        problems += _unused_string_problems(library)
    return problems


def _parse_problems(library):
    """Problems for the blocks that were skipped when parsing the
    `.bib` file, excluding duplicate-key blocks (which the
    duplicate-keys audit reports per key instead)."""
    return [
        Problem(
            "parse",
            None,
            f"block at line {block.start_line + 1} could not be "
            f"parsed: {block.error}",
        )
        # pylint: disable-next=protected-access
        for block in library._library.failed_blocks
        if not isinstance(block, DuplicateBlockKeyBlock)
    ]


def _entry_problems(entry, library):
    """The doi, empty-field, known-missing, journal, and names
    problems of a single `entry`."""
    problems = []
    archives = active.preprint_archives
    known_missing = active.known_missing
    is_preprint = _entry_preprint(entry, archives) is not None
    doi_group = known_missing.get("doi")
    if (
        entry.entry_type.lower() == "article"
        and not is_preprint
        and not _has_field(entry, "doi")
        and not (doi_group is not None and doi_group in entry.groups)
    ):
        problems.append(Problem("doi", entry.key, "missing doi"))
    for name in entry:
        if not str(entry[name]).strip():
            problems.append(
                Problem(
                    "empty_fields",
                    entry.key,
                    f"empty field {name!r} (BibDesk deletes empty "
                    "fields on save)",
                )
            )
    for field, group in known_missing.items():
        if group in entry.groups and _has_field(entry, field):
            problems.append(
                Problem(
                    "known_missing",
                    entry.key,
                    f"in group {group!r} (known-missing {field}) but "
                    f"has a non-empty {field}",
                )
            )
    if "journal" in entry:
        problems += _journal_problems(entry, library, archives)
    for field in ("author", "editor"):
        if field in entry:
            try:
                names = getattr(entry, field)
            except Exception as exc:  # pylint: disable=broad-except
                problems.append(
                    Problem(
                        "names",
                        entry.key,
                        f"{field} does not parse as names: {exc}",
                    )
                )
                continue
            for name in names:
                for part in name.first:
                    if part and not _can_initialize(part):
                        problems.append(
                            Problem(
                                "names",
                                entry.key,
                                f"{field} name "
                                f'"{name.merge_last_name_first}" has a '
                                f'first-name part ("{part}") that '
                                "cannot be initialized",
                            )
                        )
    return problems


def _journal_problems(entry, library, archives):
    """The problems with `entry`'s `journal` field: a reference to an
    undefined `@string` macro, or a non-empty literal value that is
    not a recognized preprint pseudo-journal."""
    value = entry["journal"]
    if isinstance(value, MacroString):
        name = str(value)
        # pylint: disable-next=protected-access
        if name.lower() not in library._all_strings():
            return [
                Problem(
                    "journal",
                    entry.key,
                    f"journal references undefined @string macro {name!r}",
                )
            ]
        return []
    text = str(value).strip()
    if text and _preprint_journal(text, archives) is None:
        return [
            Problem(
                "journal",
                entry.key,
                f"journal is the literal string {text!r}, not an "
                "@string macro reference",
            )
        ]
    return []


def _unused_string_problems(library):
    """Problems for the `@string` macros defined in the `.bib` file
    but not referenced by any entry."""
    referenced = set()
    for entry in library.entries:
        for _, value in _bare_macro_fields(entry):
            referenced.add(value.lower())
    return [
        Problem("unused_strings", None, f"unused @string macro {name!r}")
        for name in library.strings
        if name not in referenced
    ]


def _file_problems(entry, base_dir, listdir_cache):
    """Problems for `entry`'s linked attachments (`bdsk-file-N`
    fields) that do not resolve on disk relative to `base_dir` (the
    library's `.bib` directory, a resolved `Path`).

    Each stored relative path is walked one component at a time,
    matching case exactly against a cached `os.listdir` of each
    directory. This is deterministic across platforms: a
    case-insensitive filesystem cannot hold two names differing only
    in case, so a case-mismatched link is reported on macOS and on a
    case-sensitive Linux CI alike, whereas plain `os.path.exists`
    would accept it on macOS and reject it on Linux. Three problem
    classes: an empty stored path, a link that does not resolve, and
    a link whose on-disk spelling differs only in case (a directory
    resolves like any other path -- BibDesk can link folders).

    `listdir_cache` maps a directory `Path` to its `set` of entry
    names; pass the same dict across a whole audit run so each
    directory is listed at most once.
    """
    problems = []
    for rel_path in entry.files:
        if not rel_path.strip():
            problems.append(
                Problem(
                    "files",
                    entry.key,
                    "linked file attachment has an empty path",
                )
            )
            continue
        status, on_disk = _resolve_exact_case(
            base_dir, rel_path, listdir_cache
        )
        if status == "missing":
            problems.append(
                Problem(
                    "files",
                    entry.key,
                    f"linked file does not exist: {rel_path!r}",
                )
            )
        elif status == "case":
            problems.append(
                Problem(
                    "files",
                    entry.key,
                    f"linked file {rel_path!r} exists only as "
                    f"{on_disk!r} (case mismatch)",
                )
            )
    return problems


def _resolve_exact_case(base_dir, rel_path, listdir_cache):
    """Resolve `rel_path` (a stored POSIX relative path) below
    `base_dir`, checking every component's case exactly.

    Returns `("ok", None)` if the path resolves with exact case,
    `("missing", None)` if it does not resolve at all (or resolves
    only to a broken symlink), and `("case", on_disk)` if the full
    path resolves but at least one component's on-disk case differs,
    where `on_disk` is the path as actually spelled on disk.

    The whole path must resolve for a case mismatch to be reported:
    the walk descends into the real on-disk name of each component and
    keeps going after a case-only match, so a case-variant ancestor
    whose subtree is missing the rest of the path is reported as a
    missing link, not a case mismatch."""
    current = base_dir
    on_disk = []  # the matched components as actually spelled on disk
    mismatch = False
    for part in posixpath.normpath(rel_path).split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            on_disk.append("..")
            continue
        names = _listdir(current, listdir_cache)
        if part in names:
            current = current / part
            on_disk.append(part)
            continue
        match = next(
            (name for name in names if name.lower() == part.lower()), None
        )
        if match is None:
            return ("missing", None)
        mismatch = True
        current = current / match
        on_disk.append(match)
    # A final exists() check follows symlinks, catching a link whose
    # target was removed.
    if not os.path.exists(current):
        return ("missing", None)
    return ("case", "/".join(on_disk)) if mismatch else ("ok", None)


def _listdir(directory, listdir_cache):
    """The `set` of entry names in `directory` (a `Path`), cached in
    `listdir_cache`; an empty set if `directory` is missing or is not
    a directory."""
    names = listdir_cache.get(directory)
    if names is None:
        try:
            names = set(os.listdir(directory))
        except OSError:
            names = set()
        listdir_cache[directory] = names
    return names
