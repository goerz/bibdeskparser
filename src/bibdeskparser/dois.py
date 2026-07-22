"""Finding the DOI of a published entry.

Provides {func}`find_doi`, the free function backing
{meth}`bibdeskparser.Library.add_doi`: look up the DOI recorded on
arXiv for the entry's `eprint`, or search Crossref for a work matching
the entry's title/author/year, and return either a confident match or
a definite "no DOI found". Also provides {func}`normalize_doi`, the
validation and normalization of an explicitly given DOI.

Matching is deliberately conservative (the result is written to the
`.bib` file): a Crossref search result is accepted only on a
near-exact title match, or a good title match corroborated by the
first author's last name. A title-based match whose publication year
differs from the entry's `year` by more than one is rejected, and an
amendment record (an erratum, corrigendum, retraction, comment, or
reply, whose title embeds the original title) never matches an entry
that is not itself an amendment.

This module is imported lazily (by `Library.add_doi`): it pulls in
the network client libraries, which nothing else in the package
needs. The arXiv lookup shares `bibdeskparser.preprints`' rate-limited
`arxiv.Client`.
"""

import re
from collections import namedtuple

import arxiv
from habanero import Crossref

from .identifiers import _RX_ARXIV_ID, _normalize_doi, _strip_eprint_version
from .preprints import (
    _NONALNUM,
    _RATIO_EXACT,
    _RATIO_FLOOR,
    _clean_text,
    _client,
    _deaccent,
    _first_author_lastname,
    _norm_title,
    _parse_year,
    _title_ratio,
)

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "DoiResult",
    "find_doi",
    "normalize_doi",
]


#: The result of `find_doi` (and of `Library.add_doi`, which sets
#: `applied`); see the `Library.add_doi` docstring for the meaning of
#: each field.
DoiResult = namedtuple(
    "DoiResult", ["doi", "match", "ratio", "note", "applied"]
)

#: Crossref results to inspect per query.
_MAX_RESULTS = 10

#: The item fields requested from Crossref (`select` keeps the
#: response payload small; abstracts in particular are large).
_SELECT = ["DOI", "title", "author", "issued"]

_RX_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


# --------------------------------------------------------------------- #
# Identifier handling
# --------------------------------------------------------------------- #


def normalize_doi(doi):
    """Validate `doi` as a DOI and return its canonical form: a
    leading `doi:` prefix or `https://doi.org/` resolver address is
    stripped, and the bare DOI is lowercased (DOIs are defined to be
    case-insensitive). Raises {exc}`ValueError` if `doi` is not a
    DOI."""
    value = _normalize_doi(doi)
    if not value or not _RX_DOI.match(value):
        raise ValueError(f"not a valid DOI: {doi!r}")
    return value.lower()


# --------------------------------------------------------------------- #
# arXiv (by eprint)
# --------------------------------------------------------------------- #


def _arxiv_doi(arxiv_id):
    """The journal DOI recorded on arXiv for `arxiv_id`, in lowercase,
    or `None` if arXiv has no paper with that identifier or no DOI on
    record (may raise on a network/API failure). An arXiv-issued
    DataCite DOI (`10.48550/...`) counts as no DOI: it merely restates
    the identifier, and the journal DOI is the one worth storing."""
    search = arxiv.Search(id_list=[arxiv_id])
    results = list(_client().results(search))
    if not results:
        return None
    doi = _normalize_doi(getattr(results[0], "doi", None))
    if doi is None or doi.lower().startswith("10.48550/"):
        return None
    return doi.lower()


# --------------------------------------------------------------------- #
# Crossref search
# --------------------------------------------------------------------- #


def _search(title, lastname):
    """The Crossref works matching the entry, as a list of item
    `dict`s (may raise on a hard network/API failure). A single
    bibliographic query; precision is enforced later by
    `_pick_match`."""
    kwargs = {}
    if lastname:
        kwargs["query_author"] = lastname
    response = Crossref().works(
        query_bibliographic=_clean_text(title),
        limit=_MAX_RESULTS,
        select=_SELECT,
        **kwargs,
    )
    if not isinstance(response, dict):
        raise ValueError("unexpected response")
    message = response.get("message") or {}
    return message.get("items") or []


#: Normalized-title prefixes marking an amendment record (an erratum,
#: corrigendum, retraction, publisher's note, comment, or reply). Such
#: a record's title embeds the original title, so it can pass the
#: title-similarity thresholds against the original paper.
_AMENDMENT_PREFIXES = (
    "erratum",
    "corrigendum",
    "correction",
    "retraction",
    "publisher",
    "editorial note",
    "comment on",
    "reply to",
)


def _is_amendment(title):
    """Whether `title` marks an amendment record rather than a
    paper."""
    return _norm_title(title).startswith(_AMENDMENT_PREFIXES)


def _item_title(item):
    """The primary title of a Crossref `item`, or `""`."""
    titles = item.get("title") or []
    return titles[0] if titles else ""


def _item_year(item):
    """The publication year of a Crossref `item` (its earliest
    `issued` date), or `None`."""
    date_parts = (item.get("issued") or {}).get("date-parts") or []
    if date_parts and date_parts[0] and date_parts[0][0]:
        return int(date_parts[0][0])
    return None


def _author_matches(lastname, item):
    """Whether `lastname` appears among the family names of the
    Crossref `item`'s authors."""
    if not lastname:
        return False
    for author in item.get("author") or []:
        family = author.get("family") or ""
        toks = _NONALNUM.sub(" ", _deaccent(family).lower()).split()
        if lastname in toks:
            return True
    return False


def _pick_match(title, lastname, items, year=None):
    """Choose the best confident Crossref result among `items`, or
    `None`.

    Acceptance (conservative -- the result is written to the file):

    * title ratio >= `_RATIO_EXACT` -> `"title"`;
    * title ratio >= `_RATIO_FLOOR` and the first author matches
      -> `"title+author"`.

    An item whose amendment status (see `_is_amendment`) differs from
    the entry's is never considered. Returns `(item, ratio, reason)`,
    or `(None, best_ratio, reason)` for no confident match (with an
    empty `reason`, or `"year-mismatch(<item_year>!=<entry_year>)"`
    for a title-based match rejected because its publication year is
    more than one year away from the entry's).
    """
    amendment = _is_amendment(title)
    best = (None, 0.0)
    for item in items:
        item_title = _item_title(item)
        if not item.get("DOI") or not item_title:
            continue
        if _is_amendment(item_title) != amendment:
            continue
        ratio = _title_ratio(title, item_title)
        if ratio > best[1]:
            best = (item, ratio)
    item, ratio = best
    if item is None:
        return None, 0.0, ""
    if ratio >= _RATIO_EXACT:
        reason = "title"
    elif ratio >= _RATIO_FLOOR and _author_matches(lastname, item):
        reason = "title+author"
    else:
        return None, ratio, ""
    item_year = _item_year(item)
    if year and item_year and abs(item_year - year) > 1:
        return None, ratio, f"year-mismatch({item_year}!={year})"
    return item, ratio, reason


# --------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------- #


def find_doi(*, title=None, author=None, year=None, eprint=None):
    """Find the DOI of the published entry described by `title`,
    `author`, `year`, and `eprint` (bib field values; any may be
    `None`); the free function backing
    {meth}`bibdeskparser.Library.add_doi` (see there for the matching
    semantics).

    Returns a `DoiResult` with `applied=False`: `doi` is the found
    DOI in lowercase (`""` if none), `match` is `"eprint"` for the
    DOI recorded on arXiv for the entry's `eprint`, `"title"` or
    `"title+author"` for a Crossref search match, `"none"` for a
    clean no-match, or `"error"` when the lookup could not run to
    completion (network/API failure, or no usable title); network
    problems never raise. `ratio` is the title-similarity ratio of
    the best Crossref result (`None` when no search ran).
    """
    note = []
    errors = False
    eprint = (eprint or "").strip()
    if eprint and _RX_ARXIV_ID.match(eprint):
        try:
            doi = _arxiv_doi(_strip_eprint_version(eprint))
        # pylint: disable-next=broad-except
        except Exception as exc:
            errors = True
            note.append(f"arxiv-error({exc.__class__.__name__}: {exc})")
            doi = None
        else:
            if doi is None:
                note.append("arxiv-no-doi")
        if doi:
            return DoiResult(doi, "eprint", None, "; ".join(note), False)
    if not title or not _norm_title(title):
        note.append("no-title")
        return DoiResult("", "error", None, "; ".join(note), False)
    lastname = _first_author_lastname(author)
    year = _parse_year(year)
    try:
        items = _search(title, lastname)
    # pylint: disable-next=broad-except
    except Exception as exc:  # network / parse / API error
        note.append(f"crossref-error({exc.__class__.__name__}: {exc})")
        return DoiResult("", "error", 0.0, "; ".join(note), False)
    match = "error" if errors else "none"
    if not items:
        note.append("no-results")
        return DoiResult("", match, 0.0, "; ".join(note), False)
    item, ratio, reason = _pick_match(title, lastname, items, year=year)
    if item is None:
        if reason:
            note.append(reason)
        note.append(f"best-ratio={ratio:.2f}")
        return DoiResult("", match, ratio, "; ".join(note), False)
    doi = _normalize_doi(item["DOI"]).lower()
    return DoiResult(doi, reason, ratio, "; ".join(note), False)
