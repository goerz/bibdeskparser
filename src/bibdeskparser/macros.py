r"""Validation and normalization of BibDesk macro (`@string`) names.

BibDesk restricts the names of macros (BibTeX `@string` definitions) to a
subset of printable ASCII and treats them case-insensitively: its macro
editor forces names to lowercase as they are typed, and its macro table
(`BDSKMacroResolver`) looks names up by their lowercased form. This module
replicates those rules.
"""

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["is_valid_macro_name", "normalize_macro_name"]

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
      by {any}`normalize_macro_name`. If `False`, the empty string is
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

    Raises {any}`ValueError` if `name` is empty or is not a valid macro
    name according to {any}`is_valid_macro_name`.

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
