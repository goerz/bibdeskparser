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
from .checks import collect_problems
from .editing import strings_bib_text
from .library import Library, StaleFileError, _MissingFileWarning
from .macros import MacroString, ValueString
from .texmap import skip_texify, texify

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
    "files",
    "urls",
    "search",
    "groups",
    "keywords",
    "strings",
    "duplicate_keys",
    "check",
    "timestamp",
    "path",
    "config_path",
    "render",
    "export",
    "eval_format_spec",
    "create",
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
    "add_abstract",
    "add_preprint",
    "add_doi",
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

    bibfile_must_exist = True

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
        if self.bibfile_must_exist and not ctx.obj.is_file():
            raise click.ClickException(
                f"bibfile not found: {ctx.obj} (use 'bibdeskparser "
                f"create {ctx.obj}' to start a new library)"
            )
        try:
            return super().invoke(ctx)
        except _API_ERRORS as exc:
            raise click.ClickException(_error_message(exc)) from exc


class _NewBibCommand(_BibCommand):
    """A `_BibCommand` whose bibfile need not exist yet (`create`)."""

    bibfile_must_exist = False


_json_option = click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the data as JSON instead of human-readable text.",
)


_unicode_option = click.option(
    "--unicode/--no-unicode",
    "unicode_",
    default=True,
    show_default=True,
    help=(
        "Show field values as Unicode text (default), or TeX-encoded "
        "as stored in the .bib file (--no-unicode)."
    ),
)


_expand_strings_option = click.option(
    "--expand-strings/--no-expand-strings",
    "expand_strings",
    default=True,
    show_default=True,
    help=(
        "Replace a field value that references an @string macro by "
        "the macro's value (default). With --no-expand-strings, show "
        "the bare macro name instead (see `strings` for the "
        "definitions); with --json, every field value then uniformly "
        'becomes an object {"macro": <name or null>, "value": <value '
        "or null>} instead of a plain string."
    ),
)


def _emit(data, as_json, text):
    """Print `data` as JSON if `as_json`, else print `text` (if any)."""
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    elif text:
        click.echo(text)


def _save(lib):
    """Save `lib`, reporting save-time warnings as `Warning:` lines on
    stderr.

    Warnings about linked files that do not exist are printed
    individually only up to a small number; beyond that (e.g. for a
    `.bib` file separated from its attachment tree), they collapse
    into a single summary line.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        lib.save()
    missing = []
    for warning in caught:
        if issubclass(warning.category, _MissingFileWarning):
            missing.append(str(warning.message))
        else:
            click.echo(f"Warning: {warning.message}", err=True)
    if len(missing) > 5:
        click.echo(
            f"Warning: {len(missing)} linked files do not exist "
            f"(first: {missing[0]})",
            err=True,
        )
    else:
        for message in missing:
            click.echo(f"Warning: {message}", err=True)


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
        "bibdeskparser create new.bib  # start a new library",
        "bibdeskparser keys     # list all citation keys",
        "bibdeskparser keys --type article --missing doi",
        'bibdeskparser search "quantum computing"',
        "bibdeskparser show Preskill2018 --json",
        "bibdeskparser get_field Preskill2018 journal",
        "bibdeskparser get_field Preskill2018 journal --no-expand-strings",
        "bibdeskparser set_field Preskill2018 doi 10.1234/xyz",
        "bibdeskparser add_to_keyword NISQ Preskill2018",
        "bibdeskparser add_file Preskill2018 papers/nisq.pdf",
        "bibdeskparser export Preskill2018  # entry as BibTeX",
        "bibdeskparser export Preskill2018 --minimal --expand-strings",
        "bibdeskparser render Preskill2018  # formatted citation",
        "bibdeskparser check  # run the standing audits (exit 0/1)",
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

    Read-only commands (`author`, `check`, `config_path`,
    `duplicate_keys`, `editor`, `eval_format_spec`, `fields`, `files`,
    `get_field`, `groups`, `keys`, `keywords`, `path`, `search`,
    `show`, `strings`, `timestamp`, `urls`) print to stdout and accept
    `--json` for machine-readable output; `render` and `export` are
    read-only as well. The other commands modify the
    `.bib` file in place and print nothing on success (except `rekey`
    without NEW_KEY and `rename_file` without NEW, which print the
    generated key or file path, as does `add_file` when it auto-files;
    `import` and `add` print the citation keys of the added entries,
    and `add --dry-run` only prints the fetched entry, without
    modifying the file; `add_abstract`, `add_preprint`, and `add_doi`
    print a per-key report of the fetched abstracts/arXiv
    identifiers/DOIs, with `--dry-run` without modifying the file,
    and with a configured [known_missing] table they also update the
    corresponding static group memberships).
    Every command requires the `.bib` file to exist, except `create`,
    which starts a new, empty library and requires that the file does
    *not* exist yet.
    On any error they print `Error: <message>` to stderr and exit
    non-zero (2 for bad usage, 1 for a library error such as an unknown
    key or a `.bib` file changed on disk since it was read). The
    `check` command additionally exits 1, after printing its report,
    when any audit finds a problem. Run
    `bibdeskparser COMMAND --help` for a command's arguments.
    """


# -- read-only commands ------------------------------------------------ #


@main.command(
    name="keys",
    cls=_BibCommand,
    short_help="List citation keys, optionally filtered.",
    epilog=_examples(
        "bibdeskparser keys",
        "bibdeskparser keys --type article --type book",
        "bibdeskparser keys --missing doi --json",
        'bibdeskparser keys --group "My Papers"',
        "bibdeskparser keys --without-files  # entries lacking a PDF",
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
        "Keep only entries where FIELD has no non-empty value "
        "(repeatable). A defined-but-empty FIELD counts as missing."
    ),
)
@click.option(
    "--group",
    "group_names",
    multiple=True,
    metavar="NAME",
    help=(
        "Keep only entries that are members of the static group NAME "
        "(repeatable, an entry must be in every given group). Group "
        "names are case-sensitive; an unknown NAME is an error."
    ),
)
@click.option(
    "--not-group",
    "not_group_names",
    multiple=True,
    metavar="NAME",
    help=(
        "Keep only entries that are not members of the static group "
        "NAME (repeatable). Group names are case-sensitive; an "
        "unknown NAME is an error."
    ),
)
@click.option(
    "--with-files/--without-files",
    "with_files",
    default=None,
    help=(
        "Keep only entries that have at least one file attachment "
        "(--with-files) or none (--without-files). The default is to "
        "not filter on attachments."
    ),
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def keys(
    bibfile,
    types,
    has_fields,
    missing_fields,
    group_names,
    not_group_names,
    with_files,
    as_json,
):
    """List citation keys, one per line.

    Without options, list every entry in the library. The options
    narrow the list; an entry is listed if it matches one of the
    --type values (if any are given) and satisfies every --has,
    --missing, --group, --not-group, and --with-files/--without-files
    filter. For any FIELD, exactly one of --has and --missing holds; a
    field that is defined with an empty value counts as missing
    (BibDesk deletes empty fields on save). --with-files keeps entries
    with a file attachment, --without-files those with none (see the
    `files` command). Field names are case-insensitive, group names
    case-sensitive.
    """
    lib = Library(bibfile)
    for name in (*group_names, *not_group_names):
        _check_group(lib, name)
    data = list(
        lib.keys(
            types=types,
            has=has_fields,
            missing=missing_fields,
            group=group_names,
            not_group=not_group_names,
            with_files=with_files,
        )
    )
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


def _display_value(value, name, strings, unicode_, expand):
    """`(text, data)` display forms of one decoded field value.

    `value` is what `entry[name]` returns ({class}`ValueString` or
    {class}`MacroString`); `strings` maps macro names to their Unicode
    values (including the standard month macros). `text` is the
    human-readable form and `data` the JSON-ready form. With
    `expand=True` (macro references replaced by their values), `data`
    is a plain string; with `expand=False`, `data` is uniformly a
    `{"macro": ..., "value": ...}` dict for *every* field (`macro` is
    `None` for a literal value, `value` is `None` for an undefined
    macro), so consumers get one shape per invocation. With
    `unicode_=False`, string values are TeX-encoded.
    """

    def _tex(text):
        if unicode_ or skip_texify(name):
            return text
        return texify(text)

    if isinstance(value, MacroString):
        macro = str(value)
        resolved = strings.get(macro)
        if expand:
            shown = _tex(resolved) if resolved is not None else macro
            return shown, shown
        data = {
            "macro": macro,
            "value": _tex(resolved) if resolved is not None else None,
        }
        return macro, data
    shown = _tex(str(value))
    if expand:
        return shown, shown
    return shown, {"macro": None, "value": shown}


def _entry_data(entry, strings, unicode_, expand, only_fields=None):
    """The JSON-ready data for `entry` (a dict).

    With `only_fields` (a list of field names), the result is just a
    map of those fields (that are defined) to their values; otherwise
    it is the full record (type, key, fields, and derived data).
    Field values are rendered via `_display_value` (with the given
    `strings`/`unicode_`/`expand` settings).
    """
    if only_fields is not None:
        field_values = _selected_field_values(entry, only_fields)
    else:
        field_values = dict(entry)
    fields_data = {
        name: _display_value(value, name, strings, unicode_, expand)[1]
        for name, value in field_values.items()
    }
    if only_fields is not None:
        return fields_data
    return {
        "entry_type": entry.entry_type,
        "key": entry.key,
        "fields": fields_data,
        "groups": list(entry.groups),
        "keywords": list(entry.keywords),
        "files": list(entry.files),
        "urls": list(entry.urls),
        "date_added": _isoformat(entry.date_added),
        "date_modified": _isoformat(entry.date_modified),
    }


def _entry_block(entry, strings, unicode_, expand, only_fields=None):
    """A human-readable multi-line block describing `entry`.

    With `only_fields`, only the `KEY (type)` heading and the named
    fields (that are defined) are shown, without the derived data.
    Field values are rendered via `_display_value` (with the given
    `strings`/`unicode_`/`expand` settings).
    """
    lines = [f"{entry.key} ({entry.entry_type})"]
    if only_fields is not None:
        field_values = _selected_field_values(entry, only_fields)
    else:
        field_values = dict(entry)
    width = max((len(name) for name in field_values), default=0)
    for name, value in field_values.items():
        value = _display_value(value, name, strings, unicode_, expand)[0]
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
    "--skip-missing/--no-skip-missing",
    default=False,
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
@_unicode_option
@_expand_strings_option
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def show(
    bibfile,
    citekeys,
    field_args,
    skip_missing,
    keys_from,
    unicode_,
    expand_strings,
    as_json,
):
    """Show the data of the entries with the given keys.

    Keys come from the KEY arguments and/or --keys-from; at least one
    is required. By default every field and the derived data (groups,
    keywords, files, URLs, dates) are shown; --field narrows this to
    the named fields. Field values are rendered: Unicode text
    (--no-unicode for the TeX-encoded stored values), with @string
    macro references replaced by the macro's value
    (--no-expand-strings for the bare macro name). An unknown key
    aborts the command unless --skip-missing is given, in which case
    it is reported on stderr and the remaining entries are still
    shown.
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
    strings = lib._all_strings()
    data = {
        entry.key: _entry_data(
            entry, strings, unicode_, expand_strings, only_fields
        )
        for entry in entries
    }
    text = "\n\n".join(
        _entry_block(entry, strings, unicode_, expand_strings, only_fields)
        for entry in entries
    )
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
@_unicode_option
@_expand_strings_option
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def get_field(bibfile, citekey, fieldname, unicode_, expand_strings, as_json):
    """Print the value of the field FIELDNAME (case-insensitive) of
    the entry with the given KEY.

    The value is rendered: Unicode text (--no-unicode for the
    TeX-encoded stored value), with an @string macro reference
    replaced by the macro's value (--no-expand-strings for the bare
    macro name; see `strings` for the definitions). Fails for a field
    not defined on the entry (see `fields`)."""
    lib = Library(bibfile)
    entry = _entry(lib, citekey)
    if fieldname not in entry:
        raise KeyError(f"entry {citekey!r} has no field {fieldname!r}")
    text, data = _display_value(
        entry[fieldname],
        fieldname,
        lib._all_strings(),
        unicode_,
        expand_strings,
    )
    _emit(data, as_json, text)


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


def _emit_derived(lib, citekeys, values_for, as_json, flat):
    """Print the per-entry derived lists produced by `values_for`.

    Without `flat`, a `{key: [values]}` map: the requested `citekeys`
    (each present, an empty one as `[]`), or -- for no keys -- every
    library entry that has at least one value, in library order. With
    `flat`, the values themselves as a bare list, combined across the
    selected entries with duplicates removed (a single key keeps that
    entry's own order). An unknown key in `citekeys` is an error.
    """
    _check_keys(lib, citekeys)
    keys = citekeys if citekeys else lib.keys()
    if flat:
        seen = {}
        for key in keys:
            for value in values_for(key):
                seen.setdefault(value, None)
        data = list(seen)
        _emit(data, as_json, "\n".join(data))
        return
    if citekeys:
        data = {key: values_for(key) for key in citekeys}
    else:
        data = {}
        for key in keys:
            values = values_for(key)
            if values:
                data[key] = values
    text = "\n".join(
        f"{key}: {', '.join(values)}" for key, values in data.items()
    )
    _emit(data, as_json, text)


def _emit_index(mapping, as_json):
    """Print an inverse name -> member-keys `mapping` (`Library.groups`
    or `Library.keywords`) as a `{name: [keys]}` map."""
    data = {name: list(keys) for name, keys in mapping.items()}
    text = "\n".join(
        f"{name}: {', '.join(keys)}" for name, keys in data.items()
    )
    _emit(data, as_json, text)


@main.command(
    name="files",
    cls=_BibCommand,
    short_help="List file attachments of entries, or the whole library.",
    epilog=_examples(
        "bibdeskparser files GoerzJPB2011",
        "bibdeskparser files GoerzJPB2011 --relative --flat",
        "bibdeskparser files                 # whole-library map",
        "bibdeskparser files --flat          # every referenced file",
    ),
)
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@click.option(
    "--absolute/--relative",
    "absolute",
    default=True,
    show_default=True,
    help=(
        "Print each attachment as an absolute path (default), or as "
        "stored in the .bib file, relative to the file's directory "
        "(--relative)."
    ),
)
@click.option(
    "--flat/--no-flat",
    default=False,
    help=(
        "Print just the attachment paths as a bare list, combined "
        "across the selected entries, instead of a {key: [paths]} map."
    ),
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def files(bibfile, citekeys, absolute, flat, as_json):
    """List file attachments (the `bdsk-file-N` fields), in numeric
    order within each entry. By default, each attachment is printed as
    an absolute path; with --relative, as stored in the `.bib` file
    (relative to its directory).

    The output is a map from each citation key to its list of
    attachments: with KEY arguments, exactly those entries (an entry
    with none maps to an empty list); with no KEY, every entry in the
    library that has at least one attachment, in library order. With
    --flat, the attachment paths are instead printed as a bare list,
    one per line, combined across the selected entries with duplicates
    removed -- so `files --flat` is every file the library references,
    the reverse index for reconciling against a folder of PDFs (find
    the entries lacking one with `keys --without-files`). An unknown
    key is an error. Attachments are modified with `add_file`,
    `replace_file`, `unlink_file`, and `rename_file`."""
    lib = Library(bibfile)
    base = lib._files_base_dir() if absolute else None

    def paths_for(key):
        paths = list(lib[key].files)
        if absolute:
            paths = [str((base / p).resolve()) for p in paths]
        return paths

    _emit_derived(lib, citekeys, paths_for, as_json, flat)


@main.command(
    name="urls",
    cls=_BibCommand,
    short_help="List linked URLs of entries, or the whole library.",
    epilog=_examples(
        "bibdeskparser urls KochJPCM2016",
        "bibdeskparser urls KochJPCM2016 --flat",
        "bibdeskparser urls --json          # whole-library map",
    ),
)
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@click.option(
    "--flat/--no-flat",
    default=False,
    help=(
        "Print just the URLs as a bare list, combined across the "
        "selected entries, instead of a {key: [urls]} map."
    ),
)
@_json_option
@click.pass_obj
def urls(bibfile, citekeys, flat, as_json):
    """List the URLs linked to entries (the `bdsk-url-N` fields), in
    numeric order within each entry.

    The output is a map from each citation key to its list of URLs:
    with KEY arguments, exactly those entries (an entry with none maps
    to an empty list); with no KEY, every entry in the library that has
    at least one linked URL, in library order. With --flat, the URLs
    are instead printed as a bare list, one per line, combined across
    the selected entries with duplicates removed. An unknown key is an
    error. Linked URLs are modified with `add_url`, `replace_url`, and
    `remove_url`."""
    lib = Library(bibfile)

    def values_for(key):
        return list(lib[key].urls)

    _emit_derived(lib, citekeys, values_for, as_json, flat)


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
    short_help="List the groups of entries, or all static groups.",
    epilog=_examples(
        "bibdeskparser groups Preskill2018   # that entry's groups",
        "bibdeskparser groups                # per-entry group map",
        "bibdeskparser groups --index        # each group's members",
        "bibdeskparser groups --flat         # all group names in use",
    ),
)
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@click.option(
    "--flat/--no-flat",
    default=False,
    help=(
        "Print just the group names as a bare list, combined across "
        "the selected entries, instead of a {key: [groups]} map."
    ),
)
@click.option(
    "--index/--no-index",
    default=False,
    help=(
        "Instead print the inverse {group: [member keys]} map of every "
        "static group. Not combinable with KEY arguments or --flat."
    ),
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def groups(bibfile, citekeys, flat, index, as_json):
    """List the static groups (see BibDesk static groups) that entries
    belong to.

    The default output is a map from each citation key to its list of
    group names: with KEY arguments, exactly those entries (an entry in
    no group maps to an empty list); with no KEY, every entry that is in
    at least one group, in library order. With --flat, the group names
    are instead printed as a bare list, combined across the selected
    entries with duplicates removed. With --index, the inverse is
    printed: a map from each static group name to the citation keys it
    contains (every group, including empty ones); --index takes no KEY
    arguments and is not combinable with --flat. An unknown key is an
    error. Group membership is modified with `add_to_group`,
    `remove_from_group`, `set_group`, and `delete_group`."""
    lib = Library(bibfile)
    if index:
        if citekeys or flat:
            raise click.UsageError(
                "--index cannot be combined with KEY arguments or --flat"
            )
        _emit_index(lib.groups, as_json)
        return

    def values_for(key):
        return list(lib[key].groups)

    _emit_derived(lib, citekeys, values_for, as_json, flat)


@main.command(
    name="keywords",
    cls=_BibCommand,
    short_help="List the keywords of entries, or all keywords.",
    epilog=_examples(
        "bibdeskparser keywords Preskill2018   # that entry's keywords",
        "bibdeskparser keywords                # per-entry keyword map",
        "bibdeskparser keywords --index        # each keyword's entries",
        "bibdeskparser keywords --flat         # all keywords in use",
    ),
)
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@click.option(
    "--flat/--no-flat",
    default=False,
    help=(
        "Print just the keywords as a bare list, combined across the "
        "selected entries, instead of a {key: [keywords]} map."
    ),
)
@click.option(
    "--index/--no-index",
    default=False,
    help=(
        "Instead print the inverse {keyword: [entry keys]} map of every "
        "keyword. Not combinable with KEY arguments or --flat."
    ),
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def keywords(bibfile, citekeys, flat, index, as_json):
    """List the keywords that entries are tagged with.

    The default output is a map from each citation key to its list of
    keywords: with KEY arguments, exactly those entries (an untagged
    entry maps to an empty list); with no KEY, every entry that has at
    least one keyword, in library order. With --flat, the keywords are
    instead printed as a bare list, combined across the selected entries
    with duplicates removed. With --index, the inverse is printed: a map
    from each keyword to the citation keys tagged with it; --index takes
    no KEY arguments and is not combinable with --flat. An unknown key
    is an error. Keywords are modified with `add_to_keyword` and
    `remove_from_keyword`."""
    lib = Library(bibfile)
    if index:
        if citekeys or flat:
            raise click.UsageError(
                "--index cannot be combined with KEY arguments or --flat"
            )
        _emit_index(lib.keywords, as_json)
        return

    def values_for(key):
        return list(lib[key].keywords)

    _emit_derived(lib, citekeys, values_for, as_json, flat)


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
    name="check",
    cls=_BibCommand,
    short_help="Run the standing audits (a read-only pass/fail gate).",
    epilog=_examples(
        "bibdeskparser check",
        "bibdeskparser check --json",
        "bibdeskparser check Key1 Key2  # gate after editing these",
    ),
)
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@_json_option
@click.pass_obj
def check(bibfile, citekeys, as_json):
    """Run the standing audits and report every problem found, then
    exit 0 if all pass and 1 otherwise: a read-only pass/fail gate,
    e.g. after a batch of edits.

    The audits: the file parses cleanly (no skipped blocks); no
    citation key occurs more than once; every article that is not a
    preprint has a doi (membership in the known-missing group
    configured for 'doi' in the [known_missing] table of
    bibdeskparser.toml marks an entry verified to have none, and
    passes); no entry has a defined-but-empty field (BibDesk deletes
    empty fields on save, so the field would silently disappear); no
    entry sits in a configured known-missing group for a field it
    actually has a non-empty value for; every journal field
    references a *defined* @string macro (a literal journal value is
    a problem, unless it is a recognized preprint pseudo-journal like
    'arXiv:2205.15044'); every author and editor field parses as
    names; and every @string macro defined in the file is referenced
    by some entry.

    With KEY..., only the given entries are audited (an unknown key
    is an error): the per-entry audits cover just those entries, the
    duplicate-key audit reports only the given keys, and the
    unused-macros audit is skipped; problems parsing the file itself
    are always reported.

    Each problem prints as one line, 'KEY: <problem>' for a problem
    tied to an entry, followed by a 'PASS (N entries checked)' or
    'FAIL (N problems, M entries checked)' summary line. With --json:
    {"passed": ..., "entries_checked": ..., "problems": [{"check":
    ..., "key": ..., "message": ...}]}, where "check" names the audit
    ("parse", "duplicate_keys", "doi", "empty_fields",
    "known_missing", "journal", "names", or "unused_strings") and
    "key" is null for a problem not tied to an entry.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        lib = Library(bibfile)
    _check_keys(lib, citekeys)
    for warning in caught:
        message = str(warning.message)
        # The load warnings for duplicate keys and unparseable blocks
        # (see `Library.__init__`) are covered by the duplicate_keys
        # and parse audits; any other load warning (e.g. distinct
        # macros expanding to the same value) passes through, without
        # failing the gate.
        if "duplicate citation keys" in message:
            continue
        if "could not be parsed" in message:
            continue
        click.echo(f"Warning: {message}", err=True)
    problems = collect_problems(lib, keys=citekeys or None)
    n_entries = len(dict.fromkeys(citekeys)) if citekeys else len(lib)
    entries = "entry" if n_entries == 1 else "entries"
    if as_json:
        data = {
            "passed": not problems,
            "entries_checked": n_entries,
            "problems": [problem._asdict() for problem in problems],
        }
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        for problem in problems:
            if problem.key is not None:
                click.echo(f"{problem.key}: {problem.message}")
            else:
                click.echo(problem.message)
        if problems:
            n_problems = len(problems)
            plural = "problem" if n_problems == 1 else "problems"
            click.echo(
                f"FAIL ({n_problems} {plural}, "
                f"{n_entries} {entries} checked)"
            )
        else:
            click.echo(f"PASS ({n_entries} {entries} checked)")
    if problems:
        sys.exit(1)


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
    name="path",
    cls=_BibCommand,
    short_help="Print the absolute path of the .bib file.",
    epilog=_examples(
        "bibdeskparser path",
        "bibdeskparser path --json",
    ),
)
@_json_option
@click.pass_obj
def path(bibfile, as_json):
    """Print the absolute path of the `.bib` file being operated on:
    the given BIBFILE, or the configured `default_bib_file` when
    BIBFILE is omitted. With --json: a string."""
    data = str(Path(bibfile).resolve())
    _emit(data, as_json, data)


@main.command(
    name="config_path",
    cls=_BibCommand,
    short_help="Print the absolute path of the config file.",
    epilog=_examples(
        "bibdeskparser config_path",
        "bibdeskparser config_path --json",
    ),
)
@_json_option
@click.pass_obj
def config_path(bibfile, as_json):
    """Print the absolute path of the `bibdeskparser.toml`
    configuration file in effect for the `.bib` file being operated
    on. Discovery checks the directory of the `.bib` file, then the
    file named by `$BIBDESKPARSER_CONFIG`, then the XDG location
    (`~/.config/bibdeskparser/bibdeskparser.toml`); first found wins.
    Fails with an error if no configuration file is found (the
    built-in defaults are then in effect). With --json: a string."""
    found = config.active.load(bib_dir=Path(bibfile).resolve().parent)
    if found is None:
        raise click.ClickException(
            "no configuration file found (using built-in defaults)"
        )
    data = str(found.resolve())
    _emit(data, as_json, data)


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
    """Render a citation for the entries with the given keys.

    A preprint-only entry (a `misc` or `unpublished` entry with an
    eprint, or any entry with a pseudo-journal like
    `arXiv:2205.15044`) renders its
    preprint reference in the journal position, hyperlinked; any
    other entry's eprint renders as a separate link after the
    journal reference."""
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    _echo_block(lib.render(*citekeys, format=format_, style=style))


@main.command(
    name="export",
    cls=_BibCommand,
    short_help="Export the given entries as bibtex text.",
    epilog=_examples(
        "bibdeskparser export Preskill2018",
        "bibdeskparser export Preskill2018 --minimal --expand-strings",
        "bibdeskparser export Key1 Key2 --outfile out.bib",
    ),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--unicode/--no-unicode",
    "unicode_",
    default=True,
    show_default=True,
    help=(
        "Export field values as Unicode text (default), or "
        "TeX-encoded as stored in the .bib file (--no-unicode)."
    ),
)
@click.option(
    "--expand-strings/--no-expand-strings",
    "expand_strings",
    default=False,
    show_default=True,
    help=(
        "Replace @string macro references by the macro's value. By "
        "default, references are kept bare and the needed @string "
        "definitions are prepended instead."
    ),
)
@click.option(
    "--field",
    "field_args",
    multiple=True,
    metavar="FIELD",
    help=(
        "Export only these fields (case-insensitive) instead of the "
        "full record; repeatable and comma-separated (e.g. "
        "--field doi,title). A field not defined on an entry is "
        "silently omitted for that entry. Mutually exclusive with "
        "--minimal."
    ),
)
@click.option(
    "--minimal/--no-minimal",
    default=False,
    help=(
        "Export only the fields needed to typeset a bibliography. "
        "Mutually exclusive with --field."
    ),
)
@click.option(
    "--outfile",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write to this file instead of printing to stdout.",
)
@click.option(
    "--preprint",
    type=click.Choice(["unpublished", "misc", "article", "stored"]),
    default=None,
    help=(
        "The entry type a preprint-only entry is exported as: "
        "'unpublished' or 'misc' (structured eprint fields; for "
        "styles that render eprint, like REVTeX; 'unpublished' "
        "guarantees the required note field, using the stored note "
        "or 'preprint') or 'article' (pseudo-journal linked via "
        "url; for classic styles that would drop an eprint), each "
        "with the appropriately derived fields; 'stored' exports "
        "the entry as stored. Defaults to the preprint_export "
        "configuration setting ('unpublished' unless configured)."
    ),
)
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def export(
    bibfile,
    citekeys,
    unicode_,
    expand_strings,
    field_args,
    minimal,
    outfile,
    preprint,
):
    """Export the entries with the given keys as bibtex text.

    By default, the export contains every field (with file
    attachments and URLs as plain paths/URLs, and without the
    date-added/date-modified bookkeeping fields), field values are
    Unicode text, and @string macro references stay bare, with the
    needed @string definitions prepended, so the output is
    self-contained. --no-unicode exports the TeX-encoded values as
    stored in the .bib file; --expand-strings replaces macro
    references by their values (no @string definitions then);
    --minimal or --field restrict which fields are exported. A
    preprint-only entry (a `misc` or `unpublished` entry with an
    eprint, or any entry with a pseudo-journal like
    `arXiv:2205.15044`) is exported in
    the form selected by --preprint, whatever its stored form; an
    explicit --field list always exports the stored fields."""
    if minimal and field_args:
        raise click.UsageError("--minimal and --field are mutually exclusive")
    fields = (
        "minimal" if minimal else (_split_field_names(field_args) or "full")
    )
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    text = lib.export(
        *citekeys,
        unicode=unicode_,
        expand_strings=expand_strings,
        fields=fields,
        outfile=outfile,
        preprint=preprint,
    )
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
    name="create",
    cls=_NewBibCommand,
    short_help="Create a new, empty .bib file.",
    epilog=_examples(
        "bibdeskparser create new.bib",
        "bibdeskparser create   # the configured default_bib_file",
        "bibdeskparser create new.bib && \\\n"
        "    bibdeskparser import new.bib entries.bib",
    ),
)
@click.pass_obj
def create(bibfile):
    """Create BIBFILE as a new, empty library: a `.bib` file
    containing only the standard BibDesk header comment, ready for
    `import`, `add`, `set_string`, etc. Unlike for every other
    command, BIBFILE must *not* already exist; an existing file is
    never overwritten. Prints nothing on success."""
    # `Library.save` also refuses an existing path (`FileExistsError`),
    # but its message suggests `force=True`, which has no CLI
    # equivalent (deliberately: `create` must never overwrite).
    if bibfile.exists():
        raise click.ClickException(f"bibfile already exists: {bibfile}")
    Library().save(bibfile)


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
    _save(lib)
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
    _save(lib)


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
    _save(lib)


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

    An empty VALUE is an error: BibDesk deletes empty fields when it
    saves the .bib file, so an empty value cannot carry information.
    Use delete_field to remove FIELDNAME; to record that an entry is
    verified not to have the information, add it to a known-missing
    group instead (see the [known_missing] configuration and
    add_to_group).
    """
    if literal and macro:
        raise click.UsageError("--literal and --macro are mutually exclusive")
    if not value.strip():
        raise click.ClickException(
            "an empty VALUE is never stored (BibDesk deletes empty "
            "fields when it saves the .bib file); use 'delete_field' "
            f"to remove {fieldname!r}, or record a verified absence "
            "by adding the entry to a known-missing group (see the "
            "[known_missing] configuration and 'add_to_group')"
        )
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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    "--check-exists/--no-check-exists",
    default=True,
    help=(
        "Require FILENAME to exist on disk (the default; "
        "--no-check-exists is incompatible with auto-filing)."
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
    "--auto-file/--no-auto-file",
    "auto_file",
    default=None,
    help=(
        "Auto-file into the configured location even if the "
        "configuration does not set 'file_automatically = true' "
        "(--auto-file), or attach FILENAME under its original name "
        "even if it does (--no-auto-file). By default, the "
        "configuration decides."
    ),
)
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def add_file(
    bibfile,
    key,
    filename,
    check_exists,
    format_spec,
    location,
    auto_file,
):
    """Attach the file FILENAME to the entry KEY.

    When auto-filing is in effect -- --auto-file, --location, or
    --format-spec given, or 'file_automatically = true' in the
    [auto_file] table of bibdeskparser.toml -- the file is not
    attached under its original name: it is *moved* into the
    auto-file location, renamed according to the file-name format,
    and the stored path (relative to the .bib file) is printed to
    stdout. A plain attach prints nothing.
    """
    if auto_file is False and (
        format_spec is not None or location is not None
    ):
        raise click.UsageError(
            "--no-auto-file cannot be combined with --format-spec or "
            "--location"
        )
    lib = Library(bibfile)
    _check_keys(lib, [key])
    if auto_file is False:
        auto_file_location = ""
    elif auto_file is True:
        auto_file_location = location or lib.config.auto_file.location
    else:
        auto_file_location = location
    result = lib.add_file(
        key,
        filename,
        check_that_file_exists=check_exists,
        format_spec=format_spec,
        auto_file_location=auto_file_location,
    )
    _save(lib)
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
    "--remove/--no-remove",
    default=False,
    help="Also delete the old file from the filesystem.",
)
@click.option(
    "--check-exists/--no-check-exists",
    default=True,
    help="Require NEW to exist on disk (the default).",
)
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def replace_file(
    bibfile, key, old_filename, new_filename, remove, check_exists
):
    """Replace entry KEY's attached file OLD with NEW."""
    lib = Library(bibfile)
    _check_keys(lib, [key])
    lib.replace_file(
        key,
        old_filename,
        new_filename,
        remove=remove,
        check_that_file_exists=check_exists,
    )
    _save(lib)


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
    "--remove/--no-remove",
    default=False,
    help="Also delete the file from the filesystem.",
)
@click.pass_obj
def unlink_file(bibfile, key, filename, remove):
    """Remove the file FILENAME from entry KEY's attachments."""
    lib = Library(bibfile)
    _check_keys(lib, [key])
    lib.unlink_file(key, filename, remove=remove)
    _save(lib)


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
    _save(lib)
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
    _save(lib)


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
    _save(lib)


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
    _save(lib)


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
    "--editor",
    "editor_cmd",
    default=None,
    help="The editor command to use (default: $EDITOR).",
)
@_stdin_option
@click.pass_obj
def edit(bibfile, citekeys, editor_cmd, use_stdin):
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
    lib.edit(*citekeys, editor=editor_cmd)
    _save(lib)


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
    _save(lib)


# -- importing / adding entries ---------------------------------------- #


def _fix_uppercase_option(help_suffix, default=False):
    help_text = (
        "Fix all-uppercase author/editor names and titles (as "
        f"found in some {help_suffix}); the result may need manual "
        "correction."
    )
    return click.option(
        "--fix-uppercase/--no-fix-uppercase",
        default=default,
        help=help_text,
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
    "--keep-keys/--no-keep-keys",
    default=False,
    help=(
        "Keep the incoming citation keys instead of generating new " "ones."
    ),
)
@click.option(
    "--keep-journals/--no-keep-journals",
    default=False,
    help=(
        "Preserve the incoming journal fields as-is instead of "
        "converting them to @string macro references."
    ),
)
@_fix_uppercase_option("publisher data")
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def import_bibtex(
    bibfile, source, use_stdin, url, keep_keys, keep_journals, fix_uppercase
):
    """Import the entries of a BibTeX snippet -- read from FILE, from
    standard input (--stdin), or from a URL (--url); exactly one of
    the three -- into the library, and print their citation keys
    (modifies the `.bib` file in place).

    Every entry is sanitized: the journal becomes an `@string` macro
    reference (an existing macro matched by value, one configured in
    `[journal_macros]`, or a newly created one -- with a warning on
    stderr -- named by the journal's lowercased initials; disable
    with --keep-journals), proper nouns in a sentence-case title
    (and all configured `protected_words`) are brace-protected, the
    DOI is normalized to its bare lowercase form, and, for articles,
    a page range collapses to its first page and non-essential fields
    (`month`, `publisher`, `numpages`, `issn`, a `url` shadowed by
    the DOI, ...) are dropped. A preprint-only entry -- one with a
    pseudo-journal like `arXiv:2205.15044` (also `bioRxiv:`, `HAL:`,
    ..., per the `[preprint_archives]` configuration), or a
    `misc`/`unpublished` entry with an eprint, like arXiv's own
    BibTeX export -- is normalized to an `@unpublished` entry
    carrying the pseudo-journal (in canonical spelling) plus derived
    `eprint`/`archiveprefix`/`doi` fields (a publication-status
    `note` is never synthesized: fill it in by hand); an
    unrecognized archive prefix is an error unless --keep-journals
    is given. Citation keys are regenerated (see --keep-keys) from
    the
    configured `[auto_key]` format, else as e.g. `GoerzPRA2014`
    (articles) or `Goerz2205.15044` (preprints). An entry whose DOI
    or eprint is already in the library is rejected. If anything
    about the snippet is not acceptable, all problems are reported
    and nothing is imported.

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
            text,
            keep_keys=keep_keys,
            fix_uppercase=fix_uppercase,
            keep_journals=keep_journals,
        )
    for warning in caught:
        click.echo(f"Warning: {warning.message}", err=True)
    _save(lib)
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
@_fix_uppercase_option("publisher metadata", default=None)
@click.option(
    "--add-abstract/--no-add-abstract",
    default=None,
    help=(
        "Also store the abstract returned alongside the metadata "
        "(the publisher's Crossref deposit, or the arXiv summary) in "
        "the new entry's abstract field, cleaned to plain-unicode "
        "prose. Defaults to the [add] configuration (off)."
    ),
)
@click.option(
    "--add-preprint/--no-add-preprint",
    default=None,
    help=(
        "Also search arXiv for a preprint matching the new entry and "
        "record it in the eprint field (exactly as with the "
        "add_preprint command, which reports its result to stderr "
        "here; skipped when the entry already has an eprint). "
        "Defaults to the [add] configuration (off)."
    ),
)
@click.pass_obj
# click passes all parameters by keyword; the add_abstract parameter
# shadows the `add_abstract` command on purpose: click derives it
# from the `--add-abstract` option name (same for add_preprint)
# pylint: disable-next=redefined-outer-name,too-many-positional-arguments
def add(bibfile, query, dry_run, fix_uppercase, add_abstract, add_preprint):
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
    if add_preprint is None:
        add_preprint = config.active.add.add_preprint
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        citekey = lib.add(
            " ".join(query),
            fix_uppercase=fix_uppercase,
            add_abstract=add_abstract,
            add_preprint=False,  # done below, to report the result
        )
        preprint_result = None
        if add_preprint and not str(lib[citekey].get("eprint") or ""):
            preprint_result = lib.add_preprint(citekey)
    for warning in caught:
        click.echo(f"Warning: {warning.message}", err=True)
    if preprint_result is not None:
        # to stderr: stdout stays the citation key / dry-run entry
        _echo_preprint_result(citekey, preprint_result, err=True)
    if dry_run:
        _echo_block(lib.export(citekey))
    else:
        _save(lib)
        click.echo(citekey)


@main.command(
    name="add_abstract",
    cls=_BibCommand,
    short_help="Fetch and store missing abstracts for entries.",
    epilog=_examples(
        "bibdeskparser add_abstract GoerzPRA2014",
        "bibdeskparser add_abstract --json $(bibdeskparser keys "
        "--type article --missing abstract)",
        "bibdeskparser add_abstract --dry-run --min-confidence low Key2020",
    ),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--min-confidence",
    type=click.Choice(["high", "medium", "low"]),
    default=None,
    help=(
        "Lowest confidence level that is stored automatically; a "
        "candidate below it is only reported, for manual review. "
        "Defaults to the [add_abstract] configuration (high)."
    ),
)
@click.option(
    "--overwrite/--no-overwrite",
    default=False,
    help=(
        "Refetch and replace an existing non-empty abstract instead "
        "of skipping the entry; also re-search entries in the "
        "known-missing group for 'abstract' (explicit re-audit)."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the per-key report without modifying the .bib file.",
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def add_abstract(
    bibfile, citekeys, min_confidence, overwrite, dry_run, as_json
):
    """Fetch and store missing abstracts for the entries KEY...

    For each KEY, gather candidate abstracts from Crossref (via the
    entry's doi field), from the text of the entry's attached PDF
    (requires the poppler 'pdftotext' tool on PATH), from the arXiv
    API (via the eprint field), and from Semantic Scholar; clean each
    candidate to plain-unicode prose; and store the best one in the
    entry's abstract field if its confidence -- high (identified by
    doi/eprint, or confirmed by two sources), medium (a single
    unconfirmed source), or low (sources disagree) -- reaches
    --min-confidence. Entries that already have a non-empty abstract
    are skipped (see --overwrite).

    With a known-missing group configured for 'abstract' (the
    [known_missing] table of bibdeskparser.toml), the command has two
    modes. By default, entries in the group are skipped as verified
    to have no findable abstract, without any search; a search that
    runs cleanly against every source and finds nothing adds the
    entry to the group (creating it on first use); and storing an
    abstract removes the entry from the group -- so routine fill-in
    runs never re-search entries already audited. With --overwrite,
    the membership is ignored and the search re-runs: an explicit
    re-audit, for when an abstract may have become available since
    the last check, typically over exactly the group members:
    `add_abstract --overwrite $(bibdeskparser keys --group "No
    Abstract")`. An entry that still yields nothing stays in the
    group. A search during which any source failed never marks the
    entry. Without the configuration, none of this bookkeeping
    happens.

    Prints a per-key report; candidates that were *not* stored are
    reported in full, so that they can be reviewed and applied
    manually with `set_field KEY abstract "..."`. With --json, the
    report maps each KEY to {abstract, source, confidence, note,
    applied}. Modifies the .bib file in place (unless --dry-run is
    given); requires network access.
    """
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    results = {}
    for key in citekeys:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = lib.add_abstract(
                key,
                min_confidence=min_confidence,
                overwrite=overwrite,
            )
        for warning in caught:
            click.echo(f"Warning: {warning.message}", err=True)
        results[key] = result._asdict()
        if not as_json:
            _echo_abstract_result(key, result)
    if as_json:
        click.echo(json.dumps(results, indent=2, ensure_ascii=False))
    if not dry_run and any(r["applied"] for r in results.values()):
        _save(lib)


def _echo_abstract_result(key, result):
    """One report line (plus the abstract text, where it needs
    review) for an `add_abstract` result."""
    if result.source == "existing":
        click.echo(
            f"{key}: skipped (already has an abstract; --overwrite to "
            "refetch)"
        )
    elif result.source == "known-missing":
        click.echo(f"{key}: skipped (known missing; --overwrite to re-search)")
    elif result.source == "error":
        click.echo(f"{key}: lookup failed [{result.note}]")
    elif not result.abstract:
        if result.applied:
            group = config.active.known_missing.get("abstract")
            click.echo(
                f"{key}: no abstract found (marked known missing in "
                f"group {group!r}) [{result.note}]"
            )
        else:
            click.echo(f"{key}: no abstract found [{result.note}]")
    elif result.applied:
        click.echo(f"{key}: stored ({result.source}, {result.confidence})")
    else:
        click.echo(
            f"{key}: needs review ({result.source}, {result.confidence}) "
            f"[{result.note}]"
        )
        click.echo(f"    {result.abstract}")


@main.command(
    name="add_preprint",
    cls=_BibCommand,
    short_help="Find and store arXiv identifiers (eprint) for entries.",
    epilog=_examples(
        "bibdeskparser add_preprint GoerzPRA2014",
        "bibdeskparser add_preprint $(bibdeskparser keys "
        "--type article --missing eprint)",
        "bibdeskparser add_preprint --overwrite $(bibdeskparser keys "
        '--group "No Eprint")',
        "bibdeskparser add_preprint Key2020 --eprint arXiv:2205.15044v1",
    ),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--eprint",
    metavar="ID",
    default=None,
    help=(
        "Store this arXiv identifier explicitly instead of searching "
        "(allowed with a single KEY only; no network access). A "
        "leading 'arXiv:' prefix and a version suffix ('v2') are "
        "stripped."
    ),
)
@click.option(
    "--overwrite/--no-overwrite",
    default=False,
    help=(
        "Replace an existing non-empty eprint instead of skipping "
        "the entry; also re-search entries in the known-missing "
        "group for 'eprint' (explicit re-audit)."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the per-key report without modifying the .bib file.",
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def add_preprint(bibfile, citekeys, eprint, overwrite, dry_run, as_json):
    """Find and store the matching arXiv preprint for the entries
    KEY...

    For each KEY, search the arXiv API for a preprint matching the
    entry (by title and first author, precise queries first) and, on
    a confident match -- the result's DOI equals the entry's doi
    field, a near-exact title match, or a good title match
    corroborated by the first author's last name -- store its
    identifier in the entry's eprint field, along with
    archiveprefix = arXiv and the preprint's primary category (e.g.
    quant-ph) as primaryclass. A title-based match that postdates the
    entry's year is rejected unless the result's journal reference
    corroborates the year; such a 'postdated-unverified' candidate is
    reported for review and can be applied explicitly with --eprint.
    Entries that already have a non-empty eprint are skipped (see
    --overwrite).

    With a known-missing group configured for 'eprint' (the
    [known_missing] table of bibdeskparser.toml), the command has two
    modes. By default, entries in the group are skipped as verified
    to have no preprint, without contacting arXiv; a search that runs
    cleanly and finds no preprint adds the entry to the group
    (creating it on first use); and storing an identifier removes the
    entry from the group -- so routine fill-in runs (e.g. over `keys
    --missing eprint`) never re-query arXiv for entries already
    searched. With --overwrite, the membership is ignored and the
    search re-runs: an explicit re-audit, for when the earlier match
    may have failed or a preprint may have been posted since the last
    check, typically over exactly the group members:
    `add_preprint --overwrite $(bibdeskparser keys --group "No
    Eprint")`. An entry with another clean no-match stays in the
    group. A failed search never marks the entry. Without the
    configuration, none of this bookkeeping happens.

    Prints a per-key report; with --json, the report maps each KEY to
    {eprint, match, ratio, note, applied, primaryclass}. Modifies the
    .bib file in place (unless --dry-run is given); requires network
    access (except with --eprint) and respects the arXiv API's rate
    limit of one request every three seconds, so large runs take
    time.
    """
    if eprint is not None and len(citekeys) > 1:
        raise click.UsageError("--eprint requires a single KEY")
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    results = {}
    for key in citekeys:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = lib.add_preprint(key, eprint, overwrite=overwrite)
        for warning in caught:
            click.echo(f"Warning: {warning.message}", err=True)
        results[key] = result._asdict()
        if not as_json:
            _echo_preprint_result(key, result)
    if as_json:
        click.echo(json.dumps(results, indent=2, ensure_ascii=False))
    if not dry_run and any(r["applied"] for r in results.values()):
        _save(lib)


def _echo_preprint_result(key, result, err=False):
    """One report line for an `add_preprint` result."""
    if result.match == "existing":
        click.echo(
            f"{key}: skipped (already has an eprint; --overwrite to "
            "replace)",
            err=err,
        )
    elif result.match == "known-missing":
        click.echo(
            f"{key}: skipped (known missing; --overwrite to re-search)",
            err=err,
        )
    elif result.match == "explicit":
        click.echo(f"{key}: stored eprint {result.eprint}", err=err)
    elif result.eprint:
        tag = f" [{result.primaryclass}]" if result.primaryclass else ""
        click.echo(
            f"{key}: stored eprint {result.eprint}{tag} "
            f"(match={result.match}, ratio={result.ratio:.2f})",
            err=err,
        )
    elif result.match == "error":
        click.echo(f"{key}: search failed [{result.note}]", err=err)
    else:
        if result.applied:
            group = config.active.known_missing.get("eprint")
            click.echo(
                f"{key}: no preprint found (marked known missing in "
                f"group {group!r}) [{result.note}]",
                err=err,
            )
        else:
            click.echo(f"{key}: no preprint found [{result.note}]", err=err)


@main.command(
    name="add_doi",
    cls=_BibCommand,
    short_help="Find and store missing DOIs for entries.",
    epilog=_examples(
        "bibdeskparser add_doi GoerzNJP2014",
        "bibdeskparser add_doi $(bibdeskparser keys "
        "--type article --missing doi)",
        "bibdeskparser add_doi --overwrite $(bibdeskparser keys "
        '--group "No DOI")',
        "bibdeskparser add_doi Key2020 --doi 10.1103/PhysRevA.89.032334",
    ),
)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--doi",
    metavar="DOI",
    default=None,
    help=(
        "Store this DOI explicitly instead of searching (allowed "
        "with a single KEY only; no network access). A leading "
        "'doi:' prefix or 'https://doi.org/' resolver address is "
        "stripped, and the DOI is lowercased."
    ),
)
@click.option(
    "--overwrite/--no-overwrite",
    default=False,
    help=(
        "Replace an existing non-empty doi instead of skipping the "
        "entry; also re-search entries in the known-missing group "
        "for 'doi' (explicit re-audit)."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the per-key report without modifying the .bib file.",
)
@_json_option
@click.pass_obj
# click passes all parameters by keyword
# pylint: disable-next=too-many-positional-arguments
def add_doi(bibfile, citekeys, doi, overwrite, dry_run, as_json):
    """Find and store the DOI for the entries KEY...

    For each KEY, look up the entry's DOI online: if the entry has an
    arXiv eprint, the arXiv API is consulted first (the DOI recorded
    there names the published version of exactly this paper);
    otherwise Crossref is searched for the entry (by title and first
    author) and, on a confident match -- a near-exact title match, or
    a good title match corroborated by the first author's last name
    -- the found DOI is stored in the entry's doi field (in its bare
    lowercase form). A title-based match whose publication year
    differs from the entry's year by more than one is rejected as a
    likely title collision; such a 'year-mismatch' candidate is
    reported for review and can be applied explicitly with --doi.
    Errata, corrigenda, retractions, comments, and replies never
    match an entry that is not itself such an amendment. Entries that
    already have a non-empty doi are skipped (see --overwrite), and
    preprint-only entries are skipped without any lookup (the search
    would find the DOI of the published version, which does not
    belong on a preprint reference; store it deliberately with --doi,
    or replace the entry with the published version via the add
    command).

    With a known-missing group configured for 'doi' (the
    [known_missing] table of bibdeskparser.toml), the command has two
    modes. By default, entries in the group are skipped as verified
    to have no DOI, without any lookup; a lookup that runs cleanly
    and finds nothing adds the entry to the group (creating it on
    first use); and storing a DOI removes the entry from the group --
    so routine fill-in runs (e.g. over `keys --missing doi`) never
    re-query the sources for entries already searched. With
    --overwrite, the membership is ignored and the lookup re-runs: an
    explicit re-audit, for when a DOI may have been registered since
    the last check, typically over exactly the group members:
    `add_doi --overwrite $(bibdeskparser keys --group "No DOI")`. An
    entry with another clean no-match stays in the group. A failed
    lookup never marks the entry. Group membership also makes the
    check command accept an article without a doi. Without the
    configuration, none of this bookkeeping happens.

    Prints a per-key report; with --json, the report maps each KEY to
    {doi, match, ratio, note, applied}. Modifies the .bib file in
    place (unless --dry-run is given); requires network access
    (except with --doi), and an eprint lookup respects the arXiv
    API's rate limit of one request every three seconds.
    """
    if doi is not None and len(citekeys) > 1:
        raise click.UsageError("--doi requires a single KEY")
    lib = Library(bibfile)
    _check_keys(lib, citekeys)
    results = {}
    for key in citekeys:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = lib.add_doi(key, doi, overwrite=overwrite)
        for warning in caught:
            click.echo(f"Warning: {warning.message}", err=True)
        results[key] = result._asdict()
        if not as_json:
            _echo_doi_result(key, result)
    if as_json:
        click.echo(json.dumps(results, indent=2, ensure_ascii=False))
    if not dry_run and any(r["applied"] for r in results.values()):
        _save(lib)


def _echo_doi_result(key, result):
    """One report line for an `add_doi` result."""
    if result.match == "existing":
        click.echo(
            f"{key}: skipped (already has a doi; --overwrite to replace)"
        )
    elif result.match == "known-missing":
        click.echo(f"{key}: skipped (known missing; --overwrite to re-search)")
    elif result.match == "preprint":
        click.echo(f"{key}: skipped (preprint-only entry) [{result.note}]")
    elif result.match == "explicit":
        click.echo(f"{key}: stored doi {result.doi}")
    elif result.doi:
        detail = f"match={result.match}"
        if result.ratio is not None:
            detail += f", ratio={result.ratio:.2f}"
        click.echo(f"{key}: stored doi {result.doi} ({detail})")
    elif result.match == "error":
        click.echo(f"{key}: lookup failed [{result.note}]")
    else:
        if result.applied:
            group = config.active.known_missing.get("doi")
            click.echo(
                f"{key}: no doi found (marked known missing in "
                f"group {group!r}) [{result.note}]"
            )
        else:
            click.echo(f"{key}: no doi found [{result.note}]")
