r"""Bibtexparser middlewares replicating BibDesk's read/write conversion.

BibDesk normalizes `.bib` data when reading and writing: on *read*, TeX
accents in field and `@string` values are decoded to Unicode
(`detexify`), and `bdsk-file-N` field values are base64-encoded binary
plists (see {class}`bibdeskparser.bdskfile.BibDeskFile`). On *write*,
Unicode is re-encoded as TeX (`texify`). The `BibDesk Static Groups`
`@comment` is not handled here: its body stays a plain string, which
{class}`bibdeskparser.library.Library` decodes and re-encodes itself
(see `bibdeskparser.groups`).

This module packages those conversions as `bibtexparser` "block
middleware" classes (see the
[bibtexparser documentation](https://bibtexparser.readthedocs.io)).
Use `parse_stack` to get the standard read stack:

```python
>>> import bibtexparser
>>> from bibdeskparser.middleware import parse_stack
>>> library = bibtexparser.parse_string(
...     '@article{key1, author = {Gr{\\"u}n, Anna}}',
...     parse_stack=parse_stack(),
... )
>>> library.entries[0]["author"]
'{Grün, Anna}'

```
"""

from bibtexparser.middlewares.middleware import BlockMiddleware

from .bdskfile import BibDeskFile
from .macros import is_valid_macro_name
from .texmap import detexify, skip_texify, texify

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "NormalizeMacroNamesMiddleware",
    "DeTeXifyMiddleware",
    "TeXifyMiddleware",
    "BibDeskFileMiddleware",
    "parse_stack",
]


class NormalizeMacroNamesMiddleware(BlockMiddleware):
    r"""Middleware lowercasing `@string` macro names (*read*).

    ```python
    NormalizeMacroNamesMiddleware(allow_inplace_modification=True)
    ```

    Lowercases the name of every `@string` definition, and every bare
    (unbraced/unquoted) field value that is shaped like a valid macro
    name -- i.e., every candidate `@string` reference. BibDesk's macro
    table is case-insensitive (`BDSKMacroResolver` hashes names
    case-insensitively), so `@string{JAN = ...}` defines the same
    macro as `@string{jan = ...}`, and a field value `month = JAN`
    references it. Normalizing both sides to BibDesk's canonical
    lowercase form once, at parse time, lets every later macro lookup
    be a plain (case-sensitive) `dict` operation.

    The `keywords` field is exempt (a bare keywords value is literal
    text, never a macro reference), as are the URL and `bdsk-*` fields
    for which `skip_texify` is `True` (their values are never macro
    references, and their case must not be mangled).

    * `allow_inplace_modification`: if `True` (default), transform the
      given library's blocks in place instead of copying them (see the
      `bibtexparser` `Middleware` base class).
    """

    def transform_entry(self, entry, library):
        """Lowercase all bare macro-reference field values of
        `entry`."""
        for field in entry.fields:
            value = field.value
            # A braced/quoted value can never pass the macro-name
            # check: `{`, `}`, and `"` are not valid name characters.
            if (
                isinstance(value, str)
                and value
                and field.key.lower() != "keywords"
                and not skip_texify(field.key)
                and is_valid_macro_name(value, normalized=False)
            ):
                field.value = value.lower()
        return entry

    def transform_string(self, string, library):
        """Lowercase the name of the `@string` definition `string`."""
        string.key = string.key.lower()
        return string


class DeTeXifyMiddleware(BlockMiddleware):
    r"""Middleware converting TeX markup to Unicode (*read*).

    ```python
    DeTeXifyMiddleware(allow_inplace_modification=True)
    ```

    Applies `detexify` to every string field value of every entry
    (e.g., `Gr{\"u}n` becomes `Grün`), and to the value of every
    `@string` definition. Field keys for which `skip_texify` is `True`
    (URL and `bdsk-file` fields) are left untouched, as are non-string
    values.

    This replicates the `-stringByDeTeXifyingString:` normalization
    that BibDesk applies to every field value on read.

    * `allow_inplace_modification`: if `True` (default), transform the
      given library's blocks in place instead of copying them (see the
      `bibtexparser` `Middleware` base class).
    """

    def transform_entry(self, entry, library):
        """Detexify all string field values of `entry`."""
        for field in entry.fields:
            if not skip_texify(field.key) and isinstance(field.value, str):
                field.value = detexify(field.value)
        return entry

    def transform_string(self, string, library):
        """Detexify the value of the `@string` definition `string`."""
        if isinstance(string.value, str):
            string.value = detexify(string.value)
        return string


class TeXifyMiddleware(BlockMiddleware):
    r"""Middleware converting Unicode to TeX markup (*write*).

    ```python
    TeXifyMiddleware(allow_inplace_modification=True)
    ```

    The mirror image of `DeTeXifyMiddleware`: applies `texify` to every
    string field value of every entry (e.g., `Grün` becomes
    `Gr{\"u}n`), and to the value of every `@string` definition. Field
    keys for which `skip_texify` is `True` (URL and `bdsk-file` fields)
    are left untouched, as are non-string values (such as
    {class}`bibdeskparser.bdskfile.BibDeskFile` objects).

    This replicates the `-stringByTeXifyingString:` normalization that
    BibDesk applies to every field value on write. It is typically used
    with `allow_inplace_modification=False` so that serializing a
    library does not modify the caller's Unicode model.

    * `allow_inplace_modification`: if `True` (default), transform the
      given library's blocks in place instead of copying them (see the
      `bibtexparser` `Middleware` base class).
    """

    def transform_entry(self, entry, library):
        """Texify all string field values of `entry`."""
        for field in entry.fields:
            if not skip_texify(field.key) and isinstance(field.value, str):
                field.value = texify(field.value)
        return entry

    def transform_string(self, string, library):
        """Texify the value of the `@string` definition `string`."""
        if isinstance(string.value, str):
            string.value = texify(string.value)
        return string


class BibDeskFileMiddleware(BlockMiddleware):
    """Middleware decoding `bdsk-file-N` field values (*read*).

    ```python
    BibDeskFileMiddleware(allow_inplace_modification=True)
    ```

    Replaces the string value of every field whose (lowercased) key
    starts with `bdsk-file-` with the decoded
    {class}`bibdeskparser.bdskfile.BibDeskFile` object. The writer
    serializes such objects back via
    {meth}`bibdeskparser.bdskfile.BibDeskFile.to_field_value`, which is
    byte-exact for unmodified attachments.

    * `allow_inplace_modification`: if `True` (default), transform the
      given library's blocks in place instead of copying them (see the
      `bibtexparser` `Middleware` base class).
    """

    def transform_entry(self, entry, library):
        """Decode all `bdsk-file-N` field values of `entry`."""
        for field in entry.fields:
            is_file_field = field.key.lower().startswith("bdsk-file-")
            if is_file_field and isinstance(field.value, str):
                field.value = BibDeskFile.from_field_value(field.value)
        return entry


def parse_stack():
    """Return the standard middleware stack for reading BibDesk files.

    ```python
    parse_stack()
    ```

    Returns a list of fresh middleware instances,

    ```python
    [
        NormalizeMacroNamesMiddleware(),
        DeTeXifyMiddleware(),
        BibDeskFileMiddleware(),
    ]
    ```

    suitable as the `parse_stack` argument of
    `bibtexparser.parse_string` or `bibtexparser.parse_file`. Passing
    an explicit stack (instead of `None`) also disables bibtexparser's
    default middlewares, so values stay verbatim otherwise: `@string`
    macros are not interpolated and enclosing braces are kept, exactly
    like BibDesk's internal model.
    """
    return [
        NormalizeMacroNamesMiddleware(),
        DeTeXifyMiddleware(),
        BibDeskFileMiddleware(),
    ]
