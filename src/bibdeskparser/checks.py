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
import re
from collections import namedtuple

from bibtexparser.model import DuplicateBlockKeyBlock

from .config import active
from .entry import _percent_encode_url, _strip_enclosing
from .identifiers import _entry_preprint, _preprint_journal
from .importing import _PREPRINT_KEY_SPEC
from .library import _bare_macro_fields, _has_field
from .macros import STANDARD_MONTH_MACROS, MacroString, is_valid_macro_name
from .render import _can_initialize
from .specifiers import compile_format

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["Problem", "collect_problems"]


#: One audit finding. `check` names the audit (`"parse"`,
#: `"duplicate_keys"`, `"entry_type"`, `"required_fields"`, `"doi"`,
#: `"empty_fields"`, `"known_missing"`, `"journal"`,
#: `"undefined_macro"`, `"year"`, `"month"`, `"names"`,
#: `"url_encoding"`, `"unused_strings"`, `"files"`, or `"key_format"`),
#: `key` is the citation key the problem is tied to
#: (`None` for a problem that concerns the file as a whole), and
#: `message` describes the problem.
Problem = namedtuple("Problem", ["check", "key", "message"])


def collect_problems(
    library, keys=None, *, audit_files=False, key_format=None
):
    """Every standing-audit problem in `library`, as a `list` of
    {class}`Problem`.

    Without `keys`, all audits run over the entire library. With
    `keys` (an iterable of citation keys, all of which must exist in
    `library`), the per-entry audits (entry type, required fields,
    doi, empty fields, known-missing, journal, undefined macros, year,
    month, names, and url encoding) cover only those entries, the
    duplicate-keys audit reports only those keys, and the unused-macros
    audit is skipped; problems parsing the file itself are always
    included.

    With `audit_files`, an additional per-entry audit checks that each
    linked attachment (`bdsk-file-N` field) resolves to a real path on
    disk, relative to the library's `.bib` directory, matching case
    exactly. It is off by default because attachments may legitimately
    live only on another machine.

    With `key_format`, an additional per-entry audit checks that each
    entry's citation key matches its expected auto-key format, i.e.
    that {meth}`~bibdeskparser.Library.eval_format_spec` evaluates the
    key to itself. `key_format=True` audits against the configured
    `[auto_key]` format; `key_format` as a `str` audits against that
    format pattern instead. A preprint-only entry is always audited
    against the preprint format (`%p1%f{eprint}[.]`) regardless. An
    entry lacking a field the format references is audited against the
    shorter key the format generates for it. If no usable format is
    available -- none configured and none given (`key_format=True`
    with no configured `[auto_key]` format), or a given pattern that
    does not compile -- a single file-wide problem is reported instead
    of one per entry.
    `key_format=None` (the default) skips this audit.
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
    # The macro mapping cannot change during an audit, so build it once
    # rather than per entry in `_undefined_macro_problems`.
    # pylint: disable-next=protected-access
    strings = library._all_strings()
    audit_key_format = key_format is not None
    format_spec = None if key_format is True else key_format
    if audit_key_format:
        unavailable = _key_format_unavailable(format_spec)
        if unavailable is not None:
            problems.append(Problem("key_format", None, unavailable))
            audit_key_format = False
    for entry in entries:
        problems += _entry_problems(entry, library, strings)
        if audit_files:
            problems += _file_problems(entry, base_dir, listdir_cache)
        if audit_key_format:
            problems += _key_format_problems(entry, library, format_spec)
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


def _entry_problems(entry, library, strings):
    """The entry-type, required-field, doi, empty-field,
    known-missing, journal, undefined-macro, year, month, names, and
    url-encoding problems of a single `entry`.

    `strings` is the library's merged macro mapping
    (`Library._all_strings()`), passed in so it is built once per audit
    run rather than per entry."""
    problems = _type_problems(entry)
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
        problems += _journal_problems(entry, archives)
    if _has_field(entry, "year"):
        problems += _year_problems(entry, library)
    if _has_field(entry, "month"):
        problems += _month_problems(entry)
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
    problems += _undefined_macro_problems(entry, strings)
    problems += _url_encoding_problems(entry)
    return problems


def _url_encoding_problems(entry):
    r"""The problems with `entry`'s URL-type values that hold raw
    non-ASCII characters: every field whose name contains `url` (the
    same class that is exempt from TeX encoding), plus the `bdsk-url-N`
    values. The message shows the percent-encoded form (what `add_url`
    stores) so the fix is copy-pasteable.

    Raw non-ASCII breaks a `\url{...}` in a LaTeX export (verbatim
    catcodes bypass `inputenc`) and is dropped by BibDesk on reload.
    Stored `url` field values are never rewritten automatically, so
    this audit is the only place they surface."""
    problems = []
    for name in entry:
        if "url" in name.lower():
            value = str(entry[name])
            if not value.isascii():
                problems.append(_url_encoding_problem(entry.key, name, value))
    # pylint: disable-next=protected-access
    for _, field in entry._bdsk_url_fields():
        value = _strip_enclosing(field.value)
        if not value.isascii():
            problems.append(_url_encoding_problem(entry.key, field.key, value))
    return problems


def _url_encoding_problem(key, field_name, value):
    """A single `url_encoding` {class}`Problem` for `field_name` holding
    the raw non-ASCII `value`, showing its percent-encoded form."""
    return Problem(
        "url_encoding",
        key,
        f"{field_name} contains non-ASCII characters: {value!r} "
        f"(use {_percent_encode_url(value)!r})",
    )


def _type_problems(entry):
    """The problems with `entry`'s type: a type outside the recognized
    entry types, or a required field of its type that the entry does
    not have.

    An entry with an unrecognized type is reported once and not
    audited for required fields; a recognized type BibDesk does not
    template (an extended data-model type like `dataset`) has no
    required fields on record and is skipped. Either is declared with
    a `[types.NAME]` table in `bibdeskparser.toml`, which also gives
    the type a field template.

    Both audits are unconditional: the `verify_types`/`verify_fields`
    settings govern what happens when a type or field is *assigned* in
    Python, whereas an entry read from a `.bib` file is never
    validated (loading a library is non-destructive), so `check` is
    the only place an inherited type problem surfaces.
    """
    entry_type = entry.entry_type.lower()
    if entry_type not in active.recognized_entry_types:
        return [
            Problem(
                "entry_type",
                entry.key,
                f"unrecognized entry type {entry_type!r}",
            )
        ]
    spec = active.documented_types.get(entry_type)
    if spec is None:
        return []
    return [
        Problem(
            "required_fields",
            entry.key,
            f"missing required field {field!r} for entry type "
            f"{entry_type!r}",
        )
        for field in spec["required"]
        if not _has_field(entry, field)
    ]


def _journal_problems(entry, archives):
    """The problems with `entry`'s `journal` field: a non-empty
    literal value that is not a recognized preprint pseudo-journal.

    A `journal` that bare-references an undefined `@string` macro is
    reported by `_undefined_macro_problems` instead, which audits every
    bare field alike."""
    value = entry["journal"]
    if isinstance(value, MacroString):
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


def _undefined_macro_problems(entry, strings):
    """The problems with `entry`'s bare field values that reference an
    undefined `@string` macro.

    `strings` is the library's merged macro mapping
    (`Library._all_strings()`), built once by `collect_problems`.

    Every bare (unbraced) field is inspected except `keywords` (always
    literal text), and only a value that is a valid macro name is
    considered, so a bare non-macro value like `volume = 90` is not
    flagged. A macro is undefined when it is defined neither by an
    `@string` in the file nor as one of the built-in month macros
    `jan` ... `dec`. This is the same scan
    {meth}`~bibdeskparser.Library.save` applies before writing: it
    rejects any such reference (a name that renders as itself, so
    `month = sept` becomes literal `sept`), so reporting it here means
    a passing `check` implies a writable file. The `journal` and
    `month` audits report their own, field-specific concerns on top of
    this one."""
    problems = []
    for field, value in _bare_macro_fields(entry):
        if (
            is_valid_macro_name(value, normalized=True)
            and value not in strings
        ):
            problems.append(
                Problem(
                    "undefined_macro",
                    entry.key,
                    f"{field.key} references undefined @string macro "
                    f"{value!r}",
                )
            )
    return problems


def _year_problems(entry, library):
    """The problems with `entry`'s `year` field: a value from which no
    four-digit year can be read.

    The rule is stated through the `%Y` specifier, which is how the
    year is read everywhere else (citation keys, file names): a value
    passes iff `%Y` yields exactly four digits. That accepts the
    values BibDesk itself reads correctly, including a two-digit
    `08` (mapped into 1950--2049) and a trailing-junk `2008a`, and
    rejects the ones where `%Y` falls back to its `0` sentinel."""
    rendered = library.eval_format_spec(entry.key, "%Y")
    if re.fullmatch(r"\d{4}", rendered):
        return []
    # for a macro-valued year this is the macro name, not its
    # expansion; the message also shows the resolved reading via %Y
    text = str(entry["year"]).strip()
    return [
        Problem(
            "year",
            entry.key,
            f"year {text!r} does not read as a four-digit year "
            f"(%Y gives {rendered!r})",
        )
    ]


def _month_problems(entry):
    """The problems with `entry`'s `month` field: anything other than
    a bare reference to one of the twelve standard month macros.

    Unlike `year`, this inspects the stored value rather than what
    `%m` renders: `%m` falls back to `01` for every unparseable month,
    which is indistinguishable from a genuine January. A literal value
    is reported even when it renders correctly (`06`, `June`), for the
    same reason a literal `journal` is: the macro is what lets the
    bibliography style abbreviate and localize the month."""
    value = entry["month"]
    standard = "one of the twelve standard month macros (jan ... dec)"
    if isinstance(value, MacroString):
        name = str(value)
        if name in STANDARD_MONTH_MACROS:
            return []
        return [
            Problem(
                "month",
                entry.key,
                f"month references the macro {name!r}, not {standard}",
            )
        ]
    return [
        Problem(
            "month",
            entry.key,
            f"month is the literal string {str(value).strip()!r}, not "
            f"{standard}",
        )
    ]


def _key_format_unavailable(format_spec):
    """A message explaining why the key-format audit cannot run, or
    `None` if it can.

    `format_spec` is an explicit format pattern (a `str`), or `None`
    to use the configured `[auto_key]` format. There is no usable
    format when none is configured and none was given, or when a given
    pattern does not compile (compiling it once here reports such a
    pattern as a single problem, rather than one per entry). A
    configured format is validated when the configuration is loaded,
    so it is not re-checked. The preprint-only entries use the
    always-valid preprint format, so they are unaffected by this."""
    if format_spec is None:
        if active.auto_key.format_spec is None:
            return (
                "no citation-key format available; configure an "
                "[auto_key] format_spec or pass a format pattern"
            )
        return None
    try:
        compile_format(format_spec)
    except (ValueError, NotImplementedError) as exc:
        return f"invalid citation-key format pattern: {exc}"
    return None


def _key_format_problems(entry, library, format_spec):
    """Problems for `entry` whose citation key does not match its
    expected auto-key format.

    A preprint-only entry is audited against the preprint format
    (`%p1%f{eprint}[.]`); every other entry against `format_spec` (a
    format pattern, or `None` to fall back to the configured
    `[auto_key]` format). The key conforms when
    {meth}`~bibdeskparser.Library.eval_format_spec` evaluates it to
    itself; a format that cannot be evaluated at all (e.g. a per-type
    format with no entry for the entry's type) is reported as such."""
    key = entry.key
    if _entry_preprint(entry, active.preprint_archives) is not None:
        spec = _PREPRINT_KEY_SPEC
    else:
        spec = format_spec
    try:
        generated = library.eval_format_spec(key, spec)
    except ValueError as exc:
        reason = str(exc)
        # the problem line already says what failed, so drop the
        # "cannot generate ..." lead-in of the underlying error
        prefix = "cannot generate a citation key: "
        if reason.startswith(prefix):
            reason = reason[len(prefix) :]
        return [
            Problem(
                "key_format",
                key,
                f"cannot evaluate citation-key format: {reason}",
            )
        ]
    if generated != key:
        return [
            Problem(
                "key_format",
                key,
                "does not match the citation-key format "
                f"(would be {generated!r})",
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
