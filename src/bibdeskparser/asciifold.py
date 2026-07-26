"""Rendering Latin text as ASCII.

Provides {func}`fold_to_ascii`, the fold shared by everything in the
package that has to compare or emit text as ASCII: generated citation
keys ({mod}`bibdeskparser.specifiers`), the accent-insensitive match
level of {meth}`bibdeskparser.Library.search`, and the comparison of
an arXiv result against an entry ({mod}`bibdeskparser.preprints`).

A letter accented in the usual sense (`ü`, `ğ`, `ř`) decomposes into a
base letter plus a combining mark, and folding it is a matter of
dropping the mark. A letter whose modification is part of the glyph
(`ł`, `ı`, `ø`) does not decompose, and the base letter has to come
from somewhere else; this module reads it off the Unicode character
name, so that the fold covers every such letter rather than the ones
someone thought to write down.
"""

import functools
import re
import unicodedata

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["fold_to_ascii"]


# Letters whose compatibility decomposition spells the modification as
# standalone punctuation rather than folding it away: `ŀ` decomposes to
# `l` plus a MIDDLE DOT, `ŉ` to `n` preceded by a MODIFIER LETTER
# APOSTROPHE. Resolved before NFKD, so the punctuation never appears.
_PUNCTUATED = {
    0x013F: "L",  # L with middle dot (Catalan)
    0x0140: "l",
    0x0149: "n",  # n preceded by apostrophe (Afrikaans)
}

# Letters that render as more than one ASCII letter, or whose Unicode
# name would mislead `_BASE_LETTER_RX` ("LATIN SMALL LETTER SHARP S"
# would give `s`, not `ss`). Applied before the name derivation.
#
# Ligatures with a compatibility decomposition (`ĳ`, `ﬁ`) are absent on
# purpose: NFKD already spells them out.
_EXPANSIONS = {
    0x00C6: "AE",
    0x00E6: "ae",
    0x0152: "OE",
    0x0153: "oe",
    0x00DF: "ss",
    0x1E9E: "SS",
    0x00DE: "TH",
    0x00FE: "th",
    0xA732: "AA",
    0xA733: "aa",
    0xA734: "AO",
    0xA735: "ao",
    0xA736: "AU",
    0xA737: "au",
    0xA738: "AV",
    0xA739: "av",
    0xA73A: "AV",
    0xA73B: "av",
    0xA73C: "AY",
    0xA73D: "ay",
    0xA74E: "OO",
    0xA74F: "oo",
    0xA728: "TZ",
    0xA729: "tz",
    0xA760: "VY",
    0xA761: "vy",
    0x1D6B: "ue",
}

# The base letter of a Latin letter, read off its Unicode name: a lone
# letter, optionally preceded by qualifiers and followed by a `WITH ...`
# tail.
#
#   "LATIN SMALL LETTER L WITH STROKE"   -> l   (ł)
#   "LATIN SMALL LETTER DOTLESS I"       -> i   (ı)
_BASE_LETTER_RX = re.compile(
    r"^LATIN (SMALL|CAPITAL) LETTER (?:[A-Z]+ )*?([A-Z])(?: WITH .*)?$"
)

# Latin letters whose Unicode name carries no base letter at all, so
# `_BASE_LETTER_RX` cannot fold them.
_NAMED_LETTERS = {
    "Ð": "D",  # eth (Icelandic)
    "ð": "d",
    "ĸ": "k",  # kra (Greenlandic)
    "Ŋ": "NG",  # eng (Northern Sami)
    "ŋ": "ng",
    "Ə": "E",  # schwa (Azerbaijani)
    "ə": "e",
}


# Cached because the fold runs over whole field values (an abstract
# with a handful of math symbols is long and common), and the domain is
# bounded by the distinct characters a library actually contains.
@functools.lru_cache(maxsize=None)
def _fold_char(char):
    """The ASCII rendering of a single character, or the character
    itself if it has none."""
    if char.isascii():
        return char
    match = _BASE_LETTER_RX.match(unicodedata.name(char, ""))
    if match is not None:
        base = match.group(2)
        return base if match.group(1) == "CAPITAL" else base.lower()
    return _NAMED_LETTERS.get(char, char)


def fold_to_ascii(text):
    """`text` with every Latin letter rendered as its ASCII base
    letter.

    ```python
    >>> from bibdeskparser.asciifold import fold_to_ascii
    >>> fold_to_ascii("Kılıç")
    'Kilic'
    >>> fold_to_ascii("Mølmer")
    'Molmer'
    >>> fold_to_ascii("Weiß")
    'Weiss'

    ```

    Accents are dropped, ligatures and digraphs are spelled out
    (`æ` -> `ae`, `ǆ` -> `dz`), and a letter carrying its modification
    in the glyph becomes its base letter (`ø` -> `o`, `ł` -> `l`).

    A character with no ASCII rendering is left alone rather than
    deleted, so a value in a non-Latin script survives the fold intact
    and can still be matched against itself. Callers that need
    guaranteed ASCII (citation keys) drop what is left over
    themselves.
    """
    if text.isascii():
        return text
    # A compatibility decomposition covers ligatures and digraphs
    # (ǆ -> dz), which have no base letter in their Unicode name.
    decomposed = unicodedata.normalize("NFKD", text.translate(_PUNCTUATED))
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    expanded = stripped.translate(_EXPANSIONS)
    return "".join(_fold_char(char) for char in expanded)
