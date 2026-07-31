"""BibDesk document info (the `@bibdesk_info` block).

BibDesk stores database-level metadata -- the key/value pairs of its
"Document Info" panel -- in a single `@bibdesk_info` block between the
header comment and the `@string` definitions:

```
@bibdesk_info{document_info,
        primary_topics = {Quantum Control, Numerics}
}
```

The block has the syntactic shape of an entry (`document_info` is a
fixed pseudo-key that BibDesk ignores on read), so `bibtexparser`'s
splitter produces an `Entry` for it. It is not one: exposing it
through {class}`bibdeskparser.library.Library`'s entry API would let
entry operations corrupt it (date stamping, entry-style serialization
with the closing brace fused onto the last field line, audits of its
"fields"). BibDesk also serializes it differently from entries: the
closing brace goes on its own line, and -- unlike entry fields and
`@string` values -- the values are written without TeX conversion
(BibDesk's parser de-TeXifies them on read, though, so `_parse_info`
does the same).

`_DocumentInfoMiddleware` (part of
{func}`bibdeskparser.middleware.parse_stack`, running before every
other middleware) therefore replaces each such block with a
`_BibDeskInfo` block carrying both the parsed key/value `data` and the
raw source slice; the writer emits that slice verbatim, so an
unmodified block round-trips byte-for-byte, exactly as BibDesk wrote
it. {attr}`bibdeskparser.library.Library.info` exposes the data for
reading and writing; a mutation regenerates the raw slice in BibDesk's
own layout (`_render_info`).
"""

from bibtexparser.middlewares.middleware import BlockMiddleware
from bibtexparser.model import Block, Entry, ParsingFailedBlock

from .entry import _strip_enclosing
from .macros import is_valid_macro_name
from .texmap import detexify

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = []


class _BibDeskInfo(Block):
    """A `@bibdesk_info` block.

    `data` holds the block's key/value pairs (keys in stored case and
    order, values as Unicode `str`); the inherited `raw` attribute
    holds the block's source text, which the writer emits verbatim.
    `update` regenerates `raw` from new data, in BibDesk's own layout.
    """

    def __init__(self, data, raw=None, start_line=None):
        if raw is None:
            raw = _render_info(data)
        super().__init__(start_line=start_line, raw=raw)
        self.data = data

    def update(self, data):
        """Replace `data`, regenerating `raw` (`_render_info`)."""
        self.data = data
        self._raw = _render_info(data)


def _render_info(data):
    """Render the key/value pairs `data` as a `@bibdesk_info` block.

    Reproduces BibDesk's own layout (`BibDocument.m`,
    `documentInfoString`): the fixed pseudo-key `document_info`, one
    tab-indented `<key> = {<value>}` line per key, and the closing
    brace on its own line. Values are written as-is (BibDesk does not
    TeX-convert document-info values, while its parser -- and
    `_parse_info` -- de-TeXifies on read, so a TeX-escaped value like
    `\\o` is deliberately lossy toward Unicode once the block is
    regenerated, exactly as over a BibDesk load/save cycle)."""
    lines = "".join(f",\n\t{key} = {{{value}}}" for key, value in data.items())
    return "@bibdesk_info{document_info" + lines + "\n}"


def _parse_info(entry):
    """The key/value pairs of a `@bibdesk_info` block, parsed (as an
    `Entry`, see `_is_document_info_entry`) into a `dict`.

    Mirrors BibDesk's read behavior: the `document_info` pseudo-key is
    ignored (it is the entry's citation key, not a field), values are
    de-TeXified, and for keys differing only in case the last value
    wins (BibDesk's map is case-insensitive), under the first-seen
    spelling."""
    data = {}
    for field in entry.fields:
        key = _stored_key(data, field.key) or field.key
        data[key] = detexify(_strip_enclosing(field.value))
    return data


def _stored_key(data, key):
    """The key of `data` (a `dict`) equal to the string `key` up to
    case, or `None` if there is none."""
    lower = key.lower()
    for stored in data:
        if stored.lower() == lower:
            return stored
    return None


def _check_info_key(key):
    """Validate `key` as a document-info key, raising {exc}`TypeError`
    or {exc}`ValueError`.

    BibDesk's Document Info panel accepts any key, but a key that is
    not a valid BibTeX field name would produce a file BibDesk cannot
    read back, so the same character set as for macro names is
    enforced (printable ASCII minus BibTeX's separators/specials, no
    leading digit)."""
    if not isinstance(key, str):
        raise TypeError(f"document-info key must be a str, not {type(key)}")
    if not key or not is_valid_macro_name(key, normalized=False):
        raise ValueError(f"invalid document-info key: {key!r}")


def _check_info_value(value):
    """Validate `value` as a document-info value, raising
    {exc}`TypeError` or {exc}`ValueError`.

    Values are plain `str` (the empty string is allowed, matching
    BibDesk). Since values are written brace-delimited, braces inside
    a value must balance, or the written file could not be read
    back."""
    if not isinstance(value, str):
        raise TypeError(
            f"document-info value must be a str, not {type(value)}"
        )
    depth = 0
    for char in value:
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth < 0:
            break
    if depth != 0:
        raise ValueError(
            f"unbalanced braces in document-info value: {value!r}"
        )


def _is_document_info_entry(block):
    """Whether `block` is an `Entry` parsed from a `@bibdesk_info`
    block."""
    return (
        isinstance(block, Entry) and block.entry_type.lower() == "bibdesk_info"
    )


class _DocumentInfoMiddleware(BlockMiddleware):
    """Middleware replacing `@bibdesk_info` blocks (*read*).

    Replaces each entry-shaped `@bibdesk_info` block with a
    `_BibDeskInfo` block carrying the parsed data and the verbatim
    source. Must run before any middleware that transforms entry
    fields, so those never touch the block."""

    def transform_entry(self, entry, library):
        """Turn a `@bibdesk_info` "entry" into a `_BibDeskInfo` block
        (all other entries pass through unchanged)."""
        if _is_document_info_entry(entry):
            return _BibDeskInfo(
                _parse_info(entry), raw=entry.raw, start_line=entry.start_line
            )
        return entry

    def transform_block(self, block, library):
        """Additionally unwrap a `@bibdesk_info` block that the
        splitter marked as a duplicate-key error: all `@bibdesk_info`
        blocks share the pseudo-key `document_info`, so in a file with
        several, every block after the first is wrapped this way
        before this middleware can see it. (The base class dispatches
        entries to `transform_entry` but has no hook for failed
        blocks.)"""
        if isinstance(block, ParsingFailedBlock):
            wrapped = block.ignore_error_block
            if _is_document_info_entry(wrapped):
                return _BibDeskInfo(
                    _parse_info(wrapped),
                    raw=block.raw,
                    start_line=block.start_line,
                )
        return super().transform_block(block, library)
