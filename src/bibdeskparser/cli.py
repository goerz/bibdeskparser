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
from pathlib import Path

import click

from . import __version__, config
from .editing import strings_bib_text
from .library import Library, StaleFileError

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "main",
    "keys",
    "show",
    "groups",
    "keywords",
    "strings",
    "duplicate_keys",
    "timestamp",
    "render",
    "export",
    "rekey",
    "delete",
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
]

# Exceptions raised by the `Library` API for invalid user input; the
# CLI converts these into clean one-line error messages (exit code 1).
_API_ERRORS = (
    KeyError,
    ValueError,
    FileNotFoundError,
    FileExistsError,
    StaleFileError,
)


def _error_message(exc):
    """A one-line message for an API exception.

    `KeyError` stringifies to the `repr` of its argument (quotes
    included), so use the bare argument instead.
    """
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _default_bibfile(ctx):
    """The bibfile from `default_bib_file` in the discovered config.

    Discovery is relative to the current working directory (or the XDG
    location); fails with a usage error if no `default_bib_file` is
    configured.
    """
    try:
        config.load()
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    bibfile = config.get_default_bib_file()
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


@click.group()
@click.version_option(version=__version__)
def main():
    """Command-line interface for BibDesk `.bib` databases.

    Every command takes the `.bib` file to operate on as its first
    argument (any argument ending in `.bib`). If omitted, the file
    named by the `default_bib_file` key of a discovered
    `bibdeskparser.toml` is used instead.

    Read-only commands (`keys`, `show`, `search`, `groups`, `keywords`,
    `strings`, `duplicate_keys`, `timestamp`) print to stdout and accept
    `--json` for machine-readable output. The other commands modify the
    `.bib` file in place and print nothing on success. On any error they
    print `Error: <message>` to stderr and exit non-zero (2 for bad
    usage, 1 for a library error such as an unknown key or a `.bib` file
    changed on disk since it was read). Run `bibdeskparser COMMAND
    --help` for a command's arguments.
    """


# -- read-only commands ------------------------------------------------ #


@main.command(name="keys", cls=_BibCommand)
@_json_option
@click.pass_obj
def keys(bibfile, as_json):
    """List all citation keys, one per line."""
    data = list(Library(bibfile))
    _emit(data, as_json, "\n".join(data))


def _entry_data(entry):
    """The JSON-ready data for `entry` (a dict)."""
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


def _entry_block(entry):
    """A human-readable multi-line block describing `entry`."""
    lines = [f"{entry.key} ({entry.entry_type})"]
    fields = dict(entry)
    width = max((len(name) for name in fields), default=0)
    for name, value in fields.items():
        lines.append(f"    {(name + ':').ljust(width + 1)} {value}")
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


@main.command(name="show", cls=_BibCommand)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@_json_option
@click.pass_obj
def show(bibfile, citekeys, as_json):
    """Show the full data of the entries with the given keys."""
    lib = Library(bibfile)
    entries = [lib[key] for key in citekeys]
    data = {entry.key: _entry_data(entry) for entry in entries}
    text = "\n\n".join(_entry_block(entry) for entry in entries)
    _emit(data, as_json, text)


@main.command(name="search", cls=_BibCommand)
@click.argument("query")
@click.option(
    "--field",
    "fields",
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
    help="The match strictness.",
)
@_json_option
@click.pass_obj
def search(bibfile, query, fields, match_, as_json):
    """List the keys of the entries matching QUERY, best match first,
    one per line."""
    lib = Library(bibfile)
    entries = lib.search(query, fields=fields or None, match=match_)
    data = [entry.key for entry in entries]
    _emit(data, as_json, "\n".join(data))


@main.command(name="groups", cls=_BibCommand)
@_json_option
@click.pass_obj
def groups(bibfile, as_json):
    """List all static groups and the keys they contain."""
    data = {
        name: list(group_keys)
        for name, group_keys in Library(bibfile).groups.items()
    }
    text = "\n".join(
        f"{name}: {', '.join(group_keys)}" for name, group_keys in data.items()
    )
    _emit(data, as_json, text)


@main.command(name="keywords", cls=_BibCommand)
@_json_option
@click.pass_obj
def keywords(bibfile, as_json):
    """List all keywords and the keys of the entries using them."""
    data = {
        keyword: list(kw_keys)
        for keyword, kw_keys in Library(bibfile).keywords.items()
    }
    text = "\n".join(
        f"{keyword}: {', '.join(kw_keys)}" for keyword, kw_keys in data.items()
    )
    _emit(data, as_json, text)


@main.command(name="strings", cls=_BibCommand)
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


@main.command(name="duplicate_keys", cls=_BibCommand)
@_json_option
@click.pass_obj
def duplicate_keys(bibfile, as_json):
    """List citation keys that occur more than once, one per line."""
    data = list(Library(bibfile).duplicate_keys)
    _emit(data, as_json, "\n".join(data))


@main.command(name="timestamp", cls=_BibCommand)
@_json_option
@click.pass_obj
def timestamp(bibfile, as_json):
    """Print the modification timestamp from the file header."""
    data = _isoformat(Library(bibfile).timestamp)
    _emit(data, as_json, data or "")


@main.command(name="render", cls=_BibCommand)
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
    _echo_block(lib.render(*citekeys, format=format_, style=style))


@main.command(name="export", cls=_BibCommand)
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
    text = lib.export(*citekeys, format=format_, outfile=outfile)
    if text is not None:
        _echo_block(text)


# -- mutating commands -------------------------------------------------- #


@main.command(name="rekey", cls=_BibCommand)
@click.argument("old_key")
@click.argument("new_key")
@click.pass_obj
def rekey(bibfile, old_key, new_key):
    """Change the citation key of an entry from OLD_KEY to NEW_KEY."""
    lib = Library(bibfile)
    lib.rekey(old_key, new_key)
    lib.save()


@main.command(name="delete", cls=_BibCommand)
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def delete(bibfile, citekeys):
    """Delete the entries with the given keys from the library."""
    lib = Library(bibfile)
    for key in citekeys:
        del lib[key]
    lib.save()


@main.command(name="add_to_group", cls=_BibCommand)
@click.argument("name")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def add_to_group(bibfile, name, citekeys):
    """Add the entries with the given keys to the static group NAME."""
    lib = Library(bibfile)
    lib.add_to_group(name, *citekeys)
    lib.save()


@main.command(name="remove_from_group", cls=_BibCommand)
@click.argument("name")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def remove_from_group(bibfile, name, citekeys):
    """Remove the entries with the given keys from the group NAME."""
    lib = Library(bibfile)
    lib.remove_from_group(name, *citekeys)
    lib.save()


@main.command(name="set_group", cls=_BibCommand)
@click.argument("name")
@click.argument("citekeys", metavar="[KEY...]", nargs=-1)
@click.pass_obj
def set_group(bibfile, name, citekeys):
    """Create or replace the static group NAME with the given keys."""
    lib = Library(bibfile)
    lib.groups[name] = citekeys
    lib.save()


@main.command(name="delete_group", cls=_BibCommand)
@click.argument("name")
@click.pass_obj
def delete_group(bibfile, name):
    """Delete the static group NAME (entries are not affected)."""
    lib = Library(bibfile)
    del lib.groups[name]
    lib.save()


@main.command(name="set_string", cls=_BibCommand)
@click.argument("name")
@click.argument("value")
@click.pass_obj
def set_string(bibfile, name, value):
    """Define or redefine the @string macro NAME as VALUE."""
    lib = Library(bibfile)
    lib.strings[name] = value
    lib.save()


@main.command(name="delete_string", cls=_BibCommand)
@click.argument("name")
@click.pass_obj
def delete_string(bibfile, name):
    """Delete the @string macro NAME (must be unused)."""
    lib = Library(bibfile)
    del lib.strings[name]
    lib.save()


@main.command(name="rename_string", cls=_BibCommand)
@click.argument("old_name")
@click.argument("new_name")
@click.pass_obj
def rename_string(bibfile, old_name, new_name):
    """Rename the @string macro OLD_NAME to NEW_NAME, updating all
    entries that reference it."""
    lib = Library(bibfile)
    lib.rename_string(old_name, new_name)
    lib.save()


@main.command(name="add_to_keyword", cls=_BibCommand)
@click.argument("keyword")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def add_to_keyword(bibfile, keyword, citekeys):
    """Add KEYWORD to the entries with the given keys."""
    lib = Library(bibfile)
    lib.add_to_keyword(keyword, *citekeys)
    lib.save()


@main.command(name="remove_from_keyword", cls=_BibCommand)
@click.argument("keyword")
@click.argument("citekeys", metavar="KEY...", nargs=-1, required=True)
@click.pass_obj
def remove_from_keyword(bibfile, keyword, citekeys):
    """Remove KEYWORD from the entries with the given keys."""
    lib = Library(bibfile)
    lib.remove_from_keyword(keyword, *citekeys)
    lib.save()


@main.command(name="add_file", cls=_BibCommand)
@click.argument("key")
@click.argument("filename")
@click.option(
    "--no-check-exists",
    is_flag=True,
    help="Do not require FILENAME to exist on disk.",
)
@click.pass_obj
def add_file(bibfile, key, filename, no_check_exists):
    """Attach the file FILENAME to the entry KEY."""
    lib = Library(bibfile)
    lib.add_file(key, filename, check_that_file_exists=not no_check_exists)
    lib.save()


@main.command(name="replace_file", cls=_BibCommand)
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
    lib.replace_file(
        key,
        old_filename,
        new_filename,
        remove=remove,
        check_that_file_exists=not no_check_exists,
    )
    lib.save()


@main.command(name="unlink_file", cls=_BibCommand)
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
    lib.unlink_file(key, filename, remove=remove)
    lib.save()


@main.command(name="rename_file", cls=_BibCommand)
@click.argument("key")
@click.argument("old_filename", metavar="OLD")
@click.argument("new_filename", metavar="NEW")
@click.pass_obj
def rename_file(bibfile, key, old_filename, new_filename):
    """Rename (or move) entry KEY's attached file OLD to NEW on the
    filesystem, updating every entry that links it."""
    lib = Library(bibfile)
    lib.rename_file(key, old_filename, new_filename)
    lib.save()


@main.command(name="add_url", cls=_BibCommand)
@click.argument("key")
@click.argument("url")
@click.pass_obj
def add_url(bibfile, key, url):
    """Add URL to the entry KEY."""
    lib = Library(bibfile)
    lib.add_url(key, url)
    lib.save()


@main.command(name="replace_url", cls=_BibCommand)
@click.argument("key")
@click.argument("old_url", metavar="OLD")
@click.argument("new_url", metavar="NEW")
@click.pass_obj
def replace_url(bibfile, key, old_url, new_url):
    """Replace entry KEY's URL OLD with NEW."""
    lib = Library(bibfile)
    lib.replace_url(key, old_url, new_url)
    lib.save()


@main.command(name="remove_url", cls=_BibCommand)
@click.argument("key")
@click.argument("url")
@click.pass_obj
def remove_url(bibfile, key, url):
    """Remove URL from the entry KEY."""
    lib = Library(bibfile)
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


def _resolve_editor(editor, use_stdin):
    """The `editor` argument for `Library.edit`/`.edit_strings`.

    With `--stdin`, returns a callable that overwrites the temporary
    file with the text read from standard input (empty input is a
    usage error, so that redirecting from `/dev/null` cannot silently
    apply a no-op edit). Without `--stdin` or an explicit `--editor`,
    a non-terminal stdin is a usage error: the command fails fast
    rather than blocking on `$EDITOR`.
    """
    if use_stdin:
        if editor is not None:
            raise click.UsageError(
                "--stdin and --editor are mutually exclusive"
            )
        text = sys.stdin.read()
        if not text.strip():
            raise click.UsageError(
                "--stdin was given, but standard input is empty"
            )
        return lambda path: path.write_text(text, encoding="utf-8")
    if editor is None and not sys.stdin.isatty():
        raise click.UsageError(
            "stdin is not a terminal; pipe the edited content with "
            '--stdin, or pass --editor "CMD"'
        )
    return editor


@main.command(name="edit", cls=_BibCommand)
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
    default=None,
    help="The editor command to use (default: $EDITOR).",
)
@_stdin_option
@click.pass_obj
def edit(bibfile, citekeys, format_, editor, use_stdin):
    """Edit the entries with the given keys and merge the changes back
    into the library (modifies the `.bib` file in place). From a
    terminal, this opens the entries as BibTeX text in `$EDITOR` (or
    `--editor`). Non-interactive callers pass `--stdin` and pipe in
    the full edited text instead: obtain the current text with
    `export KEY...`, modify it, and pipe it back (`export KEY... |
    edit KEY... --stdin` is a no-op). Without a terminal, `--stdin`,
    or `--editor`, the command fails immediately instead of
    blocking."""
    editor = _resolve_editor(editor, use_stdin)
    lib = Library(bibfile)
    lib.edit(*citekeys, format=format_, editor=editor)
    lib.save()


@main.command(name="edit_strings", cls=_BibCommand)
@click.option(
    "--editor",
    default=None,
    help="The editor command to use (default: $EDITOR).",
)
@_stdin_option
@click.pass_obj
def edit_strings(bibfile, editor, use_stdin):
    """Edit the @string macro definitions and merge the changes back
    into the library (modifies the `.bib` file in place). From a
    terminal, this opens the definitions in `$EDITOR` (or `--editor`).
    Non-interactive callers pass `--stdin` and pipe in the full edited
    definitions instead: obtain the current definitions with `strings
    --bib`, modify them, and pipe them back. Without a terminal,
    `--stdin`, or `--editor`, the command fails immediately instead of
    blocking."""
    editor = _resolve_editor(editor, use_stdin)
    lib = Library(bibfile)
    lib.edit_strings(editor=editor)
    lib.save()
