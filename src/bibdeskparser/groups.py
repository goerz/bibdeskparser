"""BibDesk static groups (the `BibDesk Static Groups` `@comment`).

BibDesk stores manually curated ("static") groups in an `@comment` block
at the end of the `.bib` file. The body of that comment is the literal
prefix `BibDesk Static Groups{`, a newline, an Apple XML plist, and a
closing `}`. The plist is an `<array>` of `<dict>`s with two keys:
`group name` (the group's display name) and `keys` (the citation keys of
the group's members, comma-joined). Python's `plistlib` reproduces
BibDesk's exact XML layout (tab indentation, entity escaping), so a
parsed block re-serializes byte-for-byte.

This module holds only pure (de)serialization functions. The decoded
form is a plain `dict` mapping each group name to a `tuple` of citation
keys, in file order; all group *state* (and every mutation of it) lives
in {any}`bibdeskparser.library.Library`.
"""

import plistlib

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "is_static_groups_comment",
    "parse_static_groups",
    "render_static_groups",
]

_STATIC_GROUPS_HEAD = "BibDesk Static Groups{"


def is_static_groups_comment(comment):
    """Check whether a comment body holds a static-groups block.

    ```python
    is_static_groups_comment(comment)
    ```

    Return `True` if `comment` (the string body of an `@comment` block,
    e.g. the `comment` attribute of a bibtexparser `ExplicitComment`) is
    a `BibDesk Static Groups` block that can be parsed with
    `parse_static_groups`. Non-string input yields `False`.

    ```python
    >>> from bibdeskparser.groups import is_static_groups_comment
    >>> is_static_groups_comment("BibDesk Static Groups{...}")
    True
    >>> is_static_groups_comment("some other comment")
    False
    >>> is_static_groups_comment(None)
    False

    ```
    """
    return isinstance(comment, str) and comment.startswith(_STATIC_GROUPS_HEAD)


def parse_static_groups(comment):
    """Parse an `@comment` body of the form `BibDesk Static Groups{...}`.

    ```python
    parse_static_groups(comment)
    ```

    The `...` is a newline, an Apple XML plist, and a final newline; the
    trailing `}` closes the head's opening brace. Return a `dict`
    mapping each group name to a `tuple` of the group's citation keys,
    with both the groups and the keys within each group in file order.

    ```python
    >>> from bibdeskparser.groups import (
    ...     parse_static_groups,
    ...     render_static_groups,
    ... )
    >>> comment = render_static_groups({"My Papers": ("key1", "key2")})
    >>> parse_static_groups(comment)
    {'My Papers': ('key1', 'key2')}

    ```
    """
    # After the head comes `\\n<plist xml>\\n}`; drop the head and the
    # trailing `}`. plistlib requires the `<?xml` declaration at offset
    # 0, so strip the leading newline (render_static_groups re-adds it).
    body = comment[len(_STATIC_GROUPS_HEAD) : comment.rindex("}")]
    array = plistlib.loads(body.lstrip().encode("utf-8"))
    return {
        item["group name"]: (
            tuple(item["keys"].split(",")) if item["keys"] else ()
        )
        for item in array
    }


def render_static_groups(groups):
    """Serialize `groups` to the exact `@comment` body BibDesk writes.

    ```python
    render_static_groups(groups)
    ```

    * `groups`: a `dict` mapping each group name to an iterable of the
      group's citation keys (as returned by `parse_static_groups`).

    The result of parsing a BibDesk-written comment with
    `parse_static_groups` and serializing it again is byte-identical to
    the original.
    """
    array = [
        {"group name": name, "keys": ",".join(keys)}
        for name, keys in groups.items()
    ]
    xml = plistlib.dumps(
        array,
        fmt=plistlib.FMT_XML,  # pylint: disable=no-member
    ).decode("utf-8")
    # plistlib output ends in `</plist>\n`; the head supplies the
    # leading `\n`.
    return f"{_STATIC_GROUPS_HEAD}\n{xml}}}"
