"""Finding the arXiv preprint that matches a published entry.

Provides {func}`find_preprint`, the free function backing
{meth}`bibdeskparser.Library.add_preprint`: search the arXiv API for
a preprint matching an entry's title/author/DOI/year, and return
either a confident match or a definite "no preprint found". Also
provides {func}`normalize_eprint`, the validation and normalization
of an explicitly given arXiv identifier.

Matching is deliberately conservative (the result is written to the
`.bib` file): a search result is accepted only on an exact DOI match,
a near-exact title match, or a good title match corroborated by the
first author's last name. A title-based match whose arXiv submission
postdates the entry's publication year is rejected unless its journal
reference names that year, guarding against unrelated papers that
share a (generic) title; a genuine late posting of the same paper
carries the original DOI or journal reference, so it still passes.

This module is imported lazily (by `Library.add_preprint`): it pulls
in the network dependencies, which nothing else in the package needs.
A single module-level `arxiv.Client` is shared by all searches, so
its rate limiting (the arXiv API's terms of use ask for no more than
one request every three seconds) spans a whole batch run.
"""

import re
import unicodedata
from collections import namedtuple
from difflib import SequenceMatcher

import arxiv

from .identifiers import _RX_ARXIV_ID, _normalize_doi
from .texmap import detexify

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "PreprintResult",
    "find_preprint",
    "normalize_eprint",
]


#: The result of `find_preprint` (and of `Library.add_preprint`, which
#: sets `applied`); see the `Library.add_preprint` docstring for the
#: meaning of each field. Only a search match carries a non-empty
#: `primaryclass` (the matched preprint's arXiv primary category).
PreprintResult = namedtuple(
    "PreprintResult",
    ["eprint", "match", "ratio", "note", "applied", "primaryclass"],
    defaults=("",),
)

#: Title-similarity ratio accepted on its own.
_RATIO_EXACT = 0.97

#: Title-similarity ratio accepted together with an author match.
_RATIO_FLOOR = 0.92

#: arXiv results to inspect per query.
_MAX_RESULTS = 10

_RX_VERSION = re.compile(r"v\d+$")

#: Non-alphanumeric runs, for the fold-to-ASCII comparison path.
_NONALNUM = re.compile(r"[^a-z0-9]+")

#: Non-word runs, for the unicode-preserving query path. Unlike
#: `_NONALNUM`, `\w` keeps non-ASCII letters, so `sørensen` stays one
#: token instead of shattering into `s`/`rensen`.
_NONWORD = re.compile(r"[^\w]+")

#: Latin letters that Unicode treats as atomic rather than as
#: base-plus-combining-accent, so they have no NFKD decomposition and
#: survive `unicodedata.normalize("NFKD", ...)` unchanged. Folded to
#: ASCII explicitly on the comparison path (see `_deaccent`).
_ATOMIC = str.maketrans(
    {
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ħ": "h",
        "Ħ": "H",
        "ß": "ss",
        "ẞ": "SS",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "Th",
        "ŧ": "t",
        "Ŧ": "T",
        "ı": "i",
        "ŋ": "ng",
        "Ŋ": "Ng",
    }
)


# --------------------------------------------------------------------- #
# Identifier handling
# --------------------------------------------------------------------- #


def normalize_eprint(eprint):
    """Validate `eprint` as an arXiv identifier and return its
    canonical form: a leading `arXiv:` prefix and any version suffix
    (`2409.17398v1` -> `2409.17398`) are stripped; old-style
    identifiers (`quant-ph/9911042`) are kept as-is. Raises
    {exc}`ValueError` if `eprint` is not an arXiv identifier."""
    value = re.sub(r"(?i)^arxiv:\s*", "", (eprint or "").strip())
    if not _RX_ARXIV_ID.match(value):
        raise ValueError(f"not a valid arXiv identifier: {eprint!r}")
    return _RX_VERSION.sub("", value)


def _short_id(result):
    """The canonical arXiv id of a search result, without the version
    suffix (e.g. `1103.6050` or `quant-ph/9911042`)."""
    return _RX_VERSION.sub("", result.get_short_id())


# --------------------------------------------------------------------- #
# Normalization helpers
# --------------------------------------------------------------------- #


def _deaccent(s):
    """Fold accented and atomic Latin letters to ASCII: 'Körner' ->
    'Korner', 'Mølmer' -> 'Molmer', 'Weiß' -> 'Weiss'. Decomposable
    letters lose their combining marks; atomic letters (ø, ł, ß, æ, …,
    which have no NFKD decomposition) are folded via an explicit table.
    Applied on the comparison path so a match is insensitive to how an
    accent is spelled; queries preserve the original letters."""
    s = "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )
    return s.translate(_ATOMIC)


def _clean_text(raw, *, deaccent=True):
    """Strip TeX/braces/math markup from a field value, for building
    queries and comparing titles. Field values are already TeX-decoded
    unicode, but titles may retain brace protection, math (`$...$`),
    and the occasional TeX command, so any `{\\...}` is decoded first.
    With `deaccent` (the default, for comparison) accented and atomic
    letters are folded to ASCII; query construction passes
    `deaccent=False` to preserve the letters, which arXiv's index
    stores literally."""
    if raw is None:
        return ""
    s = detexify(str(raw))
    s = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    s = re.sub(r"\\[^a-zA-Z]", "", s)
    s = s.replace("{", "").replace("}", "").replace("$", "")
    s = s.replace("~", " ").replace("--", "-")
    if deaccent:
        s = _deaccent(s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_title(raw):
    """Collapse a title to lowercase ASCII alphanumeric tokens, for
    fuzzy comparison (accents folded)."""
    return _NONALNUM.sub(" ", _clean_text(raw).lower()).strip()


def _query_norm(raw):
    """Like `_norm_title`, but preserves non-ASCII letters and does not
    fold accents, for building arXiv queries. arXiv's index stores
    title characters literally, so a folded query never matches a
    unicode title. NFC composes any decomposed accent (`o` + combining
    diaeresis) so `\\w` keeps it as one token."""
    s = unicodedata.normalize("NFC", _clean_text(raw, deaccent=False))
    return _NONWORD.sub(" ", s.lower()).strip()


def _first_author_lastname(authors_raw):
    """Best-effort last name of the first author from a bib `author`
    field value."""
    if not authors_raw:
        return ""
    first = re.split(r"\s+and\s+", str(authors_raw).strip())[0]
    first = _clean_text(first)
    if "," in first:  # "Goerz, Michael H"
        lastpart = first.split(",")[0]
    else:  # "Michael H Goerz"
        lastpart = first
    toks = lastpart.split()  # last token: "van der Meer" -> "meer"
    return toks[-1].lower() if toks else ""


def _parse_year(raw):
    """First plausible 4-digit publication year in a bib `year` value,
    or `None`."""
    if not raw:
        return None
    match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", str(raw))
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------- #


def _title_ratio(a, b):
    """Similarity of two titles, in `[0, 1]`."""
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio()


def _doi_eq(a, b):
    """Whether two DOI values are equal (case-insensitive, ignoring a
    trailing slash); `False` if either is empty."""
    if not a or not b:
        return False
    return a.strip().lower().rstrip("/") == b.strip().lower().rstrip("/")


def _author_matches(lastname, result):
    """Whether `lastname` appears among the arXiv result's authors."""
    if not lastname:
        return False
    for author in result.authors:
        toks = _NONALNUM.sub(" ", _deaccent(author.name).lower()).split()
        if lastname in toks:
            return True
    return False


def _result_year(result):
    """Year of a result's first (v1) arXiv submission, or `None`."""
    published = getattr(result, "published", None)
    return published.year if published is not None else None


def _journal_ref_year_matches(result, year):
    """Whether the arXiv result's journal reference names the entry's
    publication year."""
    if not year:
        return False
    journal_ref = getattr(result, "journal_ref", None) or ""
    return str(year) in journal_ref


def _pick_match(title, doi, lastname, results, year=None):
    """Choose the best confident arXiv result among `results`, or
    `None`.

    Acceptance (conservative -- the result is written to the file):

    * the arXiv result's DOI equals the entry DOI -> `"doi"`;
    * title ratio >= `_RATIO_EXACT` -> `"title"`;
    * title ratio >= `_RATIO_FLOOR` and the first author matches
      -> `"title+author"`.

    Returns `(result, ratio, reason)`, or `(None, best_ratio, reason)`
    for no confident match (with an empty `reason`, or
    `"postdated-unverified(<arxiv_year>><entry_year>)"` for a
    title-based match rejected by the postdating guard).
    """
    best = (None, 0.0)
    for result in results:
        ratio = _title_ratio(title, result.title)
        if doi and _doi_eq(doi, getattr(result, "doi", None)):
            # The DOI identifies the paper; accept regardless of date.
            return result, ratio, "doi"
        if ratio > best[1]:
            best = (result, ratio)
    result, ratio = best
    if result is None:
        return None, 0.0, ""
    if ratio >= _RATIO_EXACT:
        reason = "title"
    elif ratio >= _RATIO_FLOOR and _author_matches(lastname, result):
        reason = "title+author"
    else:
        return None, ratio, ""
    # Postdating guard: a title-based acceptance is rejected when the
    # preprint was first submitted more than a year after the entry's
    # publication year, unless its journal reference corroborates that
    # year. This guards against unrelated papers sharing a (generic)
    # title; a genuine late posting of the same paper carries the
    # original DOI (accepted above) or journal reference.
    arxiv_year = _result_year(result)
    if (
        year
        and arxiv_year
        and arxiv_year > year + 1
        and not _journal_ref_year_matches(result, year)
    ):
        return None, ratio, f"postdated-unverified({arxiv_year}>{year})"
    return result, ratio, reason


# --------------------------------------------------------------------- #
# arXiv search
# --------------------------------------------------------------------- #

# The shared client (created on first use). One client for the whole
# process, so that its rate limiting -- `delay_seconds` between any
# two requests, retrying transient errors -- spans batch runs.
_CLIENT = None


def _client():
    """The shared `arxiv.Client`."""
    # pylint: disable=global-statement
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = arxiv.Client(
            page_size=_MAX_RESULTS, delay_seconds=3.0, num_retries=3
        )
    return _CLIENT


def _distinctive_words(title, n=4):
    """The `n` longest, most distinctive title words (deduped, longest
    first). Querying a few long words joined by AND (rather than an
    exact phrase) is robust to minor wording differences -- e.g. a
    published "colour" vs. the arXiv "color" -- while `_pick_match`
    still enforces precision. Pure-ASCII words are preferred (arXiv
    indexes them unambiguously); a non-ASCII word is kept only when
    fewer than three ASCII candidates remain."""
    words = [w for w in _query_norm(title).split() if len(w) >= 4]
    if len(words) < 3:  # very short title: keep everything
        words = _query_norm(title).split()
    ascii_words = [w for w in words if w.isascii()]
    if len(ascii_words) >= 3:
        words = ascii_words
    seen, uniq = set(), []
    for word in sorted(words, key=len, reverse=True):
        if word not in seen:
            seen.add(word)
            uniq.append(word)
    return uniq[:n]


def _build_queries(title, lastname):
    """arXiv `search_query` strings to try in order, precise first:

    1. exact title phrase + author (the common case);
    2. exact title phrase (author listed differently on the preprint);
    3. distinctive title words + author (tolerant of a single
       word/spelling difference);
    4. distinctive title words (last resort).

    Non-ASCII letters are preserved (see `_query_norm`), so a title
    like "Mølmer-Sørensen" produces intact `mølmer`/`sørensen` tokens
    rather than shattered fragments.
    """
    words = _query_norm(title).split()
    if not words:
        return []
    phrase = " ".join(words[:14])
    distinct = " AND ".join(f"ti:{w}" for w in _distinctive_words(title))
    queries = []
    for core in (f'ti:"{phrase}"', distinct):
        if not core:
            continue
        if lastname:
            queries.append(f"{core} AND au:{lastname}")
        queries.append(core)
    seen, out = set(), []
    for query in queries:
        if query not in seen:
            seen.add(query)
            out.append(query)
    return out


def _search(title, lastname):
    """A list of arXiv results for the entry (may raise on a hard
    network/API failure). Tries progressively looser queries (see
    `_build_queries`) and returns the first non-empty result set;
    precision is enforced later by `_pick_match`."""
    for query in _build_queries(title, lastname):
        search = arxiv.Search(query=query, max_results=_MAX_RESULTS)
        results = list(_client().results(search))
        if results:
            return results
    return []


# --------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------- #


def find_preprint(*, title, author=None, doi=None, year=None):
    """Search arXiv for the preprint of the entry described by
    `title`, `author`, `doi`, and `year` (bib field values; all but
    `title` may be `None`); the free function backing
    {meth}`bibdeskparser.Library.add_preprint` (see there for the
    matching semantics).

    Returns a `PreprintResult` with `applied=False`: `eprint` is the
    matched arXiv identifier (`""` if none), `match` is `"doi"`,
    `"title"`, or `"title+author"` for a match, `"none"` for a clean
    no-match, or `"error"` when the search could not run (network/API
    failure, or no usable title); network problems never raise. For a
    match, `primaryclass` is the preprint's arXiv primary category
    (e.g. `"quant-ph"`), `""` otherwise.
    """
    if not title or not _norm_title(title):
        return PreprintResult("", "error", 0.0, "no-title", False)
    lastname = _first_author_lastname(author)
    doi = _normalize_doi(doi)
    year = _parse_year(year)
    try:
        results = _search(title, lastname)
    # pylint: disable-next=broad-except
    except Exception as exc:  # network / parse / API error
        note = f"arxiv-error({exc.__class__.__name__}: {exc})"
        return PreprintResult("", "error", 0.0, note, False)
    if not results:
        return PreprintResult("", "none", 0.0, "no-results", False)
    result, ratio, reason = _pick_match(
        title, doi, lastname, results, year=year
    )
    if result is None:
        note = f"best-ratio={ratio:.2f}"
        if reason:
            note = f"{reason}; {note}"
        return PreprintResult("", "none", ratio, note, False)
    primaryclass = getattr(result, "primary_category", "") or ""
    return PreprintResult(
        _short_id(result), reason, ratio, "", False, primaryclass
    )
