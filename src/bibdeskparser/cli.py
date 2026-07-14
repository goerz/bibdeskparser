"""Command-line interface (the `bibdeskparser` console script).

Every subcommand operates on a single `.bib` file, given as the first
argument after the subcommand name (`bibdeskparser <command> [BIBFILE]
<args>`). An argument counts as the bibfile exactly if it does not
start with `-` and ends in `.bib` (case-insensitive); otherwise the
bibfile is taken from the `default_bib_file` key of the discovered
`bibdeskparser.toml` (see {mod}`bibdeskparser.config`).

The commands map directly onto the {class}`bibdeskparser.Library` API:
read-only commands print data (optionally as JSON, via `--json`);
mutating commands load the library, apply one change, and save it back
in place.
"""

import json
import sys
import warnings
from pathlib import Path

import click

from . import __version__, config
from .editing import strings_bib_text
from .library import Library, StaleFileError
from .macros import MacroString, ValueString

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "main",
    "keys",
    "show",
    "fields",
    "get_field",
    "author",
    "editor",
    "search",
    "groups",
    "keywords",
    "strings",
    "duplicate_keys",
    "timestamp",
    "render",
    "export",
    "eval_format_spec",
    "rekey",
    "delete",
    "set_type",
    "set_field",
    "delete_field",
    "add_to_group",
    "remove_from_group",
    "set_group",
    "delete_group",
    "set_string",
    "delete_string",
    "rename_string",
    "add_to_keyword",
    "remove_from_keyword",
    "add_file",
    "replace_file",
    "unlink_file",
    "rename_file",
    "add_url",
    "replace_url",
    "remove_url",
    "edit",
    "edit_strings",
    "import_bibtex",
    "add",
]

# Exceptions raised by the `Library` API for invalid user input; the
# CLI converts these into clean one-line error messages (exit code 1).
# `NotImplementedError` covers recognized-but-unsupported format
# specifiers (`%i`) in `rekey --format-spec` patterns.
_API_ERRORS = (
    KeyError,
    ValueError,
    FileNotFoundError,
    FileExistsError,
    StaleFileError,
    NotImplementedError,
)


def _error_message(exc):
    """A one-line message for an API exception.

    `KeyError` stringifies to the `repr` of its argument (quotes
    included), so use the bare argument instead.
    """
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _fail_unknown_keys(keys):
    """Fail cleanly, naming the unknown citation `keys` (a list)."""
    if len(keys) == 1:
        raise click.ClickException(f"unknown citation key {keys[0]!r}")
    listed = ", ".join(repr(key) for key in keys)
    raise click.ClickException(f"unknown citation keys: {listed}")


def _check_keys(lib, keys):
    """Fail cleanly for any of `keys` not a citation key in `lib`."""
    unknown = [key for key in keys if key not in lib]
    if unknown:
        _fail_unknown_keys(unknown)


def _entry(lib, key):
    """`lib[key]`, failing cleanly if `key` is not in `lib`."""
    if key not in lib:
        _fail_unknown_keys([key])
    return lib[key]


def _check_group(lib, name):
    """Fail cleanly if no static group `name` exists in `lib`."""
    if name not in lib.groups:
        raise click.ClickException(f"unknown static group {name!r}")


def _check_string(lib, name):
    """Fail cleanly if no `@string` macro `name` is defined in `lib`."""
    if name not in lib.strings:
        raise click.ClickException(f"unknown @string macro {name!r}")


def _default_bibfile(ctx):
    """The bibfile from `default_bib_file` in the discovered config.

    Discovery is relative to the current working directory (or the XDG
    location); fails with a usage error if no `default_bib_file` is
    configured.
    """
    try:
        config.active.load()
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    bibfile = config.active.default_bib_file
    if bibfile is None:
        raise click.UsageError(
            "no BIBFILE given, and no 'default_bib_file' is configured "
            "in bibdeskparser.toml; pass a .bib file as the first "
            "argument, or set 'default_bib_file'",
            ctx=ctx,
        )
    return bibfile


class _BibCommand(click.Command):
    """A `click.Command` operating on a `.bib` file.

    Resolves the bibfile (see the module docstring) into `ctx.obj` (a
    `Path`), makes `[BIBFILE]` show up in the usage line, and converts
    `Library` API errors into clean one-line `click` errors.
    """

    def parse_args(self, ctx, args):
        ctx.obj = None
        if (
            args
            and not args[0].startswith("-")
            and args[0].lower().endswith(".bib")
        ):
            ctx.obj = Path(args[0])
            args = args[1:]
        return super().parse_args(ctx, args)

    def collect_usage_pieces(self, ctx):
        return ["[BIBFILE]", *super().collect_usage_pieces(ctx)]

    def invoke(self, ctx):
        if ctx.obj is None:
            # Deferred from parse_args so that `--help` (handled
            # there, by its eager callback) works without a bibfile.
            ctx.obj = _default_bibfile(ctx)
        if not ctx.obj.is_file():
            raise click.ClickException(f"bibfile not found: {ctx.obj}")
        try:
            return super().invoke(ctx)
        except _API_ERRORS as exc:
            raise click.ClickException(_error_message(exc)) from exc


_json_option = click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the data as JSON instead of human-readable text.",
)


def _emit(data, as_json, text):
    """Print `data` as JSON if `as_json`, else print `text` (if any)."""
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    elif text:
        click.echo(text)


def _echo_block(text):
    """Print multi-line `text` without adding a trailing blank line."""
    click.echo(text, nl=not text.endswith("\n"))


def _isoformat(stamp):
    """`stamp.isoformat()`, or `None` if `stamp` is `None`."""
    return stamp.isoformat() if stamp is not None else None


def _examples(*lines):
    """An "Examples:" help epilog from example invocations.

    Each element of `lines` is one example (embedded newlines allowed,
    for shell line continuations). The leading `\\b` marker (ASCII
    backspace) keeps `click` from re-wrapping the block. A note about
    the `default_bib_file` assumption of the examples is appended.
    """
    text = "\n".join(lines).replace("\n", "\n  ")
    return (
        f"\b\nExamples:\n  {text}\n\n"
        "The examples assume that a discovered `bibdeskparser.toml` "
        "sets `default_bib_file`. Without that, every command takes "
        "the path to the `.bib` file as its first argument, e.g. "
        "`bibdeskparser keys library.bib`."
    )


@click.group(
    epilog=_examples(
        "bibdeskparser keys     # list all citation keys",
        "bibdeskparser keys --type article --missing doi",
        'bibdeskparser search "quantum computing"',
        "bibdeskparser show Preskill2018 --json",
        "bibdeskparser get_field Preskill2018 title",
        "bibdeskparser set_field Preskill2018 doi 10.1234/xyz",
        "bibdeskparser add_to_keyword NISQ Preskill2018",
        "bibdeskparser add_file Preskill2018 papers/nisq.pdf",
        "bibdeskparser export Preskill2018  # entry as BibTeX",
        "bibdeskparser render Preskill2018  # formatted citation",
        "bibdeskparser add 10.1103/PhysRevA.89.032334  # by DOI",
        "pbpaste | bibdeskparser import --stdin",
    )
)
@click.version_option(version=__version__)
def main():
    """Command-line interface for BibDesk `.bib` databases.

    Every command takes the `.bib` file to operate on as its first
    argument (any argument ending in `.bib`). If omitted, the file
    named by the `default_bib_file` key of a discovered
    `bibdeskparser.toml` is used instead.

    Read-only commands (`keys`, `show`, `fields`, `get_field`,
    `author`, `editor`, `search`, `groups`, `keywords`, `strings`,
    `duplicate_keys`, `timestamp`, `eval_format_spec`) print to stdout
    and accept `--json` for machine-readable output; `render` and
    `export` are read-only as well. The other commands modify the
    `.bib` file in place and print nothing on success (except `rekey`
    without NEW_KEY and `rename_file` without NEW, which print the
    generated key or file path, as does `add_file` when it auto-files;
    `import` and `add` print the citation keys of the added entries,
    and `add --dry-run` only prints the fetched entry, without
    modifying the file).
    On any error they print `Error: <message>` to stderr and exit
    non-zero (2 for bad usage, 1 for a library error such as an unknown
    key or a `.bib` file changed on disk since it was read). Run
    `bibdeskparser COMMAND --help` for a command's arguments.
    """


# -- read-only commands ------------------------------------------------ #


def _field_state(entry, name):
    """One of `"missing"`, `"empty"`, or `"has"` for field `name`.

    A field is "missing" if not defined on the entry at all, "empty"
    if defined with an empty (or whitespace-only) value, and "has"
    otherwise.
    """
    try:
        value = entry[name]
    except KeyError:
        return "missing"
    return "has" if str(value).strip() else "empty"


@main.command(
    name="keys",
    cls=_BibCommand,
    short_help="List citation keys, optionally filtered.",
    epilog=_examples(
        "bibdeskparser keys",
        "bibdeskparser keys --type article --type book",
        "bibdeskparser keys --missing doi --json",
        "bibdeskparser keys --has eprint --empty abstract",
    ),
)
@click.option(
    "--type",
    "types",
    multiple=True,
    metavar="TYPE",
    help=(
        "Keep only entries of this type, e.g. 'article' "
        "(case-insensitive; repeatable, an entry may match any of "
        "the given types)."
    ),
)
@click.option(
    "--has",
    "has_fields",
    multiple=True,
    metavar="FIELD",
    help=(
        "Keep only entries where FIELD is defined with a non-empty "
        "value (repeatable)."
    ),
)
@click.option(
    "--missing",
    "missing_fields",
    multiple=True,
    metavar="FIELD",
    help=(
        "Keep only entries where FIELD is not defined at all "
        "(repeatable). A defined-but-empty FIELD does not count as "
        "missing; see --empty."
    ),
)
@click.option(
    "--empty",
    "empty_fields",
    multiple=True,
    metavar="FIELD",
    help=(
        "Keep only entries where FIELD is defined, but with an empty "
        "value (repeatable)."
    ),
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def keys(bibfile, types, has_fields, missing_fields, empty_fields, as_json):
    """List citation keys, one per line.

    Without options, list every entry in the library. The options
    narrow the list; an entry is listed if it matches one of the
    --type values (if any are given) and satisfies every --has,
    --missing, and --empty filter. For any FIELD, exactly one of
    --has, --missing, and --empty holds: a field that is defined but
    empty is neither "missing" nor "has". Field names are
    case-insensitive.
    """
    lib = Library(bibfile)
    types = {t.lower() for t in types}
    required = [("has", name) for name in has_fields]
    required += [("missing", name) for name in missing_fields]
    required += [("empty", name) for name in empty_fields]
    data = []
    for key in lib:
        entry = lib[key]
        if types and entry.entry_type.lower() not in types:
            continue
        if all(_field_state(entry, name) == state for state, name in required):
            data.append(key)
    _emit(data, as_json, "\n".join(data))


def _selected_field_values(entry, names):
    """`{canonical_name: value}` for the `names` present on `entry`.

    Field names match case-insensitively; the result keeps the order
    in which `names` were requested, dropping any not defined on the
    entry.
    """
    lookup = {name.lower(): name for name in dict(entry)}
    result = {}
    for name in names:
        canonical = lookup.get(name.lower())
        if canonical is not None:
            result[canonical] = entry[canonical]
    return result


def _entry_data(entry, only_fields=None):
    """The JSON-ready data for `entry` (a dict).

    With `only_fields` (a list of field names), the result is just a
    map of those fields (that are defined) to their values; otherwise
    it is the full record (type, key, fields, and derived data).
    """
    if only_fields is not None:
        return {
            name: str(value)
            for name, value in _selected_field_values(
                entry, only_fields
            ).items()
        }
    return {
        "entry_type": entry.entry_type,
        "key": entry.key,
        "fields": dict(entry),
        "groups": list(entry.groups),
        "keywords": list(entry.keywords),
        "files": list(entry.files),
        "urls": list(entry.urls),
        "date_added": _isoformat(entry.date_added),
        "date_modified": _isoformat(entry.date_modified),
    }


def _entry_block(entry, only_fields=None):
    """A human-readable multi-line block describing `entry`.

    With `only_fields`, only the `KEY (type)` heading and the named
    fields (that are defined) are shown, without the derived data.
    """
    lines = [f"{entry.key} ({entry.entry_type})"]
    if only_fields is not None:
        field_values = _selected_field_values(entry, only_fields)
    else:
        field_values = dict(entry)
    width = max((len(name) for name in field_values), default=0)
    for name, value in field_values.items():
        lines.append(f"    {(name + ':').ljust(width + 1)} {value}")
    if only_fields is not None:
        return "\n".join(lines)
    derived = [
        ("groups", ", ".join(entry.groups)),
        ("keywords", ", ".join(entry.keywords)),
        ("files", ", ".join(entry.files)),
        ("urls", ", ".join(entry.urls)),
        ("date added", _isoformat(entry.date_added)),
        ("date modified", _isoformat(entry.date_modified)),
    ]
    derived = [(name, value) for (name, value) in derived if value]
    width = max((len(name) for name, _ in derived), default=0)
    for name, value in derived:
        lines.append(f"  {(name + ':').ljust(width + 1)} {value}")
    return "\n".join(lines)


def _read_key_lines(source):
    """Citation keys read from `source`, one per line (blanks skipped).

    `source` is a file path, or `-` to read from standard input.
    """
    if source == "-":
        text = sys.stdin.read()
    else:
        text = Path(source).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _split_field_names(field_args):
    """The field names from a repeatable, comma-separated `--field`.

    Returns an order-preserving, de-duplicated list, or `None` if no
    `--field` was given (i.e. show every field).
    """
    if not field_args:
        return None
    names = []
    for item in field_args:
        names += [part.strip() for part in item.split(",") if part.strip()]
    return list(dict.fromkeys(names))


@main.command(
    name="show",
    cls=_BibCommand,
    short_help="Show the full data of the given entries.",
    epilog=_examples(
        "bibdeskparser show Preskill2018",
        "bibdeskparser show Preskill2018 --json",
        "bibdeskparser show Key1 Key2 --field doi,title --json",
        "bibdeskparser keys --missing eprint \\\n"
        "    | bibdeskparser show --field doi --skip-missing --keys-from -",
    ),
)
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@click.option(
    "--field",
    "field_args",
    multiple=True,
    metavar="FIELD",
    help=(
        "Show only these fields (case-insensitive) instead of the "
        "full record; repeatable and comma-separated (e.g. "
        "--field doi,title). A field not defined on an entry is "
        "silently omitted for that entry."
    ),
)
@click.option(
    "--skip-missing",
    is_flag=True,
    help=(
        "Report unknown citation keys on stderr and show the rest, "
        "instead of aborting the whole command on the first one."
    ),
)
@click.option(
    "--keys-from",
    "keys_from",
    metavar="FILE",
    default=None,
    help=(
        "Read additional citation keys from FILE (one per line; '-' "
        "for standard input), appended to any KEY arguments."
    ),
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def show(bibfile, citekeys, field_args, skip_missing, keys_from, as_json):
    """Show the data of the entries with the given keys.

    Keys come from the KEY arguments and/or --keys-from; at least one
    is required. By default every field and the derived data (groups,
    keywords, files, URLs, dates) are shown; --field narrows this to
    the named fields. An unknown key aborts the command unless
    --skip-missing is given, in which case it is reported on stderr
    and the remaining entries are still shown.
    """
    lib = Library(bibfile)
    keys = list(citekeys)
    if keys_from is not None:
        keys += _read_key_lines(keys_from)
    keys = list(dict.fromkeys(keys))
    if not keys:
        raise click.UsageError(
            "no citation keys given; pass KEY... and/or --keys-from"
        )
    only_fields = _split_field_names(field_args)
    entries = [lib[key] for key in keys if key in lib]
    missing = [key for key in keys if key not in lib]
    if missing and not skip_missing:
        _fail_unknown_keys(missing)
    for key in missing:
        click.echo(f"Warning: unknown citation key {key!r}", err=True)
    data = {entry.key: _entry_data(entry, only_fields) for entry in entries}
    text = "\n\n".join(_entry_block(entry, only_fields) for entry in entries)
    _emit(data, as_json, text)


@main.command(
    name="fields",
    cls=_BibCommand,
    short_help="List the fields defined on an entry.",
    epilog=_examples(
        "bibdeskparser fields Preskill2018",
        "bibdeskparser fields Preskill2018 --json",
    ),
)
@click.argument("citekey", metavar="KEY")
@_json_option
@click.pass_obj
def fields(bibfile, citekey, as_json):
    """List the names of the fields defined on the entry with the
    given KEY, one per line.

    This covers the normal BibTeX fields, including 'keywords', but
    not the internal date and 'bdsk-*' fields; use `show` for a
    complete view of an entry."""
    data = list(_entry(Library(bibfile), citekey))
    _emit(data, as_json, "\n".join(data))


@main.command(
    name="get_field",
    cls=_BibCommand,
    short_help="Print the value of one field of an entry.",
    epilog=_examples(
        "bibdeskparser get_field Preskill2018 title",
        "bibdeskparser get_field Preskill2018 journal",
    ),
)
@click.argument("citekey", metavar="KEY")
@click.argument("fieldname")
@_json_option
@click.pass_obj
def get_field(bibfile, citekey, fieldname, as_json):
    """Print the value of the field FIELDNAME (case-insensitive) of
    the entry with the given KEY.

    A field whose value is a reference to an `@string` macro prints
    as the bare macro name (see `strings` for the definitions). Fails
    for a field not defined on the entry (see `fields`)."""
    entry = _entry(Library(bibfile), citekey)
    if fieldname not in entry:
        raise KeyError(f"entry {citekey!r} has no field {fieldname!r}")
    data = str(entry[fieldname])
    _emit(data, as_json, data)


def _names_data(names):
    """The JSON-ready data for a list of structured names."""
    return [
        {
            "first": name.first,
            "von": name.von,
            "last": name.last,
            "jr": name.jr,
        }
        for name in names
    ]


def _names_text(names):
    """One name per line, in last-name-first form."""
    return "\n".join(name.merge_last_name_first for name in names)


@main.command(
    name="author",
    cls=_BibCommand,
    short_help="Show an entry's authors as structured names.",
    epilog=_examples(
        "bibdeskparser author NielsenChuangBook",
        "bibdeskparser author NielsenChuangBook --json",
    ),
)
@click.argument("citekey", metavar="KEY")
@_json_option
@click.pass_obj
def author(bibfile, citekey, as_json):
    """Show the authors of the entry with the given KEY as structured
    names, one per line, in last-name-first form ("von Last, Jr,
    First"). With --json: an array of objects with "first", "von",
    "last", and "jr" keys, each a list of name words. Prints nothing
    (an empty array, with --json) for an entry without an 'author'
    field."""
    names = _entry(Library(bibfile), citekey).author
    _emit(_names_data(names), as_json, _names_text(names))


@main.command(
    name="editor",
    cls=_BibCommand,
    short_help="Show an entry's editors as structured names.",
    epilog=_examples(
        "bibdeskparser editor NielsenChuangBook",
        "bibdeskparser editor NielsenChuangBook --json",
    ),
)
@click.argument("citekey", metavar="KEY")
@_json_option
@click.pass_obj
def editor(bibfile, citekey, as_json):
    """Show the editors of the entry with the given KEY as structured
    names, one per line, in last-name-first form ("von Last, Jr,
    First"). With --json: an array of objects with "first", "von",
    "last", and "jr" keys, each a list of name words. Prints nothing
    (an empty array, with --json) for an entry without an 'editor'
    field."""
    names = _entry(Library(bibfile), citekey).editor
    _emit(_names_data(names), as_json, _names_text(names))


@main.command(
    name="search",
    cls=_BibCommand,
    short_help="List the keys of entries matching QUERY.",
    epilog=_examples(
        'bibdeskparser search "quantum computing"',
        "bibdeskparser search Schroedinger --field author",
        "bibdeskparser search '^10\\.1103/' " "--field doi --match regex",
    ),
)
@click.argument("query")
@click.option(
    "--field",
    "field_names",
    multiple=True,
    metavar="FIELD",
    help=(
        "Limit the search to this field (repeatable). The special "
        "name 'key' matches against the citation key."
    ),
)
@click.option(
    "--match",
    "match_",
    type=click.Choice(["exact", "folded", "words", "fuzzy", "regex"]),
    default="words",
    show_default=True,
    help="The match strictness (see the command's help for details).",
)
@_json_option
@click.pass_obj
def search(bibfile, query, field_names, match_, as_json):
    """List the keys of the entries matching QUERY, best match first,
    one per line.

    The query is matched against the raw field values (bare `@string`
    macro names intact), their decoded Unicode form, and macro
    expansions. --field limits the search to specific fields.

    --match sets the strictness. The first four levels form a ladder
    -- each matches everything looser levels do, plus more -- and are
    case-insensitive:

    \b
    - exact:  the query occurs verbatim (up to case) as a substring.
    - folded: additionally ignores accents ("Schrodinger" and
              "Schroedinger" both match "Schrödinger").
    - words:  (the default) additionally matches when most of the
              query's words occur in a field, in any order -- good for
              a half-remembered title.
    - fuzzy:  additionally tolerates small typos: two words match when
              ~80% of their letters agree, and >=70% of the query's
              words must match. It casts the widest net and can return
              surprising hits, so treat its results as candidates to
              verify, not exact answers.
    - regex:  the query is a regular expression (standard `re`
              semantics, case-sensitive unless it starts with "(?i)");
              an invalid pattern is an error. Not part of the ladder.
    """
    lib = Library(bibfile)
    entries = lib.search(query, fields=field_names or None, match=match_)
    data = [entry.key for entry in entries]
    _emit(data, as_json, "\n".join(data))


@main.command(
    name="groups",
    cls=_BibCommand,
    short_help="List all static groups, or the groups of entry KEY.",
    epilog=_examples(
        "bibdeskparser groups   # all groups and members",
        "bibdeskparser groups Preskill2018  # entry's groups",
    ),
)
@click.argument("citekey", metavar="[KEY]", required=False)
@_json_option
@click.pass_obj
def groups(bibfile, citekey, as_json):
    """Without KEY, list all static groups and the keys they contain.
    With KEY, list the names of the groups the entry with that key
    belongs to, one per line."""
    lib = Library(bibfile)
    if citekey is not None:
        data = list(_entry(lib, citekey).groups)
        _emit(data, as_json, "\n".join(data))
        return
    data = {name: list(group_keys) for name, group_keys in lib.groups.items()}
    text = "\n".join(
        f"{name}: {', '.join(group_keys)}" for name, group_keys in data.items()
    )
    _emit(data, as_json, text)


@main.command(
    name="keywords",
    cls=_BibCommand,
    short_help="List all keywords, or the keywords of entry KEY.",
    epilog=_examples(
        "bibdeskparser keywords   # all keywords and users",
        "bibdeskparser keywords Preskill2018",
    ),
)
@click.argument("citekey", metavar="[KEY]", required=False)
@_json_option
@click.pass_obj
def keywords(bibfile, citekey, as_json):
    """Without KEY, list all keywords and the keys of the entries
    using them. With KEY, list the keywords of the entry with that
    key, one per line."""
    lib = Library(bibfile)
    if citekey is not None:
        data = list(_entry(lib, citekey).keywords)
        _emit(data, as_json, "\n".join(data))
        return
    data = {
        keyword: list(kw_keys) for keyword, kw_keys in lib.keywords.items()
    }
    text = "\n".join(
        f"{keyword}: {', '.join(kw_keys)}" for keyword, kw_keys in data.items()
    )
    _emit(data, as_json, text)


@main.command(
    name="strings",
    cls=_BibCommand,
    epilog=_examples(
        "bibdeskparser strings",
        "bibdeskparser strings --bib  # @string{...} lines",
    ),
)
@click.option(
    "--bib",
    "as_bib",
    is_flag=True,
    help=(
        "Print the definitions as re-parseable `@string{name = "
        "{value}}` lines, sorted by name: the exact baseline text for "
        "`edit_strings --stdin`."
    ),
)
@_json_option
@click.pass_obj
def strings(bibfile, as_bib, as_json):
    """List all @string macro definitions."""
    if as_bib and as_json:
        raise click.UsageError("--bib and --json are mutually exclusive")
    data = dict(Library(bibfile).strings)
    if as_bib:
        text = strings_bib_text(data)
        if text:
            _echo_block(text)
        return
    text = "\n".join(f"{name} = {value}" for name, value in data.items())
    _emit(data, as_json, text)


@main.command(
    name="duplicate_keys",
    cls=_BibCommand,
    short_help="List citation keys that occur more than once.",
    epilog=_examples(
        "bibdeskparser duplicate_keys",
        "bibdeskparser duplicate_keys --json",
    ),
)
@_json_option
@click.pass_obj
def duplicate_keys(bibfile, as_json):
    """List citation keys that occur more than once, one per line."""
    data = list(Library(bibfile).duplicate_keys)
    _emit(data, as_json, "\n".join(data))


@main.command(
    name="timestamp",
    cls=_BibCommand,
    short_help="Print the modification timestamp from the header.",
    epilog=_examples(
        "bibdeskparser timestamp",
        "bibdeskparser timestamp --json",
    ),
)
@_json_option
@click.pass_obj
def timestamp(bibfile, as_json):
    """Print the modification timestamp from the file header."""
    data = _isoformat(Library(bibfile).timestamp)
    _emit(data, as_json, data or "")


@main.command(
    name="render",
    cls=_BibCommand,
    short_help="Render a citation for the given entries.",
    epilog=_examples(
        "bibdeskparser render Preskill2018",
        "bibdeskparser render Key1 Key2 --format html",
    ),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--format",
    "format_",
    type=click.Choice(["markdown", "tex", "html"]),
    default="markdown",
    show_default=True,
    help="The output format.",
)
@click.option(
    "--style",
    type=click.Choice(
        ["default", "paragraphs", "numbered list", "itemized list"]
    ),
    default="default",
    show_default=True,
    help="The layout of the citations relative to one another.",
)
@click.pass_obj
def render(bibfile, citekeys, format_, style):
    """Render a citation for the entries with the given keys."""
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    _echo_block(lib.render(*citekeys, format=format_, style=style))


@main.command(
    name="export",
    cls=_BibCommand,
    short_help="Export the given entries as bibtex text.",
    epilog=_examples(
        "bibdeskparser export Preskill2018",
        "bibdeskparser export Key1 Key2 --outfile out.bib",
    ),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--format",
    "format_",
    type=click.Choice(["default", "raw", "minimal"]),
    default="default",
    show_default=True,
    help="The export format.",
)
@click.option(
    "--outfile",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write to this file instead of printing to stdout.",
)
@click.pass_obj
def export(bibfile, citekeys, format_, outfile):
    """Export the entries with the given keys as bibtex text."""
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    text = lib.export(*citekeys, format=format_, outfile=outfile)
    if text is not None:
        _echo_block(text)


@main.command(
    name="eval_format_spec",
    cls=_BibCommand,
    short_help="Show the key or file name a format yields.",
    epilog=_examples(
        "bibdeskparser eval_format_spec Preskill2018 " "'%a1%Y%u0'",
        "bibdeskparser eval_format_spec Preskill2018 \\\n"
        "    --filename paper.pdf '%f{Cite Key}%e'",
    ),
)
@click.argument("citekey", metavar="KEY")
@click.argument("format_spec", metavar="FORMAT", required=False)
@click.option(
    "--filename",
    default=None,
    metavar="FILE",
    help=(
        "Evaluate FORMAT as a file name instead of a citation key, in "
        "the file-name dialect. FILE only supplies the original-name "
        "specifiers %l/%L/%e/%E (e.g. its extension); it need not "
        "exist or be attached to KEY. Pass an empty string to select "
        "the dialect when FORMAT uses none of those specifiers."
    ),
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def eval_format_spec(bibfile, citekey, format_spec, filename, as_json):
    """Print the citation key (or, with --filename, the file name)
    that a format yields for the entry with the given KEY. Read-only:
    nothing is renamed or moved.

    FORMAT is a pattern in BibDesk's format-specifier language (e.g.
    "%a1%c{journal}0%Y%u0"; with --filename e.g. "%f{Cite Key}%u0%e");
    if omitted, the 'format_spec' key of the [auto_key] table in
    bibdeskparser.toml is used ([auto_file], with --filename), which
    may map a different format to each entry type. If FILE is an
    attachment's current path and already matches the format, it
    evaluates to itself, so printing anything else means it does not
    follow the format.
    """
    lib = Library(bibfile)
    _check_keys(lib, [citekey])
    data = lib.eval_format_spec(citekey, format_spec, filename=filename)
    _emit(data, as_json, data)


# -- mutating commands -------------------------------------------------- #


@main.command(
    name="rekey",
    cls=_BibCommand,
    short_help="Change an entry's citation key.",
    epilog=_examples(
        "bibdeskparser rekey Preskill2018 Preskill2018NISQ",
        "bibdeskparser rekey Preskill2018 " "--format-spec '%a1%Y%u0'",
    ),
)
@click.argument("old_key")
@click.argument("new_key", required=False)
@click.option(
    "--format-spec",
    "format_spec",
    metavar="PATTERN",
    default=None,
    help=(
        "Generate the new key from this auto-key format pattern "
        '(e.g. "%a1%c{journal}0%Y%u0") instead of the configured one. '
        "Only valid without NEW_KEY."
    ),
)
@click.pass_obj
def rekey(bibfile, old_key, new_key, format_spec):
    """Change the citation key of an entry from OLD_KEY to NEW_KEY.

    If NEW_KEY is omitted, generate it from an auto-key format in
    BibDesk's format-specifier language: the --format-spec PATTERN if
    given, or else the 'format_spec' key of the [auto_key] table in
    bibdeskparser.toml (which may map a different format to each entry
    type). A generated key is printed to stdout. A key that already
    matches the format is kept unchanged, and a %u/%U/%n specifier in
    the format resolves collisions with other entries.
    """
    lib = Library(bibfile)
    _check_keys(lib, [old_key])
    result = lib.rekey(old_key, new_key, format_spec=format_spec)
    lib.save()
    if new_key is None:
        click.echo(result)


@main.command(
    name="delete",
    cls=_BibCommand,
    short_help="Delete the given entries from the library.",
    epilog=_examples("bibdeskparser delete StaleEntry2001"),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def delete(bibfile, citekeys):
    """Delete the entries with the given keys from the library."""
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    for key in citekeys:
        del lib[key]
    lib.save()


@main.command(
    name="set_type",
    cls=_BibCommand,
    short_help="Change the entry type of entry KEY.",
    epilog=_examples("bibdeskparser set_type Preskill2018 misc"),
)
@click.argument("citekey", metavar="KEY")
@click.argument("entry_type", metavar="TYPE")
@click.pass_obj
def set_type(bibfile, citekey, entry_type):
    """Change the entry type of the entry with the given KEY to TYPE,
    e.g. 'article' (case-insensitive). An unrecognized TYPE is
    rejected; see the 'types' configuration in bibdeskparser.toml to
    define custom entry types."""
    lib = Library(bibfile)
    _entry(lib, citekey).entry_type = entry_type
    lib.save()


@main.command(
    name="set_field",
    cls=_BibCommand,
    short_help="Set one field of an entry to VALUE.",
    epilog=_examples(
        "bibdeskparser set_field Preskill2018 volume 2",
        "bibdeskparser set_field Preskill2018 journal prl",
        "bibdeskparser set_field Preskill2018 title prl " "--literal",
    ),
)
@click.argument("citekey", metavar="KEY")
@click.argument("fieldname")
@click.argument("value")
@click.option(
    "--literal",
    is_flag=True,
    help=(
        "Store VALUE as literal text even if it looks like the name "
        "of an @string macro."
    ),
)
@click.option(
    "--macro",
    is_flag=True,
    help=(
        "Store VALUE as a bare @string macro reference; fail if it "
        "is not a valid macro name."
    ),
)
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def set_field(bibfile, citekey, fieldname, value, literal, macro):
    """Set the field FIELDNAME (case-insensitive) of the entry with
    the given KEY to VALUE, adding the field if it does not exist.

    Like BibDesk, a VALUE that is a valid `@string` macro name is
    stored as a bare macro reference rather than as literal text,
    unless --literal is given; --macro forces a macro reference. The
    'keywords', date, and 'bdsk-*' fields cannot be set this way (use
    add_to_keyword, add_file, add_url, etc.); an 'author'/'editor'
    VALUE must be parseable as names. A warning is printed on stderr
    for a field that is not appropriate for the entry type.
    """
    if literal and macro:
        raise click.UsageError("--literal and --macro are mutually exclusive")
    if literal:
        value = ValueString(value)
    elif macro:
        value = MacroString(value)
    lib = Library(bibfile)
    entry = _entry(lib, citekey)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        entry[fieldname] = value
    for warning in caught:
        click.echo(f"Warning: {warning.message}", err=True)
    lib.save()


@main.command(
    name="delete_field",
    cls=_BibCommand,
    short_help="Delete one field of an entry.",
    epilog=_examples("bibdeskparser delete_field Preskill2018 note"),
)
@click.argument("citekey", metavar="KEY")
@click.argument("fieldname")
@click.pass_obj
def delete_field(bibfile, citekey, fieldname):
    """Delete the field FIELDNAME (case-insensitive) from the entry
    with the given KEY.

    Fails for a field not defined on the entry (see `fields`), and
    for the 'keywords', date, and 'bdsk-*' fields (use
    remove_from_keyword, unlink_file, remove_url, etc. instead)."""
    lib = Library(bibfile)
    entry = _entry(lib, citekey)
    if fieldname not in entry:
        raise KeyError(f"entry {citekey!r} has no field {fieldname!r}")
    del entry[fieldname]
    lib.save()


@main.command(
    name="add_to_group",
    cls=_BibCommand,
    short_help="Add entries to the static group NAME.",
    epilog=_examples(
        'bibdeskparser add_to_group "quantum computing" ' "Preskill2018",
    ),
)
@click.argument("name")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def add_to_group(bibfile, name, citekeys):
    """Add the entries with the given keys to the static group NAME."""
    lib = Library(bibfile)
    _check_group(lib, name)
    _check_keys(lib, citekeys)
    lib.add_to_group(name, *citekeys)
    lib.save()


@main.command(
    name="remove_from_group",
    cls=_BibCommand,
    short_help="Remove entries from the group NAME.",
    epilog=_examples(
        "bibdeskparser remove_from_group Preprints Key2020",
    ),
)
@click.argument("name")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def remove_from_group(bibfile, name, citekeys):
    """Remove the entries with the given keys from the group NAME."""
    lib = Library(bibfile)
    _check_group(lib, name)
    lib.remove_from_group(name, *citekeys)
    lib.save()


@main.command(
    name="set_group",
    cls=_BibCommand,
    short_help="Create or replace the static group NAME.",
    epilog=_examples(
        "bibdeskparser set_group Theses Key2010 Key2015",
        "bibdeskparser set_group Theses   # empty the group",
    ),
)
@click.argument("name")
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@click.pass_obj
def set_group(bibfile, name, citekeys):
    """Create or replace the static group NAME with the given keys."""
    lib = Library(bibfile)
    lib.groups[name] = citekeys
    lib.save()


@main.command(
    name="delete_group",
    cls=_BibCommand,
    short_help="Delete the static group NAME.",
    epilog=_examples("bibdeskparser delete_group Theses"),
)
@click.argument("name")
@click.pass_obj
def delete_group(bibfile, name):
    """Delete the static group NAME (entries are not affected)."""
    lib = Library(bibfile)
    _check_group(lib, name)
    del lib.groups[name]
    lib.save()


@main.command(
    name="set_string",
    cls=_BibCommand,
    short_help="Define or redefine the @string macro NAME.",
    epilog=_examples(
        'bibdeskparser set_string prl "Phys. Rev. Lett."',
    ),
)
@click.argument("name")
@click.argument("value")
@click.pass_obj
def set_string(bibfile, name, value):
    """Define or redefine the @string macro NAME as VALUE."""
    lib = Library(bibfile)
    lib.strings[name] = value
    lib.save()


@main.command(
    name="delete_string",
    cls=_BibCommand,
    short_help="Delete the @string macro NAME (must be unused).",
    epilog=_examples("bibdeskparser delete_string prl"),
)
@click.argument("name")
@click.pass_obj
def delete_string(bibfile, name):
    """Delete the @string macro NAME (must be unused)."""
    lib = Library(bibfile)
    _check_string(lib, name)
    del lib.strings[name]
    lib.save()


@main.command(
    name="rename_string",
    cls=_BibCommand,
    short_help="Rename a @string macro, updating references.",
    epilog=_examples("bibdeskparser rename_string prl PhysRevLett"),
)
@click.argument("old_name")
@click.argument("new_name")
@click.pass_obj
def rename_string(bibfile, old_name, new_name):
    """Rename the @string macro OLD_NAME to NEW_NAME, updating all
    entries that reference it."""
    lib = Library(bibfile)
    _check_string(lib, old_name)
    lib.rename_string(old_name, new_name)
    lib.save()


@main.command(
    name="add_to_keyword",
    cls=_BibCommand,
    short_help="Add KEYWORD to the given entries.",
    epilog=_examples(
        "bibdeskparser add_to_keyword NISQ Preskill2018",
        'bibdeskparser add_to_keyword "open systems" Key1 Key2',
    ),
)
@click.argument("keyword")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def add_to_keyword(bibfile, keyword, citekeys):
    """Add KEYWORD to the entries with the given keys."""
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    lib.add_to_keyword(keyword, *citekeys)
    lib.save()


@main.command(
    name="remove_from_keyword",
    cls=_BibCommand,
    short_help="Remove KEYWORD from the given entries.",
    epilog=_examples(
        "bibdeskparser remove_from_keyword NISQ Preskill2018",
    ),
)
@click.argument("keyword")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def remove_from_keyword(bibfile, keyword, citekeys):
    """Remove KEYWORD from the entries with the given keys."""
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    lib.remove_from_keyword(keyword, *citekeys)
    lib.save()


@main.command(
    name="add_file",
    cls=_BibCommand,
    epilog=_examples(
        "bibdeskparser add_file Preskill2018 papers/nisq.pdf",
        "bibdeskparser add_file Preskill2018 new.pdf " "--location papers",
    ),
)
@click.argument("key")
@click.argument("filename")
@click.option(
    "--no-check-exists",
    is_flag=True,
    help=(
        "Do not require FILENAME to exist on disk (incompatible "
        "with auto-filing)."
    ),
)
@click.option(
    "--format-spec",
    "format_spec",
    metavar="PATTERN",
    default=None,
    help=(
        "Auto-file using this file-name format pattern (e.g. "
        '"%f{Cite Key}%u0%e") instead of the configured one. '
        "Implies auto-filing."
    ),
)
@click.option(
    "--location",
    default=None,
    metavar="DIR",
    help=(
        "Auto-file into this directory (relative to the .bib file, "
        "or absolute) instead of the configured one. Implies "
        "auto-filing."
    ),
)
@click.option(
    "--no-auto-file",
    is_flag=True,
    help=(
        "Attach FILENAME under its original name, even if the "
        "configuration sets 'file_automatically = true'."
    ),
)
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def add_file(
    bibfile,
    key,
    filename,
    no_check_exists,
    format_spec,
    location,
    no_auto_file,
):
    """Attach the file FILENAME to the entry KEY.

    When auto-filing is in effect -- --location or --format-spec
    given, or 'file_automatically = true' in the [auto_file] table of
    bibdeskparser.toml -- the file is not attached under its original
    name: it is *moved* into the auto-file location, renamed according
    to the file-name format, and the stored path (relative to the .bib
    file) is printed to stdout. A plain attach prints nothing.
    """
    if no_auto_file and (format_spec is not None or location is not None):
        raise click.UsageError(
            "--no-auto-file cannot be combined with --format-spec or "
            "--location"
        )
    lib = Library(bibfile)
    _check_keys(lib, [key])
    auto_file_location = "" if no_auto_file else location
    result = lib.add_file(
        key,
        filename,
        check_that_file_exists=not no_check_exists,
        format_spec=format_spec,
        auto_file_location=auto_file_location,
    )
    lib.save()
    if auto_file_location is None:
        auto_filed = (
            format_spec is not None or lib.config.auto_file.file_automatically
        )
    else:
        auto_filed = str(auto_file_location) != ""
    if auto_filed:
        click.echo(result)


@main.command(
    name="replace_file",
    cls=_BibCommand,
    short_help="Replace an entry's attached file OLD with NEW.",
    epilog=_examples(
        "bibdeskparser replace_file Key2020 old.pdf new.pdf " "--remove",
    ),
)
@click.argument("key")
@click.argument("old_filename", metavar="OLD")
@click.argument("new_filename", metavar="NEW")
@click.option(
    "--remove",
    is_flag=True,
    help="Also delete the old file from the filesystem.",
)
@click.option(
    "--no-check-exists",
    is_flag=True,
    help="Do not require NEW to exist on disk.",
)
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def replace_file(
    bibfile, key, old_filename, new_filename, remove, no_check_exists
):
    """Replace entry KEY's attached file OLD with NEW."""
    lib = Library(bibfile)
    _check_keys(lib, [key])
    lib.replace_file(
        key,
        old_filename,
        new_filename,
        remove=remove,
        check_that_file_exists=not no_check_exists,
    )
    lib.save()


@main.command(
    name="unlink_file",
    cls=_BibCommand,
    short_help="Remove a file from an entry's attachments.",
    epilog=_examples(
        "bibdeskparser unlink_file Key2020 paper.pdf",
        "bibdeskparser unlink_file Key2020 paper.pdf --remove",
    ),
)
@click.argument("key")
@click.argument("filename")
@click.option(
    "--remove",
    is_flag=True,
    help="Also delete the file from the filesystem.",
)
@click.pass_obj
def unlink_file(bibfile, key, filename, remove):
    """Remove the file FILENAME from entry KEY's attachments."""
    lib = Library(bibfile)
    _check_keys(lib, [key])
    lib.unlink_file(key, filename, remove=remove)
    lib.save()


@main.command(
    name="rename_file",
    cls=_BibCommand,
    short_help="Rename or move an entry's attached file.",
    epilog=_examples(
        "bibdeskparser rename_file Key2020 old.pdf new.pdf",
        "bibdeskparser rename_file Key2020 old.pdf  # auto-file",
    ),
)
@click.argument("key")
@click.argument("old_filename", metavar="OLD")
@click.argument("new_filename", metavar="NEW", required=False)
@click.option(
    "--format-spec",
    "format_spec",
    metavar="PATTERN",
    default=None,
    help=(
        "Generate the new file name from this file-name format "
        'pattern (e.g. "%f{Cite Key}%u0%e") instead of the '
        "configured one. Only valid without NEW."
    ),
)
@click.option(
    "--location",
    default=None,
    metavar="DIR",
    help=(
        "Move the file into this directory (relative to the .bib "
        "file, or absolute) instead of the configured auto-file "
        "location. Only valid without NEW."
    ),
)
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def rename_file(
    bibfile, key, old_filename, new_filename, format_spec, location
):
    """Rename (or move) entry KEY's attached file OLD to NEW on the
    filesystem, updating every entry that links it.

    If NEW is omitted, the target is generated by **auto-filing**: the
    file is moved into the auto-file location and renamed according to
    a file-name format in BibDesk's format-specifier language -- the
    --format-spec/--location options if given, or else the
    'format_spec' and 'location' keys of the [auto_file] table in
    bibdeskparser.toml -- and the new path (relative to the .bib file)
    is printed to stdout. A file whose name already matches the format
    is left in place, and a %u/%U/%n specifier in the format resolves
    collisions with existing files.
    """
    lib = Library(bibfile)
    _check_keys(lib, [key])
    result = lib.rename_file(
        key,
        old_filename,
        new_filename,
        format_spec=format_spec,
        auto_file_location=location,
    )
    lib.save()
    if new_filename is None:
        click.echo(result)


@main.command(
    name="add_url",
    cls=_BibCommand,
    epilog=_examples(
        "bibdeskparser add_url Key2020 https://example.org/x",
    ),
)
@click.argument("key")
@click.argument("url")
@click.pass_obj
def add_url(bibfile, key, url):
    """Add URL to the entry KEY."""
    lib = Library(bibfile)
    _check_keys(lib, [key])
    lib.add_url(key, url)
    lib.save()


@main.command(
    name="replace_url",
    cls=_BibCommand,
    epilog=_examples(
        "bibdeskparser replace_url Key2020 http://x.org " "https://x.org",
    ),
)
@click.argument("key")
@click.argument("old_url", metavar="OLD")
@click.argument("new_url", metavar="NEW")
@click.pass_obj
def replace_url(bibfile, key, old_url, new_url):
    """Replace entry KEY's URL OLD with NEW."""
    lib = Library(bibfile)
    _check_keys(lib, [key])
    lib.replace_url(key, old_url, new_url)
    lib.save()


@main.command(
    name="remove_url",
    cls=_BibCommand,
    epilog=_examples(
        "bibdeskparser remove_url Key2020 http://x.org",
    ),
)
@click.argument("key")
@click.argument("url")
@click.pass_obj
def remove_url(bibfile, key, url):
    """Remove URL from the entry KEY."""
    lib = Library(bibfile)
    _check_keys(lib, [key])
    lib.remove_url(key, url)
    lib.save()


_stdin_option = click.option(
    "--stdin",
    "use_stdin",
    is_flag=True,
    help=(
        "Read the full edited text from standard input instead of "
        "launching an editor (for non-interactive callers)."
    ),
)


def _resolve_editor(editor_cmd, use_stdin, allow_empty=False):
    """The `editor` argument for `Library.edit`/`.edit_strings`.

    With `--stdin`, returns a callable that overwrites the temporary
    file with the text read from standard input. Unless `allow_empty`
    is given, empty input is a usage error, so that redirecting from
    `/dev/null` cannot silently apply a destructive edit; the caller
    sets `allow_empty` when empty input is a valid no-op (a library
    with no `@string` macros in `edit_strings`). Without `--stdin` or
    an explicit `--editor`, a non-terminal stdin is a usage error: the
    command fails fast rather than blocking on `$EDITOR`.
    """
    if use_stdin:
        if editor_cmd is not None:
            raise click.UsageError(
                "--stdin and --editor are mutually exclusive"
            )
        text = sys.stdin.read()
        if not text.strip() and not allow_empty:
            raise click.UsageError(
                "--stdin was given, but standard input is empty"
            )
        return lambda path: path.write_text(text, encoding="utf-8")
    if editor_cmd is None and not sys.stdin.isatty():
        raise click.UsageError(
            "stdin is not a terminal; pipe the edited content with "
            '--stdin, or pass --editor "CMD"'
        )
    return editor_cmd


@main.command(
    name="edit",
    cls=_BibCommand,
    short_help="Edit the given entries in $EDITOR.",
    epilog=_examples(
        "bibdeskparser edit Preskill2018",
        "bibdeskparser export Key1 | sed s/2018/2019/ \\\n"
        "    | bibdeskparser edit Key1 --stdin",
    ),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--format",
    "format_",
    type=click.Choice(["default", "raw", "minimal"]),
    default="default",
    show_default=True,
    help="The format in which to present the entries in the editor.",
)
@click.option(
    "--editor",
    "editor_cmd",
    default=None,
    help="The editor command to use (default: $EDITOR).",
)
@_stdin_option
@click.pass_obj
def edit(bibfile, citekeys, format_, editor_cmd, use_stdin):
    """Edit the entries with the given keys and merge the changes back
    into the library (modifies the `.bib` file in place). From a
    terminal, this opens the entries as BibTeX text in `$EDITOR` (or
    `--editor`). Non-interactive callers pass `--stdin` and pipe in
    the full edited text instead: obtain the current text with
    `export KEY...`, modify it, and pipe it back (`export KEY... |
    edit KEY... --stdin` is a no-op). Without a terminal, `--stdin`,
    or `--editor`, the command fails immediately instead of
    blocking."""
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    editor_cmd = _resolve_editor(editor_cmd, use_stdin)
    lib.edit(*citekeys, format=format_, editor=editor_cmd)
    lib.save()


@main.command(
    name="edit_strings",
    cls=_BibCommand,
    short_help="Edit the @string macro definitions in $EDITOR.",
    epilog=_examples(
        "bibdeskparser edit_strings",
        "bibdeskparser strings --bib | sed s/Phys/PHYS/ \\\n"
        "    | bibdeskparser edit_strings --stdin",
    ),
)
@click.option(
    "--editor",
    "editor_cmd",
    default=None,
    help="The editor command to use (default: $EDITOR).",
)
@_stdin_option
@click.pass_obj
def edit_strings(bibfile, editor_cmd, use_stdin):
    """Edit the @string macro definitions and merge the changes back
    into the library (modifies the `.bib` file in place). From a
    terminal, this opens the definitions in `$EDITOR` (or `--editor`).
    Non-interactive callers pass `--stdin` and pipe in the full edited
    definitions instead: obtain the current definitions with `strings
    --bib`, modify them, and pipe them back. Without a terminal,
    `--stdin`, or `--editor`, the command fails immediately instead of
    blocking."""
    lib = Library(bibfile)
    # Empty stdin is a valid no-op exactly when there are no macros
    # (so an empty `strings --bib` round-trips); with macros present
    # it is rejected rather than deleting them all.
    editor_cmd = _resolve_editor(
        editor_cmd, use_stdin, allow_empty=not lib.strings
    )
    lib.edit_strings(editor=editor_cmd)
    lib.save()


# -- importing / adding entries ---------------------------------------- #


def _fix_uppercase_option(help_suffix):
    return click.option(
        "--fix-uppercase",
        is_flag=True,
        help=(
            "Fix all-uppercase author/editor names and titles (as "
            f"found in some {help_suffix}); the result may need manual "
            "correction."
        ),
    )


@main.command(
    name="import",
    cls=_BibCommand,
    short_help="Import entries from a BibTeX snippet.",
    epilog=_examples(
        "bibdeskparser import library.bib entries.bib",
        "pbpaste | bibdeskparser import --stdin",
        "bibdeskparser import --url " "https://example.com/refs.bib",
        "bibdeskparser export Key1 \\\n"
        "    | bibdeskparser import other.bib --stdin",
    ),
)
@click.argument(
    "source",
    metavar="[FILE]",
    required=False,
    type=click.Path(exists=True, dir_okay=False),
)
@_stdin_option
@click.option(
    "--url",
    default=None,
    help="Download the BibTeX text from URL.",
)
@click.option(
    "--keep-keys",
    is_flag=True,
    help=(
        "Keep the incoming citation keys instead of generating new " "ones."
    ),
)
@_fix_uppercase_option("publisher data")
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def import_bibtex(bibfile, source, use_stdin, url, keep_keys, fix_uppercase):
    """Import the entries of a BibTeX snippet -- read from FILE, from
    standard input (--stdin), or from a URL (--url); exactly one of
    the three -- into the library, and print their citation keys
    (modifies the `.bib` file in place).

    Every entry is sanitized: the journal becomes an `@string` macro
    reference (an existing macro matched by value, one configured in
    `[journal_macros]`, or a newly created one -- with a warning on
    stderr -- named by the journal's lowercased initials; a literal
    `arXiv:...` journal marks a preprint and stays literal, deriving
    `eprint`/`archiveprefix`), proper nouns in a sentence-case title
    (and all configured `protected_words`) are brace-protected, the
    DOI is normalized to its bare lowercase form, and, for articles,
    a page range collapses to its first page and non-essential fields
    (`month`, `publisher`, `numpages`, `issn`, a `url` shadowed by
    the DOI, ...) are dropped. Citation keys are regenerated (see
    --keep-keys) from the configured `[auto_key]` format, else as
    e.g. `GoerzPRA2014` (articles) or `Goerz2205.15044` (arXiv
    preprints). An entry whose DOI or eprint is already in the
    library is rejected. If anything about the snippet is not
    acceptable, all problems are reported and nothing is imported.

    Note that the library itself is always the *first* argument
    ending in `.bib`: importing from a `.bib` file requires naming
    the library explicitly (`import library.bib entries.bib`), even
    with a configured `default_bib_file`.
    """
    if (source is not None) + use_stdin + (url is not None) != 1:
        raise click.UsageError("give exactly one of FILE, --stdin, or --url")
    if use_stdin:
        text = sys.stdin.read()
        if not text.strip():
            raise click.UsageError(
                "--stdin was given, but standard input is empty"
            )
    elif url is not None:
        # Imported lazily: fetch pulls in the network dependencies.
        # pylint: disable-next=import-outside-toplevel
        from . import fetch

        text = fetch.fetch_text(url)
    else:
        text = Path(source).read_text(encoding="utf-8")
    lib = Library(bibfile)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        citekeys = lib.import_bibtex(
            text, keep_keys=keep_keys, fix_uppercase=fix_uppercase
        )
    for warning in caught:
        click.echo(f"Warning: {warning.message}", err=True)
    lib.save()
    for citekey in citekeys:
        click.echo(citekey)


@main.command(
    name="add",
    cls=_BibCommand,
    short_help="Fetch an entry by DOI/arXiv ID/query and add it.",
    epilog=_examples(
        "bibdeskparser add 10.1103/PhysRevA.89.032334",
        "bibdeskparser add https://arxiv.org/abs/2205.15044",
        "bibdeskparser add "
        "https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.113.140401",
        "bibdeskparser add --dry-run pulser open-source " "pulse sequences",
    ),
)
@click.argument("query", metavar="QUERY...", nargs=-1, required=True)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Print the entry that would be added (as BibTeX) instead of "
        "modifying the .bib file."
    ),
)
@_fix_uppercase_option("publisher metadata")
@click.pass_obj
def add(bibfile, query, dry_run, fix_uppercase):
    """Fetch bibliographic data for QUERY from the appropriate online
    source, add it to the library as a new, sanitized entry (exactly
    as with `import`), and print its citation key (modifies the
    `.bib` file in place; with --dry-run, prints the entry and
    modifies nothing).

    All QUERY arguments are joined into a single query: an arXiv
    identifier (or a string containing one, e.g. an arxiv.org URL) is
    fetched from the arXiv API and added as a preprint; a DOI (or a
    URL containing one, e.g. most publisher article pages) is fetched
    from Crossref; anything else (i.e., free text with spaces) is a
    Crossref bibliographic search, adding the best match -- verify
    the result! Requires network access.
    """
    lib = Library(bibfile)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        citekey = lib.add(" ".join(query), fix_uppercase=fix_uppercase)
    for warning in caught:
        click.echo(f"Warning: {warning.message}", err=True)
    if dry_run:
        _echo_block(lib.export(citekey))
    else:
        lib.save()
        click.echo(citekey)
