"""Refreshing an exported plain BibTeX file from a library.

Backs the `update` mode of {meth}`bibdeskparser.Library.export`
(`export --update` on the command line): the target file -- an
earlier export, evolving alongside a paper -- is rewritten in place,
with selected entries replaced by fresh exports from the source
library, new entries appended, and everything else (hand-written
entries, comments, `@string` definitions) preserved.

This module intentionally does not import `bibdeskparser.library`
(which imports this module), to avoid a circular dependency; the
source library is passed in as an argument.
"""

from pathlib import Path

import bibtexparser
from bibtexparser.model import Entry as _RawEntry
from bibtexparser.model import (
    ExplicitComment,
    ImplicitComment,
    ParsingFailedBlock,
    Preamble,
    String,
)

from .entry import Entry, _strip_enclosing
from .exporting import _check_fields, _render_entry, _render_entry_verbatim
from .macros import STANDARD_MACROS
from .middleware import parse_stack, quiet_block_type_logging
from .plain import (
    PlainOptions,
    database_content,
    format_marker,
    leading_marker,
    resolve_plain_options,
)
from .texmap import texify
from .writer import join_plain_pieces

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["update_exported_file"]


def _load_target(path):
    """Read and parse the target file; returns `(text, parsed)`.

    Raises {exc}`FileNotFoundError` if `path` does not exist and
    {exc}`ValueError` if the file is in the database format (naming
    the database content found)."""
    if not path.is_file():
        raise FileNotFoundError(
            f"cannot update {path}: no such file (create a new export "
            "with outfile/--outfile)"
        )
    text = path.read_text(encoding="utf-8")
    with quiet_block_type_logging():
        parsed = bibtexparser.parse_string(text, parse_stack=parse_stack())
    found = database_content(parsed)
    if found:
        raise ValueError(
            f"cannot update {path}: not a plain BibTeX export "
            f"(found {', '.join(found)})"
        )
    return text, parsed


def _updated_strings(parsed, referenced, library_strings):
    """The `@string` definitions of the updated file, as a sorted
    `{name: unicode_value}` dict: the union of the target's existing
    definitions and the definitions `referenced` by the rewritten
    entries, with the library's current value for every macro
    `library_strings` defines, and the target's own value for a macro
    only the target defines. The block only grows or refreshes:
    unused definitions are kept."""
    existing = {
        string.key: _strip_enclosing(string.value) for string in parsed.strings
    }
    names = set(existing) | {
        name for name in referenced if name in library_strings
    }
    return {
        name: library_strings.get(name, existing.get(name))
        for name in sorted(names)
    }


# pylint: disable-next=too-many-locals,too-many-branches
def update_exported_file(
    library,
    path,
    keys,
    *,
    unicode=None,
    expand_strings=None,
    fields="minimal",
    preprint=None,
    marker=True,
):
    """Refresh the exported plain BibTeX file at `path` from
    `library`; see {meth}`bibdeskparser.Library.export` (its `update`
    mode) for the full semantics.

    * `library`: the source {class}`bibdeskparser.Library` (only
      read).
    * `path`: the target file (rewritten in place); must exist and be
      in the plain format.
    * `keys`: the citation keys to update or append; every key must
      exist in `library` (raises {exc}`KeyError` otherwise). With no
      keys, every key in the target that exists in `library` is
      updated.
    * `unicode`, `expand_strings`, `preprint`: `None` (the default)
      resolves to the target file's own options; an explicit value
      overrides them (and is recorded in the marker).
    * `fields`: the field selection for the rewritten entries
      (`bdsk-*` fields are always excluded, whatever it says).
    * `marker`: whether to write a marker line recording the
      effective options (rewriting an existing one, or adding one to
      a marker-less file). With `False`, the file's marker state is
      left untouched.
    """
    path = Path(path)
    text, parsed = _load_target(path)
    fields = _check_fields(fields)
    target_options = resolve_plain_options(
        text, parsed, [Entry._wrap(block) for block in parsed.entries]
    )
    options = PlainOptions(
        unicode=target_options.unicode if unicode is None else unicode,
        expand_strings=(
            target_options.expand_strings
            if expand_strings is None
            else expand_strings
        ),
        preprint=target_options.preprint if preprint is None else preprint,
    )

    target_keys = [block.key for block in parsed.entries]
    keys = list(dict.fromkeys(keys))
    if keys:
        missing = [key for key in keys if key not in library]
        if missing:
            raise KeyError(
                "no such citation key(s) in the source library: "
                + ", ".join(repr(key) for key in missing)
            )
        update_keys = set(keys)
        append_keys = [key for key in keys if key not in target_keys]
    else:
        update_keys = {key for key in target_keys if key in library}
        append_keys = []

    # The macro table for rendering: the library's definitions win
    # over the target's own (that is how corrected values propagate),
    # with the standard month macros as the fallback.
    library_strings = dict(library.strings)
    all_strings = {
        **STANDARD_MACROS,
        **{
            string.key: _strip_enclosing(string.value)
            for string in parsed.strings
        },
        **library_strings,
    }
    referenced = set()
    rendered = {}
    for key in sorted(update_keys):
        entry_text, _ = _render_entry(
            library[key],
            fields,
            options.unicode,
            options.expand_strings,
            all_strings,
            referenced,
            options.preprint,
            skip_bdsk=True,
        )
        rendered[key] = entry_text.rstrip("\n")

    strings = _updated_strings(parsed, referenced, library_strings)
    string_pieces = []
    for name, value in strings.items():
        if not options.unicode:
            value = texify(value)
        string_pieces.append(("string", f"@string{{{name} = {{{value}}}}}"))

    pieces = []
    blocks = list(parsed.blocks)
    if marker:
        pieces.append(("comment", format_marker(options)))
        if leading_marker(parsed) is not None:
            blocks = blocks[1:]  # replaced by the rewritten marker
    strings_placed = False
    for block in blocks:
        if isinstance(block, String):
            # The whole sorted union replaces the first run of
            # `@string` definitions; any later ones fold into it.
            if not strings_placed:
                pieces.extend(string_pieces)
                strings_placed = True
        elif isinstance(block, _RawEntry):
            if not strings_placed and string_pieces:
                # A target without any `@string` block gets the union
                # where an export would put it: above the entries.
                pieces.extend(string_pieces)
                strings_placed = True
            if block.key in update_keys:
                pieces.append(("entry", rendered[block.key]))
            else:
                entry_text = _render_entry_verbatim(
                    Entry._wrap(block),
                    options.unicode,
                    options.expand_strings,
                    all_strings,
                )
                pieces.append(("entry", entry_text.rstrip("\n")))
        elif isinstance(block, ImplicitComment):
            pieces.append(("comment", block.comment))
        elif isinstance(block, ExplicitComment):
            pieces.append(("comment", f"@comment{{{block.comment}}}"))
        elif isinstance(block, Preamble):
            pieces.append(("comment", f"@preamble{{{block.value}}}"))
        elif isinstance(block, ParsingFailedBlock):
            pieces.append(("entry", block.raw))
    if not strings_placed and string_pieces:
        pieces.extend(string_pieces)
    for key in append_keys:
        pieces.append(("entry", rendered[key]))
    path.write_text(join_plain_pieces(pieces), encoding="utf-8")
    return None
