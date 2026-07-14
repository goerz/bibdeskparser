"""Importing sanitized BibTeX entries into a `Library`.

Provides {func}`import_entries`, the free function backing
{meth}`bibdeskparser.Library.import_bibtex` (and, indirectly,
{meth}`bibdeskparser.Library.add`): parse a BibTeX snippet, sanitize
and normalize every entry in it, and add the entries to a library.

The overall flow is *validate-then-commit*: the snippet is parsed and
every entry is staged and validated first, collecting *all* problems;
only if there are none is the library mutated. A failed import
therefore leaves the library untouched.
"""

import datetime
import re
import warnings

import bibtexparser

from .bdskfile import BibDeskFile
from .config import active
from .editing import _failed_block_problems, _is_bare
from .entry import (
    _BDSK_FILE_RE,
    _BDSK_URL_RE,
    _DATE_FORMAT,
    Entry,
    _split_keywords,
    _strip_enclosing,
)
from .macros import (
    MacroString,
    ValueString,
    is_valid_macro_name,
    normalize_macro_name,
)
from .specifiers import (
    _acronym,
    compile_format,
    missing_required_fields,
    render_format,
)
from .texmap import detexify, skip_texify

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["import_entries"]

#: The literal pseudo-journal of an arXiv preprint, e.g.
#: `journal = {arXiv:2205.15044}`. Such a journal stays a literal value
#: (it is not converted to an `@string` macro).
_ARXIV_JOURNAL_RX = re.compile(r"^arXiv:(\S+)$")

_ARXIV_VERSION_RX = re.compile(r"v\d+$")

#: A page range, with any of the dash conventions found in publisher
#: data (hyphen, `--`, `---`, en-dash, em-dash).
_PAGE_RANGE_RX = re.compile(r"^(\w+)\s*(?:-{1,3}|–|—{1,2})\s*(\w+)$")

_DOI_PREFIX_RX = re.compile(
    r"^(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:)", re.IGNORECASE
)

#: Fields dropped from an imported `@article`: publisher BibTeX
#: routinely includes them, but they are not needed to render an
#: article with any modern bibliography style.
_ARTICLE_JUNK_FIELDS = frozenset(
    ("month", "day", "publisher", "address", "numpages", "issn")
)

#: Fields whose values are single-line by nature: runs of whitespace
#: (including line breaks from wrapped BibTeX source) collapse to a
#: single space.
_SINGLE_LINE_FIELDS = ("title", "author", "editor", "journal", "booktitle")

#: Words that stay lowercase in an English title-case title (only words
#: longer than 3 letters matter for `_detect_title_case`).
_TITLE_LC_WORDS = frozenset(
    """from into like near once onto about over than that till upon with
    when""".split()
)

# https://stackoverflow.com/questions/7609880
_RX_PROPER_NOUNS = re.compile(
    r"""
    (?<!^)                  # Do not match at beginning of string
    (?<![:.?!]\s)           # Ignore at beginning of sentence
    (?<!\{)                 # Ignore words already protected
    \b                      # Word boundary (\w -> \W)
    (\w*[A-Z]\w*)           # Word containing a capital letter
    (\b|$)                  # Word boundary (\w -> \W)
    (?!\})                  # Ignore words already protected
    """,
    re.X,
)

#: Built-in per-type citation-key formats, used when no `[auto_key]`
#: format is configured. `%p` (author-or-editor) rather than `%a` keeps
#: editor-only entries (edited books etc.) keyable. The journal acronym
#: includes short words (`0`), so that `Phys. Rev. A` gives `PRA`; the
#: booktitle acronym skips them (default small-word length), so that
#: `Advances in Atomic, Molecular, and Optical Physics` gives `AAMOP`.
_DEFAULT_KEY_SPECS = {
    "article": "%p1%c{journal}0%Y%u0",
    "inproceedings": "%p1%c{booktitle}%Y%u0",
    "conference": "%p1%c{booktitle}%Y%u0",
    "incollection": "%p1%c{booktitle}%Y%u0",
    "": "%p1%Y%u0",
}

#: The citation-key format for arXiv preprints (entries with a literal
#: `arXiv:...` journal), e.g. `Goerz2205.15044`. The `[.]` argument
#: maps the `/` of old-style arXiv identifiers (`quant-ph/0106057`) to
#: a `.`. Applied regardless of any configured `[auto_key]` format: the
#: format language has no conditionals, so a format configured for
#: published articles would derive nonsense from the pseudo-journal.
_ARXIV_KEY_SPEC = "%p1%f{eprint}[.]"


# -- pure value normalization ------------------------------------------ #


def _normalize_doi(value):
    """Normalize a `doi` field value: strip any `https://doi.org/`,
    `dx.doi.org`, or `doi:` prefix, and lowercase (DOIs are defined to
    be case-insensitive)."""
    return _DOI_PREFIX_RX.sub("", value.strip()).lower()


def _normalize_pages(value, entry_type):
    """Normalize a `pages` field value.

    For an `@article`, a page range collapses to its first page (the
    style of modern article identifiers); for any other type, the
    range's dash is normalized to `--`."""
    match = _PAGE_RANGE_RX.match(value.strip())
    if match is None:
        return value.strip()
    if entry_type == "article":
        return match.group(1)
    return match.group(1) + "--" + match.group(2)


def _fix_name_case(value):
    """Title-case every name in an all-uppercase `author`/`editor`
    value (the result is not guaranteed to be perfect, e.g. for
    `McDonald`-style names)."""
    return " and ".join(part.title() for part in value.split(" and "))


def _rx_word(word):
    """Regex matching `word` when it is not at the beginning of the
    string and not already brace-protected."""
    return re.compile(r"(?<!^)(?<!\{)\b" + re.escape(word) + r"\b(?!\})")


def _detect_title_case(title, protected_words):
    """Heuristically detect whether `title` uses (English) title case.

    Counts title-cased vs. lowercase words (ignoring the first word,
    short words, `_TITLE_LC_WORDS`, and `protected_words`); the title
    is title-case when the former outnumber the latter and there are
    more than two of them."""
    lowercase_count = 0
    titlecase_count = 0
    for word in title.split()[1:]:
        if (
            len(word) > 3
            and word.lower() not in _TITLE_LC_WORDS
            and word not in protected_words
        ):
            if word.capitalize() == word:
                titlecase_count += 1
            else:
                lowercase_count += 1
    return titlecase_count > lowercase_count and titlecase_count > 2


def _protect_title(title, protected_words):
    """Brace-protect capitalization in a `title` value.

    If the title looks like it is in sentence case (see
    `_detect_title_case`), every word containing a capital letter --
    other than at the beginning of the title or of a sentence -- is
    assumed to be a proper noun and is wrapped in braces. The
    `protected_words` (from the configuration) are wrapped in braces
    in any title. Words that are already brace-protected are left
    alone."""
    if not _detect_title_case(title, protected_words):
        title = _RX_PROPER_NOUNS.sub(r"{\1}", title)
    for word in protected_words:
        title = _rx_word(word).sub("{" + word + "}", title)
    return title


def _decode_value(key, raw):
    """Decode a raw parsed field value (as from
    `bibtexparser.parse_string(text, parse_stack=[])`) into a
    {class}`MacroString` (bare macro-shaped value) or
    {class}`ValueString` (braced/quoted or other literal value,
    detexified to Unicode)."""
    if _is_bare(raw) and is_valid_macro_name(raw, normalized=False):
        return MacroString(normalize_macro_name(raw))
    inner = _strip_enclosing(raw)
    return ValueString(inner if skip_texify(key) else detexify(inner))


# -- journal macro resolution ------------------------------------------ #


def _journal_macro_name(name):
    """The `@string` macro name for a new journal macro: the
    `[initials.journal]` exception configured for `name`, if any, else
    the journal's acronym (the same rule the `%c{journal}` key
    specifier uses), lowercased."""
    initials = active.initials.get("journal", {}).get(name)
    if initials is None:
        initials = _acronym(name, 0)
    return initials.lower()


def _plan_config_macro(name, existing_strings, planned_strings):
    """If macro `name` is not yet defined but has a `[journal_macros]`
    configuration entry, plan its `@string` definition (using the
    configured canonical journal name)."""
    if name in existing_strings or name in planned_strings:
        return
    names = active.journal_macros.get(name)
    if names is not None:
        planned_strings[name] = names[0]


def _resolve_journal(name, existing_strings, planned_strings):
    """Resolve the journal `name` to an `@string` macro name.

    Tried in order: a library/planned macro whose value is `name`; a
    `[journal_macros]` configuration entry listing `name` (planning
    the macro's `@string` definition if needed); a newly created macro
    named by `_journal_macro_name` (planned, with a notice). Returns
    `(macro, problem, notice)` where exactly one of `macro` and
    `problem` is not `None`."""
    for strings in (existing_strings, planned_strings):
        for macro, value in strings.items():
            if value == name:
                return macro, None, None
    for macro, names in active.journal_macros.items():
        if name in names:
            if macro in existing_strings:
                if existing_strings[macro] not in names:
                    return (
                        None,
                        f"the journal macro {macro!r} configured for "
                        f"{name!r} is already defined as "
                        f"{existing_strings[macro]!r}",
                        None,
                    )
                return macro, None, None
            planned_strings.setdefault(macro, names[0])
            return macro, None, None
    macro = _journal_macro_name(name)
    if not is_valid_macro_name(macro, normalized=True):
        return (
            None,
            f"cannot derive an @string macro name for journal {name!r}; "
            "add a [journal_macros] entry to the configuration",
            None,
        )
    if macro in existing_strings or macro in planned_strings:
        taken = existing_strings.get(macro, planned_strings.get(macro))
        return (
            None,
            f"cannot create @string macro {macro!r} for journal "
            f"{name!r}: the name is already defined as {taken!r}",
            None,
        )
    planned_strings[macro] = name
    notice = (
        f"created new @string macro for journal: {macro} = {{{name}}}; "
        "verify the macro name, and consider abbreviating the journal "
        "name (or configure it in [journal_macros])"
    )
    return macro, None, notice


# -- staging ------------------------------------------------------------ #


def _planned_strings(parsed, existing_strings):
    """Collect the `@string` definitions of the parsed snippet that
    are new (to be defined in the library on commit), as a `dict`
    mapping macro name to (Unicode) value. A definition that matches
    an existing one is a no-op; a conflicting one is a problem."""
    planned = {}
    problems = []
    for string in parsed.strings:
        if not is_valid_macro_name(string.key, normalized=False):
            problems.append(f"invalid macro name: {string.key!r}")
            continue
        name = normalize_macro_name(string.key)
        value = detexify(_strip_enclosing(string.value))
        conflict = existing_strings.get(name, planned.get(name))
        if conflict is not None and conflict != value:
            problems.append(
                f"@string {name} = {{{value}}} conflicts with the "
                f"existing definition {name} = {{{conflict}}}"
            )
        elif conflict is None:
            planned[name] = value
    return planned, problems


def _resolve_files(file_items, library, label):
    """Resolve imported `bdsk-file-N` path values (in index order)
    into `BibDeskFile` objects, validating that each path exists
    relative to the library's `.bib` directory."""
    problems = []
    bdsk_files = []
    base_dir = None if library.path is None else library.path.parent
    for _, path in sorted(file_items):
        if path.startswith("YnBsaXN0"):  # a base64-encoded binary plist
            problems.append(
                f"entry {label}: bdsk-file-N holds BibDesk's binary "
                "attachment data; only plain file paths (as written by "
                "`export`) can be imported"
            )
        elif base_dir is None:
            problems.append(
                f"entry {label}: cannot attach linked file {path!r}: "
                "the library has no file path yet (save it first)"
            )
        elif not (base_dir / path).exists():
            problems.append(
                f"entry {label}: linked file does not exist: {path!r} "
                f"(relative to {base_dir})"
            )
        else:
            bdsk_files.append(
                BibDeskFile(
                    base_dir / path, relative_to=base_dir, must_exist=False
                )
            )
    return bdsk_files, problems


def _stage_entry(
    model_entry,
    library,
    existing_strings,
    planned_strings,
    notices,
    *,
    fix_uppercase,
):
    """Sanitize and normalize one parsed entry into a staged
    {class}`Entry` (not yet added to any library).

    Returns `(entry, problems)`; `entry` is `None` if there were any
    problems. Human-readable `notices` (to be emitted as warnings on
    commit) are appended to the passed-in list."""
    problems = []
    key = model_entry.key
    label = repr(key) if key else "<unnamed>"
    if not model_entry.entry_type:
        problems.append(f"entry {label}: missing entry type")
    if not key:
        problems.append("an entry is missing its citation key")
    if problems:
        return None, problems
    entry_type = model_entry.entry_type.lower()
    fields = {}
    keywords = ()
    url_items = []
    file_items = []
    date_added = None
    for field in model_entry.fields:
        lkey = field.key.lower()
        file_match = _BDSK_FILE_RE.match(lkey)
        url_match = _BDSK_URL_RE.match(lkey)
        if file_match:
            file_items.append(
                (int(file_match.group(1)), _strip_enclosing(field.value))
            )
        elif url_match:
            url_items.append(
                (int(url_match.group(1)), _strip_enclosing(field.value))
            )
        elif lkey == "date-added":
            date_added = _strip_enclosing(field.value)
        elif lkey == "date-modified":
            pass  # regenerated when the entry is added
        elif lkey == "keywords":
            keywords = _split_keywords(_strip_enclosing(field.value))
        else:
            fields[lkey] = _decode_value(lkey, field.value)
    for lkey in _SINGLE_LINE_FIELDS:
        value = fields.get(lkey)
        if isinstance(value, ValueString):
            fields[lkey] = ValueString(" ".join(str(value).split()))
    journal = fields.get("journal")
    arxiv_match = None
    if isinstance(journal, ValueString):
        arxiv_match = _ARXIV_JOURNAL_RX.match(str(journal))
    if arxiv_match:
        arxiv_id = _ARXIV_VERSION_RX.sub("", arxiv_match.group(1))
        fields.setdefault("eprint", ValueString(arxiv_id))
        fields.setdefault("archiveprefix", ValueString("arXiv"))
    doi = fields.get("doi")
    if isinstance(doi, ValueString):
        fields["doi"] = ValueString(_normalize_doi(str(doi)))
    if entry_type == "article":
        for lkey in _ARTICLE_JUNK_FIELDS:
            fields.pop(lkey, None)
        if "doi" in fields:
            fields.pop("url", None)
    pages = fields.get("pages")
    if isinstance(pages, ValueString):
        fields["pages"] = ValueString(_normalize_pages(str(pages), entry_type))
    journal = fields.get("journal")
    if isinstance(journal, MacroString):
        _plan_config_macro(str(journal), existing_strings, planned_strings)
    elif isinstance(journal, ValueString) and not arxiv_match:
        macro, problem, notice = _resolve_journal(
            str(journal), existing_strings, planned_strings
        )
        if problem is not None:
            problems.append(f"entry {label}: {problem}")
        else:
            fields["journal"] = MacroString(macro)
            if notice is not None:
                notices.append(notice)
    if fix_uppercase:
        for lkey in ("author", "editor"):
            value = fields.get(lkey)
            if isinstance(value, ValueString):
                fields[lkey] = ValueString(_fix_name_case(str(value)))
        title = fields.get("title")
        if isinstance(title, ValueString):
            fields["title"] = ValueString(str(title).capitalize())
    title = fields.get("title")
    if isinstance(title, ValueString):
        fields["title"] = ValueString(
            _protect_title(str(title), active.protected_words)
        )
    defined = set(existing_strings) | set(planned_strings)
    for lkey, value in fields.items():
        if isinstance(value, MacroString) and str(value) not in defined:
            problems.append(
                f"entry {label}: undefined macro {str(value)!r} "
                f"referenced by field {lkey!r}"
            )
    entry = None
    caught = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            entry = Entry(entry_type, key, fields=fields)
    except (ValueError, TypeError, KeyError) as exc:
        problems.append(f"entry {label}: {exc}")
    if entry is not None:
        notices.extend(f"entry {label}: {w.message}" for w in caught)
        # keywords/bdsk-url-N/bdsk-file-N/date-added are excluded from
        # the Entry dict interface, so they are restored through the
        # same internal accessors the editing module uses.
        # pylint: disable=protected-access
        if keywords:
            entry._set_keywords(keywords)
        if url_items:
            entry._set_urls(url for _, url in sorted(url_items))
        if file_items:
            bdsk_files, file_problems = _resolve_files(
                file_items, library, label
            )
            problems.extend(file_problems)
            if bdsk_files:
                entry._set_files(bdsk_files)
        if date_added is not None:
            try:
                datetime.datetime.strptime(date_added, _DATE_FORMAT)
            except ValueError:
                notices.append(
                    f"entry {label}: dropped unparseable date-added "
                    f"{date_added!r}"
                )
            else:
                entry._set_raw_field("date-added", "{" + date_added + "}")
    if problems:
        return None, problems
    return entry, []


# -- duplicate detection ------------------------------------------------ #


def _duplicate_problems(library, staged):
    """Problem strings for staged entries whose `doi` or `eprint`
    already identifies an entry in `library` (or an earlier entry of
    the same import)."""
    problems = []
    seen = {"doi": {}, "eprint": {}}
    normalize = {
        "doi": _normalize_doi,
        "eprint": lambda value: _ARXIV_VERSION_RX.sub("", value.strip()),
    }
    for key, entry in library.items():
        for field, index in seen.items():
            value = entry.get(field)
            if value:
                index.setdefault(normalize[field](str(value)), key)
    for incoming_key, entry in staged:
        for field, index in seen.items():
            value = entry.get(field)
            if not value:
                continue
            normalized = normalize[field](str(value))
            existing = index.setdefault(normalized, incoming_key)
            if existing != incoming_key:
                problems.append(
                    f"entry {incoming_key!r}: {field} {str(value)!r} "
                    f"is already in the library as entry {existing!r}"
                )
    return problems


# -- citation keys ------------------------------------------------------ #


def _key_format_spec(entry):
    """The citation-key format string for a staged `entry`: the arXiv
    preprint format for a literal `arXiv:...` journal, else the
    configured `[auto_key]` format (resolved per-type), else the
    built-in `_DEFAULT_KEY_SPECS`. Returns `(format_string, problem)`,
    exactly one of them not `None`."""
    journal = entry.get("journal")
    if journal is not None and _ARXIV_JOURNAL_RX.match(str(journal)):
        return _ARXIV_KEY_SPEC, None
    spec = active.auto_key.format_spec
    if spec is None:
        spec = _DEFAULT_KEY_SPECS
    if isinstance(spec, str):
        return spec, None
    if entry.entry_type in spec:
        return spec[entry.entry_type], None
    if "" in spec:
        return spec[""], None
    return None, (
        "cannot generate a citation key: the [auto_key] format_spec "
        f"has no entry for type {entry.entry_type!r} and no '' fallback"
    )


def _final_key(entry, incoming_key, taken, keep_keys, strings):
    """The citation key under which the staged `entry` will be added:
    `incoming_key` itself with `keep_keys`, else a key generated from
    `_key_format_spec` (keeping an incoming key that already matches
    the format). `taken` is the set of keys that are not available
    (the library's, and earlier staged entries'). Returns
    `(key, problems)`."""
    if keep_keys:
        if incoming_key in taken:
            return None, [
                f"entry {incoming_key!r}: the citation key is already "
                "in the library"
            ]
        return incoming_key, []
    format_string, problem = _key_format_spec(entry)
    if problem is not None:
        return None, [f"entry {incoming_key!r}: {problem}"]
    fmt = compile_format(format_string)
    missing = missing_required_fields(fmt, entry)
    if missing:
        return None, [
            f"entry {incoming_key!r}: cannot generate a citation key: "
            f"the format {format_string!r} requires the missing "
            f"field(s) {', '.join(sorted(missing))}"
        ]
    new_key = render_format(
        fmt,
        entry,
        strings=strings,
        initials=active.initials,
        lowercase=active.auto_key.lowercase,
        clean=active.auto_key.clean,
        current_key=incoming_key,
        is_free=lambda k: k not in taken,
    )
    # a format without a unique specifier (e.g. the arXiv preprint
    # format) can generate a key that is already taken
    if new_key in taken:
        return None, [
            f"entry {incoming_key!r}: the generated citation key "
            f"{new_key!r} is already in the library"
        ]
    if new_key == str(entry.get("crossref", "") or ""):
        return None, [
            f"entry {incoming_key!r}: the generated key {new_key!r} "
            "would equal the entry's own crossref"
        ]
    return new_key, []


# -- the import entry point --------------------------------------------- #


def import_entries(library, text, *, keep_keys=False, fix_uppercase=False):
    """Parse the BibTeX snippet `text`, sanitize and normalize every
    entry in it, and add the entries to `library`; backs
    {meth}`bibdeskparser.Library.import_bibtex` (see there for the
    user-facing documentation of the sanitization steps).

    Returns the list of citation keys of the added entries, in
    snippet order. Raises {exc}`ValueError` with a list of *all*
    validation problems if anything about the snippet is not
    acceptable; the library is guaranteed unmodified in that case.
    Does not save the library."""
    try:
        parsed = bibtexparser.parse_string(text, parse_stack=[])
    except Exception as exc:  # pylint: disable=broad-except
        raise ValueError(f"parse error: {exc}") from exc
    problems = _failed_block_problems(parsed)
    if not parsed.entries and not problems:
        raise ValueError("no entries found in the imported text")
    existing_strings = dict(library.strings)
    planned_strings, string_problems = _planned_strings(
        parsed, existing_strings
    )
    problems.extend(string_problems)
    notices = []
    staged = []
    for model_entry in parsed.entries:
        entry, entry_problems = _stage_entry(
            model_entry,
            library,
            existing_strings,
            planned_strings,
            notices,
            fix_uppercase=fix_uppercase,
        )
        problems.extend(entry_problems)
        if entry is not None:
            staged.append((model_entry.key, entry))
    problems.extend(_duplicate_problems(library, staged))
    all_strings = {**existing_strings, **planned_strings}
    taken = set(library)
    final = []
    for incoming_key, entry in staged:
        key, key_problems = _final_key(
            entry, incoming_key, taken, keep_keys, all_strings
        )
        problems.extend(key_problems)
        if key is not None:
            taken.add(key)
            final.append((key, entry))
    if problems:
        raise ValueError("Validation failed:\n" + "\n".join(problems))
    # -- commit (nothing above may have modified the library) -------- #
    referenced = {
        str(value)
        for _, entry in final
        for value in entry.values()
        if isinstance(value, MacroString)
    }
    for name, value in planned_strings.items():
        if name in referenced:
            library.strings[name] = value
    keys = []
    for key, entry in final:
        library[key] = entry
        keys.append(key)
    for notice in notices:
        warnings.warn(notice, UserWarning, stacklevel=3)
    return keys
