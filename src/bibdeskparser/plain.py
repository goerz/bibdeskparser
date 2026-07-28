"""Detection and bookkeeping for the plain (non-database) `.bib` format.

A `.bib` file is in one of two formats. The *database format* is what
BibDesk writes: a header comment, group `@comment` blocks, `bdsk-*`
fields, and `date-added`/`date-modified` bookkeeping. The *plain
format* is what {meth}`bibdeskparser.Library.export` writes: plain
BibTeX for citing from LaTeX, with none of the above. A loaded file is
in the database format exactly if it contains any database-only
content -- a BibDesk header, any BibDesk group `@comment` block, or
any `bdsk-*` field (see `database_content`); a file with none of
these is plain.

A plain file has three options that affect how it is regenerated and
serialized, collected in a `PlainOptions` record: the value encoding
(Unicode or TeX-encoded), whether `@string` references are expanded,
and the preprint export form. They are resolved once, at load time
(`resolve_plain_options`): from the marker line that every export
writes as the file's first block (`format_marker`/`parse_marker`), or
-- for a file without a marker, e.g. hand-written or from another tool
-- by content heuristics that pick the behavior consistent with the
file's observable state.
"""

import re
from collections import namedtuple

import bibtexparser
from bibtexparser.model import ExplicitComment, ImplicitComment

from .config import active
from .groups import is_groups_comment
from .header import parse_header
from .identifiers import _entry_preprint
from .macros import is_valid_macro_name
from .texmap import skip_texify

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "PlainOptions",
    "format_marker",
    "parse_marker",
    "leading_marker",
    "database_content",
    "resolve_plain_options",
]


#: The options of a plain-format file that affect regeneration and
#: serialization: the value encoding (`unicode`, a bool), whether
#: `@string` references are expanded (`expand_strings`, a bool), and
#: the preprint export form (`preprint`, one of `"unpublished"`,
#: `"misc"`, `"article"`, `"stored"`).
PlainOptions = namedtuple(
    "PlainOptions", ["unicode", "expand_strings", "preprint"]
)


#: Regex matching a marker line (a single-line comment); the
#: vocabulary inside the parentheses is parsed by `parse_marker`.
_MARKER_RE = re.compile(
    r"%% Created by BibDeskParser \((?P<options>[^)]*)\)\.",
    flags=re.IGNORECASE,
)


def format_marker(options):
    """The marker line recording `options` (a `PlainOptions`), e.g.
    `%% Created by BibDeskParser (unicode, preprints as unpublished).`
    (no trailing newline)."""
    parts = ["unicode" if options.unicode else "TeX-encoded"]
    if options.expand_strings:
        parts.append("strings expanded")
    parts.append(f"preprints as {options.preprint}")
    return f"%% Created by BibDeskParser ({', '.join(parts)})."


def parse_marker(comment):
    """Parse `comment` (the text of a comment block) as a marker line.

    Returns the recorded `PlainOptions`, or `None` if `comment` is not
    a (single-line) marker. The vocabulary is parsed case-insensitively:
    `unicode` or `TeX-encoded` for the encoding, `strings expanded`,
    and `preprints as unpublished`/`misc`/`article`/`stored`; any
    unrecognized item disqualifies the marker. An option not named in
    the marker takes its default (Unicode, strings not expanded, the
    configured `preprint_export`).
    """
    match = _MARKER_RE.fullmatch(comment.strip())
    if match is None:
        return None
    unicode_ = True
    expand_strings = False
    preprint = None
    for item in match.group("options").split(","):
        item = item.strip().lower()
        if item == "unicode":
            unicode_ = True
        elif item == "tex-encoded":
            unicode_ = False
        elif item == "strings expanded":
            expand_strings = True
        elif item.startswith("preprints as "):
            form = item[len("preprints as ") :]
            if form not in ("unpublished", "misc", "article", "stored"):
                return None
            preprint = form
        else:
            return None
    if preprint is None:
        preprint = active.preprint_export
    return PlainOptions(unicode_, expand_strings, preprint)


def leading_marker(raw_library):
    """The `PlainOptions` from the marker leading `raw_library` (a
    `bibtexparser.Library`), or `None` if its first block is not a
    marker comment. Only the leading block is recognized; a marker
    anywhere else in the file is an inert comment."""
    blocks = raw_library.blocks
    if blocks and isinstance(blocks[0], ImplicitComment):
        return parse_marker(blocks[0].comment)
    return None


def database_content(raw_library):
    """The database-only content of `raw_library` (a
    `bibtexparser.Library`), as a list of human-readable descriptions.

    An empty list means the file is in the plain format. Checked, in
    order: a BibDesk header comment (as the first block), any BibDesk
    group `@comment` block (static, smart, URL, or script groups), and
    any `bdsk-*` field on any entry. The `date-added`/`date-modified`
    fields are *not* markers: a plain file can legitimately contain
    them (e.g. an entry pasted from a database).
    """
    found = []
    blocks = raw_library.blocks
    if blocks and isinstance(blocks[0], ImplicitComment):
        creator, _ = parse_header(blocks[0].comment)
        if creator is not None:
            found.append("a BibDesk header")
    if any(
        isinstance(block, ExplicitComment) and is_groups_comment(block.comment)
        for block in blocks
    ):
        found.append("BibDesk group data")
    if any(
        field.key.lower().startswith("bdsk-")
        for entry in raw_library.entries
        for field in entry.fields
    ):
        found.append("bdsk-* fields")
    return found


def _is_bare(value):
    """Whether `value` is a string with no enclosing `{...}`/`"..."`
    (a candidate bare macro reference)."""
    return isinstance(value, str) and bool(value) and value[0] not in '{"'


def _detect_unicode(text):
    """Encoding heuristic: whether any TeX-encodable value in the raw
    file `text` contains non-ASCII text.

    Requires a second, middleware-free parse of `text`: the normal
    parse stack detexifies values on read, after which a TeX-encoded
    and a Unicode file are indistinguishable. Fields exempt from TeX
    encoding (URL and `bdsk-*` fields) are ignored, since they can
    hold non-ASCII legitimately in either encoding. An all-ASCII file
    is detected as TeX-encoded; this only matters once a non-ASCII
    value is written, and writing it TeX-encoded is the safe choice
    for such a file.
    """
    if text.isascii():
        # No field value can be non-ASCII; skips the reparse (for a
        # str, isascii() is O(1): CPython stores the flag at creation)
        return False
    raw = bibtexparser.parse_string(text, parse_stack=[])
    for entry in raw.entries:
        for field in entry.fields:
            if skip_texify(field.key):
                continue
            if isinstance(field.value, str) and not field.value.isascii():
                return True
    return any(
        isinstance(string.value, str) and not string.value.isascii()
        for string in raw.strings
    )


def _detect_expanded(raw_library):
    """Strings heuristic: whether the file shows no macro usage at all
    -- no `@string` definitions and no bare macro references (the
    `keywords` field and the URL/`bdsk-*` fields are ignored, the same
    exemption the parser applies when recognizing macro references).

    A macro-free file is treated as expanded, so it stays macro-free,
    with values inlined for updated entries. A file whose only macro
    usage is a standard month reference like `month = jan` counts as
    using macros (such references never come with a definition, since
    the month macros are built in, which is why the presence of
    definitions alone would be the wrong test).
    """
    if raw_library.strings:
        return False
    for entry in raw_library.entries:
        for field in entry.fields:
            if field.key.lower() == "keywords" or skip_texify(field.key):
                continue
            value = field.value
            if _is_bare(value) and is_valid_macro_name(value, normalized=True):
                return False
    return True


def _detect_preprint(entries):
    """Preprint-form heuristic: the stored entry type of the file's
    preprint-only entries (recognized exactly as in exporting),
    provided they are all of one consistent type; the configured
    `preprint_export` with no preprint-only entries, or mixed types.
    The `stored` form is never detected: a `stored` export of a
    library whose canonical form is `@unpublished` is indistinguishable
    from an `unpublished`-form export, and detecting `unpublished`
    yields the same update output.

    * `entries`: the file's entries, as
      {class}`bibdeskparser.entry.Entry` objects.
    """
    types = set()
    for entry in entries:
        if _entry_preprint(entry, active.preprint_archives) is not None:
            types.add(entry.entry_type.lower())
    if len(types) == 1:
        form = types.pop()
        if form in ("unpublished", "misc", "article"):
            return form
    return active.preprint_export


def resolve_plain_options(text, raw_library, entries):
    """Resolve the `PlainOptions` of a plain-format file.

    * `text`: the raw file text (as read from disk).
    * `raw_library`: the parsed `bibtexparser.Library` (through the
      normal parse stack).
    * `entries`: the file's entries, as
      {class}`bibdeskparser.entry.Entry` objects.

    From the marker line, if the file leads with one; else by the
    content heuristics (`_detect_unicode`, `_detect_expanded`,
    `_detect_preprint`), each choosing the behavior consistent with
    the file's observable state.
    """
    options = leading_marker(raw_library)
    if options is not None:
        return options
    return PlainOptions(
        unicode=_detect_unicode(text),
        expand_strings=_detect_expanded(raw_library),
        preprint=_detect_preprint(entries),
    )
