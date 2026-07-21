"""Standing audits backing the `check` CLI command.

Pure inspection of a loaded {class}`bibdeskparser.Library`: each
function returns {class}`Problem` records and never modifies the
library. The CLI command turns the records into a report and a
pass/fail exit code.
"""

from collections import namedtuple

from bibtexparser.model import DuplicateBlockKeyBlock

from .config import active
from .identifiers import _entry_preprint, _preprint_journal
from .library import _bare_macro_fields, _field_state
from .macros import MacroString

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["Problem", "collect_problems"]


#: One audit finding. `check` names the audit (`"parse"`,
#: `"duplicate_keys"`, `"doi"`, `"journal"`, `"names"`, or
#: `"unused_strings"`), `key` is the citation key the problem is tied
#: to (`None` for a problem that concerns the file as a whole), and
#: `message` describes the problem.
Problem = namedtuple("Problem", ["check", "key", "message"])


def collect_problems(library, keys=None):
    """Every standing-audit problem in `library`, as a `list` of
    {class}`Problem`.

    Without `keys`, all audits run over the entire library. With
    `keys` (an iterable of citation keys, all of which must exist in
    `library`), the doi, journal, and names audits cover only those
    entries, the duplicate-keys audit reports only those keys, and
    the unused-macros audit is skipped; problems parsing the file
    itself are always included.
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
    for entry in entries:
        problems += _entry_problems(entry, library)
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
    """The doi, journal, and names problems of a single `entry`."""
    problems = []
    archives = active.preprint_archives
    is_preprint = _entry_preprint(entry, archives) is not None
    if (
        entry.entry_type.lower() == "article"
        and not is_preprint
        and _field_state(entry, "doi") == "missing"
    ):
        problems.append(Problem("doi", entry.key, "missing doi"))
    if "journal" in entry:
        problems += _journal_problems(entry, library, archives)
    for field in ("author", "editor"):
        if field in entry:
            try:
                getattr(entry, field)
            except Exception as exc:  # pylint: disable=broad-except
                problems.append(
                    Problem(
                        "names",
                        entry.key,
                        f"{field} does not parse as names: {exc}",
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
