r"""Content search over `Entry` objects.

Provides {func}`search_entries`, the backend for
{meth}`bibdeskparser.Library.search`. For every searched field, three
candidate texts are matched against the query: the stored value (bare
`@string` macro names and braces intact; TeX-encoded when the entry
was populated through the `Entry` dict interface rather than loaded
from a file, whose TeX markup is decoded at parse time), the decoded
Unicode value, and -- for a bare macro reference -- the macro's
expansion. The query itself is additionally detexified, so TeX markup
pasted as a query matches the decoded Unicode values.

The `"exact"`/`"folded"`/`"words"`/`"fuzzy"` match levels form a ladder
(each level matches everything the previous one does, plus more), and
the rung at which an entry matches doubles as its ranking; `"regex"`
sits outside the ladder. See {meth}`bibdeskparser.Library.search` for
the user-facing description of each level.

This module intentionally does not import `bibdeskparser.library`
(which imports this module), to avoid a circular dependency.
"""

import difflib
import re
import unicodedata

from .entry import _is_normal_key
from .macros import MacroString
from .texmap import detexify

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["search_entries"]

#: Valid `match` arguments: the ladder levels (strictest first), plus
#: `"regex"`.
_MATCH_LEVELS = ("exact", "folded", "words", "fuzzy", "regex")

#: Ladder rung enabled as the *loosest* one for each `match` level
#: (`"regex"` bypasses the ladder entirely).
_RUNG_FLOOR = {"exact": 4, "folded": 3, "words": 2, "fuzzy": 1, "regex": 0}

#: Minimum fraction of query words that must occur in a candidate text
#: for a `"words"`/`"fuzzy"` match.
_WORD_OVERLAP_THRESHOLD = 0.7

#: Minimum `difflib.SequenceMatcher` ratio for two word tokens to count
#: as a typo-tolerant match at the `"fuzzy"` level.
#:
#: The ratio is `2 * M / (len_a + len_b)`, where `M` is the number of
#: matching characters, so `0.8` requires the two words to agree on
#: about 80% of their letters. Each single-character error (a wrong,
#: missing, or extra letter) costs roughly `2 / (len_a + len_b)`, so the
#: threshold forgives one such slip in a word of ~5+ letters, and an
#: adjacent transposition (e.g. `theory`/`theroy`) as well. Shorter
#: words tolerate less: a 4-letter word can lose or gain a letter
#: (`gate`/`gates`) but not swap one for another (`gate`/`rate` is
#: 0.75), and a 3-letter word is essentially exact-only. A second typo
#: survives only in long words. The complementary length filter in
#: `_fuzzy_token_match` (skip when the lengths differ by more than 2)
#: rules out the far ends this ratio would otherwise still admit.
#:
#: Lowering the ratio starts pulling in genuinely different words
#: (`cat`/`hat`); raising it rejects common single typos in mid-length
#: words. See the "How to search a library" how-to guide for a table of
#: worked examples.
_FUZZY_RATIO = 0.8

_GERMAN_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

_SS_TRANSLIT = str.maketrans({"ß": "ss"})

_WORD_RE = re.compile(r"\w+")


def _strip_accents(text):
    """`text` with accents dropped (NFKD decomposition, combining marks
    removed) and `ß` mapped to `ss` (which NFKD does not decompose)."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_SS_TRANSLIT))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _fold_variants(text):
    """The folded forms of `text` for accent-insensitive matching.

    Lowercases and then applies both plain accent-stripping
    (`ö` -> `o`) and German-style transliteration (`ö` -> `oe`),
    returning the deduplicated results:

    ```python
    >>> from bibdeskparser.search import _fold_variants
    >>> sorted(_fold_variants("Universität"))
    ['universitaet', 'universitat']

    ```
    """
    # An accented text thus fold-matches both its accent-stripped and
    # its transliterated ASCII spelling. The one pair this does not
    # bridge -- plain-ASCII "schrodinger" vs. literal-ASCII
    # "schroedinger", where neither side has an accent to expand -- is
    # left to the "fuzzy" level (difflib ratio ~0.96).
    low = text.lower()
    return tuple(
        {_strip_accents(low), _strip_accents(low.translate(_GERMAN_TRANSLIT))}
    )


def _tokenize(text):
    """The set of folded word tokens of `text` (the union of `\\w+`
    tokens over all fold variants)."""
    return {
        token
        for variant in _fold_variants(text)
        for token in _WORD_RE.findall(variant)
    }


def _prepare_query(query, match):
    """Precompute the matching data for `query` as a dict.

    Keys: `texts` (lowercased query, as given and detexified, so TeX
    markup pasted as a query still matches decoded values), `variants`
    (fold variants), `tokens` (folded word tokens), `regex` (compiled
    pattern, or `None` unless `match == "regex"`), and `floor` (loosest
    enabled ladder rung).
    """
    texts = {query, detexify(query)}
    regex = None
    if match == "regex":
        try:
            regex = re.compile(query)
        except re.error as exc:
            raise ValueError(
                f"invalid regular expression {query!r}: {exc}"
            ) from exc
    return {
        "texts": tuple({text.lower() for text in texts}),
        "variants": tuple(
            {variant for text in texts for variant in _fold_variants(text)}
        ),
        "tokens": {token for text in texts for token in _tokenize(text)},
        "regex": regex,
        "floor": _RUNG_FLOOR[match],
    }


def _fuzzy_token_match(query_token, tokens):
    """Whether `query_token` approximately matches any of `tokens`
    (`difflib` ratio at least `_FUZZY_RATIO`; exact matches must be
    checked by the caller)."""
    matcher = difflib.SequenceMatcher()
    matcher.set_seq2(query_token)
    for token in tokens:
        if abs(len(token) - len(query_token)) > 2:
            continue
        matcher.set_seq1(token)
        if (
            matcher.real_quick_ratio() >= _FUZZY_RATIO
            and matcher.quick_ratio() >= _FUZZY_RATIO
            and matcher.ratio() >= _FUZZY_RATIO
        ):
            return True
    return False


def _score_text(text, query):
    """The `(rung, fine)` score of the strictest ladder rung at which
    `query` (see `_prepare_query`) matches the candidate `text`, or
    `None`.

    Rungs: exact substring (4), folded substring (3), word overlap
    (2), fuzzy word overlap (1), regex (0); only rungs at or above
    `query["floor"]` are tried. The `fine` component breaks ties
    within a rung: substring coverage of the matched text for rungs
    4/3, the fraction of matched query words for rungs 2/1.
    """
    if query["regex"] is not None:
        # All regex matches rank equal (library order).
        if query["regex"].search(text):
            return (0, 1.0)
        return None
    floor = query["floor"]
    low = text.lower()
    coverage = [
        len(query_text) / len(low)
        for query_text in query["texts"]
        if query_text in low
    ]
    if coverage:
        return (4, min(max(coverage), 1.0))
    if floor > 3:
        return None
    text_variants = _fold_variants(text)
    coverage = [
        len(query_variant) / len(text_variant)
        for query_variant in query["variants"]
        for text_variant in text_variants
        if query_variant in text_variant
    ]
    if coverage:
        return (3, min(max(coverage), 1.0))
    if floor > 2 or not query["tokens"]:
        return None
    text_tokens = _tokenize(text)
    matched = sum(1 for token in query["tokens"] if token in text_tokens)
    fraction = matched / len(query["tokens"])
    if fraction >= _WORD_OVERLAP_THRESHOLD:
        return (2, fraction)
    if floor > 1:
        return None
    matched = sum(
        1
        for token in query["tokens"]
        if token in text_tokens or _fuzzy_token_match(token, text_tokens)
    )
    fraction = matched / len(query["tokens"])
    if fraction >= _WORD_OVERLAP_THRESHOLD:
        return (1, fraction)
    return None


def _candidate_texts(entry, field, strings):
    """The searchable text strings for `field` of `entry`: the raw
    stored value, the decoded Unicode value, and, for a bare `@string`
    macro reference, the macro's expansion (raw and detexified);
    deduplicated, order preserved. The pseudo-field `"key"` yields the
    citation key; a field the entry does not have yields nothing."""
    if field.lower() == "key":
        return [entry.key]
    # Raw values are not reachable through any public `Entry`
    # accessor; both modules are part of the same package, so this
    # reaches across a module boundary but not a public API boundary.
    # pylint: disable=protected-access
    raw_field = entry._find_field(field)
    if raw_field is None or not _is_normal_key(raw_field.key):
        return []
    texts = [str(raw_field.value)]
    decoded = entry[raw_field.key]
    texts.append(str(decoded))
    if isinstance(decoded, MacroString):
        expansion = strings.get(str(decoded))
        if expansion is not None:
            texts.extend([expansion, detexify(expansion)])
    return list(dict.fromkeys(texts))


def _score_entry(entry, query, fields, strings):
    """The best `(rung, fine)` score of `entry` over all candidate
    texts of the selected `fields` (`None` meaning the citation key
    plus all normal fields), or `None` if nothing matches."""
    if fields is None:
        fields = ["key", *entry.keys()]
    best = None
    for field in fields:
        for text in _candidate_texts(entry, field, strings):
            score = _score_text(text, query)
            if score is not None and (best is None or score > best):
                best = score
    return best


def search_entries(
    entries, query, *, strings=None, fields=None, match="words"
):
    """Return the entries among `entries` matching `query`, best match
    first. Backend for {meth}`bibdeskparser.Library.search`, which
    documents the parameters.

    `strings` is a mapping of `@string` macro names to their values
    (e.g. `dict(library.strings)`), used to match against macro
    expansions; without it, bare macro references only match by name.
    """
    if match not in _MATCH_LEVELS:
        raise ValueError(
            f"invalid match level {match!r}: must be one of "
            + ", ".join(repr(level) for level in _MATCH_LEVELS)
        )
    if strings is None:
        strings = {}
    if isinstance(fields, str):
        fields = [fields]
    if fields is not None:
        fields = [field.lower() for field in fields]
    if not query.strip():
        return []
    prepared = _prepare_query(query, match)
    scored = []
    for entry in entries:
        score = _score_entry(entry, prepared, fields, strings)
        if score is not None:
            scored.append((score, entry))
    # `list.sort` is stable (also with `reverse=True`) and the entries
    # are visited in library order, so ties keep the library's order.
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for (score, entry) in scored]
