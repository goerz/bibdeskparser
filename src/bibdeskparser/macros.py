r"""BibDesk macro (`@string`) names and macro-aware field values.

BibDesk restricts the names of macros (BibTeX `@string` definitions) to a
subset of printable ASCII and treats them case-insensitively: its macro
editor forces names to lowercase as they are typed, and its macro table
(`BDSKMacroResolver`) looks names up by their lowercased form. This module
replicates those rules, and defines the {class}`ValueString` /
{class}`MacroString` marker types that force a field value to be stored
as a literal braced string or as a bare macro reference, respectively.
"""

# ValueString and MacroString are re-exported from the top-level
# `bibdeskparser` package, which is their public (documented) location.
__all__ = ["ValueString", "MacroString"]

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "is_valid_macro_name",
    "normalize_macro_name",
    "STANDARD_MACROS",
]

# BibDesk's built-in "standard" macros: exactly the twelve BibTeX month
# macros, and nothing else (`standardMacroDefinitions` in
# `BDSKMacroResolver.m`). BibDesk maps them to the localized full month
# names; we use the (deterministic) English names, which is also what
# the standard BibTeX style `plain.bst` defines. These are a
# lowest-priority *fallback* for resolving a bare reference, never part
# of `Library.strings` and never written to the `.bib` file. A
# `@string` definition of the same name is an ordinary macro -- it
# overrides the fallback (as in BibTeX/BibDesk, where a `.bib`
# `@string` beats a `.bst`/built-in definition) and round-trips through
# `Library.strings` and save like any other macro.
STANDARD_MACROS = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "may": "May",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}

# Characters BibDesk allows in a field/macro name. Built exactly as
# `invalidCiteKeyCharSet` in `BDSKTypeManager.m` (which
# `invalidFieldNameCharacterSet` aliases): start from printable ASCII
# 32..125, then remove the BibTeX separators/specials. Everything outside
# this set (control chars, `~`, and all non-ASCII) is invalid.
_MACRO_NAME_CHARS = frozenset(chr(c) for c in range(32, 126)) - set(
    " '\"@,\\#}{~%()="
)


def is_valid_macro_name(name, normalized=True):
    r"""Return whether `name` is a valid BibDesk macro (`@string`) name.

    ```python
    is_valid_macro_name(name, normalized=True)
    ```

    Mirrors `-[BDSKMacroTextViewController isPartialStringValid:...]`: a
    name is valid iff every character is in BibDesk's allowed set (printable
    ASCII 32..125 minus the BibTeX separators/specials `` '"@,\#}{~%()=``
    and the space character) and it does not begin with a decimal digit.

    * `name`: the macro name to check.
    * `normalized`: if `True` (default), `name` must additionally be
      non-empty and already lowercase, i.e. in the canonical form produced
      by {func}`normalize_macro_name`. If `False`, the empty string is
      accepted (BibDesk permits it as an in-progress edit) and uppercase
      letters are allowed.

    ```python
    >>> from bibdeskparser.macros import is_valid_macro_name
    >>> is_valid_macro_name("pra")
    True
    >>> is_valid_macro_name("bad name")  # space is not allowed
    False
    >>> is_valid_macro_name("2pac")  # must not start with a digit
    False
    >>> is_valid_macro_name("PRA")  # not lowercase
    False
    >>> is_valid_macro_name("PRA", normalized=False)
    True

    ```
    """
    if any(ch not in _MACRO_NAME_CHARS for ch in name):
        return False
    if name and name[0].isascii() and name[0].isdigit():
        return False
    if normalized:
        if not name:
            return False
        if name != name.lower():
            return False
    return True


def normalize_macro_name(name):
    """Return the BibDesk-canonical form of a macro name.

    ```python
    normalize_macro_name(name)
    ```

    BibDesk's macro editor forces names to lowercase as they are typed
    (`*partialStringPtr = [partialString lowercaseString]`) while rejecting
    any input that contains a disallowed character or starts with a digit.
    This returns the lowercased name that BibDesk would store, matching its
    case-insensitive macro table (`BDSKMacroResolver`), so two names that
    differ only in case normalize to the same key.

    * `name`: the macro name as written (e.g. from a parsed `@string`
      block).

    Raises {exc}`ValueError` if `name` is empty or is not a valid macro
    name according to {func}`is_valid_macro_name`.

    ```python
    >>> from bibdeskparser.macros import normalize_macro_name
    >>> normalize_macro_name("PRA")
    'pra'
    >>> normalize_macro_name("pra")
    'pra'
    >>> normalize_macro_name("bad name")
    Traceback (most recent call last):
        ...
    ValueError: invalid BibDesk macro name: 'bad name'

    ```
    """
    if not name:
        raise ValueError("macro name must not be empty")
    if not is_valid_macro_name(name, normalized=False):
        raise ValueError(f"invalid BibDesk macro name: {name!r}")
    return name.lower()


class ValueString(str):
    r"""Force a field value to be stored as a braced BibTeX string.

    ```python
    ValueString(value)
    ```

    A plain `str` value assigned via `entry[field] = value` is stored
    bare (no enclosing `{...}`) when it happens to be a valid,
    normalized BibDesk macro name, since such a value is ambiguous
    with a reference to a `@string` macro of that name. Wrap the
    value in `ValueString` to force it to be treated as literal text
    instead, even though it would otherwise pass as a macro name.

    `ValueString` is the mirror image of {class}`MacroString`, which
    forces the opposite (bare `@string` macro reference) storage. Both
    return the same value through the `dict` interface -- the
    difference is only in how the value is *stored* (as a literal
    braced string vs. a bare macro reference), visible in the `"raw"`
    export format (see {meth}`Library.export`):

    ```python
    >>> from bibdeskparser import Entry, Library, ValueString
    >>> bib = Library()
    >>> entry = Entry("article", "Key2024")
    >>> entry["journal"] = ValueString("prl")  # forced literal text
    >>> entry["journal"]
    'prl'
    >>> bib["Key2024"] = entry
    >>> bib.export("Key2024", format="raw") == (
    ...     "@article{Key2024,\n\tjournal = {prl}\n}\n"
    ... )
    True
    >>> entry["journal"] = "prl"  # bare str: treated as a macro ref
    >>> entry["journal"]
    'prl'
    >>> bib.export("Key2024", format="raw") == (
    ...     "@article{Key2024,\n\tjournal = prl\n}\n"
    ... )
    True

    ```
    """

    __slots__ = ()


class MacroString(str):
    r"""Force a field value to be stored as a bare `@string` macro
    reference.

    ```python
    MacroString(value)
    ```

    A plain `str` value assigned via `entry[field] = value` is already
    stored as a bare macro reference whenever it looks like a valid
    macro name (e.g. `entry["journal"] = "prl"` stores `journal = prl`).
    Wrapping the value in `MacroString` makes that intent explicit and
    forces bare-macro storage even in code that cannot rely on the
    value's shape. The macro name is validated (it must be a valid,
    normalized BibDesk macro name), so an invalid name raises
    {exc}`ValueError`. To force the opposite -- a literal braced value
    for a macro-shaped string -- wrap it in {class}`ValueString`.

    `MacroString` is the mirror image of {class}`ValueString`, which
    forces the opposite (literal braced) storage. Both return the same
    value through the `dict` interface -- the difference is only in how
    the value is *stored* (as a bare macro reference vs. a literal
    braced string), visible in the `"raw"` export format (see
    {meth}`Library.export`):

    ```python
    >>> from bibdeskparser import Entry, Library, MacroString
    >>> bib = Library()
    >>> entry = Entry("article", "Key2024")
    >>> entry["journal"] = MacroString("prl")  # forced macro reference
    >>> entry["journal"]
    'prl'
    >>> bib["Key2024"] = entry
    >>> bib.export("Key2024", format="raw") == (
    ...     "@article{Key2024,\n\tjournal = prl\n}\n"
    ... )
    True

    ```
    """

    __slots__ = ()
