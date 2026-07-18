"""Fetching bibliographic data from online sources.

Provides {func}`fetch_bibtex`, the free function backing
{meth}`bibdeskparser.Library.add`: classify a query as an arXiv
identifier, a DOI, or a free-form search, fetch the metadata from the
appropriate source (the arXiv API, or Crossref), and render it as a
*minimal* BibTeX snippet. The snippet is deliberately raw -- full
journal names, no brace protection, a placeholder citation key: all
sanitization and normalization is left to the import pipeline
(`bibdeskparser.importing`), which every fetched entry passes through.

Also provides {func}`fetch_text`, the plain URL download used by the
command-line `import --url`.

This module is imported lazily (by `Library.add`): it pulls in the
network dependencies, which nothing else in the package needs. Network
politeness is delegated to the client libraries; in particular,
`arxiv.Client` enforces the arXiv API's terms of use (no more than one
request every three seconds).
"""

import re

import arxiv
import httpx
from habanero import Crossref, cn

from .abstracttext import cleaned_abstract
from .names import structured_names

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["fetch_bibtex", "fetch_text"]


_RX_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)

_RX_ARXIV_NEW = re.compile(r"arxiv.*?(\d{4}\.\d{4,}(?:v\d+)?)", re.IGNORECASE)

#: A bare new-style arXiv identifier (`2205.15044`), without any
#: `arXiv` context around it.
_RX_ARXIV_BARE = re.compile(r"^(\d{4}\.\d{4,}(?:v\d+)?)$")

_RX_ARXIV_OLD = re.compile(
    r"""
    ((
       math-ph
      |hep-ph
      |nucl-ex
      |nucl-th
      |gr-qc
      |astro-ph
      |hep-lat
      |quant-ph
      |hep-ex
      |hep-th
      |stat
        (\.(AP|CO|ML|ME|TH))?
      |q-bio
        (\.(BM|CB|GN|MN|NC|OT|PE|QM|SC|TO))?
      |cond-mat
        (\.(dis-nn|mes-hall|mtrl-sci|other|soft|stat-mech|str-el|supr-con))?
      |cs
        (\.(AR|AI|CL|CC|CE|CG|GT|CV|CY|CR|DS|DB|DL|DM|DC|GL|GR|HC|IR|IT|LG|LO|
          MS|MA|MM|NI|NE|NA|OS|OH|PF|PL|RO|SE|SD|SC))?
      |nlin
        (\.(AO|CG|CD|SI|PS))?
      |physics
        (\.(acc-ph|ao-ph|atom-ph|atm-clus|bio-ph|chem-ph|class-ph|comp-ph|
          data-an|flu-dyn|gen-ph|geo-ph|hist-ph|ins-det|med-ph|optics|ed-ph|
          soc-ph|plasm-ph|pop-ph|space-ph))?
      |math
          (\.(AG|AT|AP|CT|CA|CO|AC|CV|DG|DS|FA|GM|GN|GT|GR|HO|IT|KT|LO|MP|MG
          |NT|NA|OA|OC|PR|QA|RT|RA|SP|ST|SG))?
    )/\d{7}(v\d+)?)""",
    re.X,
)

_ARXIV_VERSION_RX = re.compile(r"v\d+$")

#: Crossref work types with a BibTeX equivalent. Anything else is
#: retrieved as publisher BibTeX via DOI content negotiation.
_CROSSREF_TYPES = {
    "journal-article": "article",
    "proceedings-article": "inproceedings",
    "book-chapter": "incollection",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
}


def _classify(query):
    """Classify `query` as `("arxiv", id)`, `("doi", doi)`, or
    `("query", query)`. An arXiv identifier wins over a DOI; anything
    containing a space can only be a free-form query."""
    match = (
        _RX_ARXIV_NEW.search(query)
        or _RX_ARXIV_BARE.match(query)
        or _RX_ARXIV_OLD.search(query)
    )
    if match:
        return ("arxiv", match.group(1))
    if " " not in query:
        if query.startswith("10."):
            return ("doi", query)
        match = _RX_DOI.search(query)
        if match:
            return ("doi", match.group(0))
    return ("query", query)


# -- BibTeX rendering --------------------------------------------------- #


def _entry_text(entry_type, fields):
    """Render `fields` (skipping `None` values) as a minimal BibTeX
    entry with a placeholder citation key (the import pipeline
    generates the real key)."""
    lines = ["@%s{Fetched," % entry_type]
    for key, value in fields.items():
        if value is not None:
            lines.append("    %s = {%s}," % (key, value))
    lines.append("}")
    return "\n".join(lines)


# -- the arXiv backend --------------------------------------------------- #


def _bibtex_from_arxiv(arxiv_id, include_abstract=False):
    """A minimal BibTeX preprint entry for `arxiv_id`, from the arXiv
    API."""
    search = arxiv.Search(id_list=[arxiv_id])
    results = list(arxiv.Client().results(search))
    if not results:
        raise ValueError(f"arXiv query for {arxiv_id!r} returned no result")
    result = results[0]
    base_id = _ARXIV_VERSION_RX.sub("", arxiv_id)
    author = " and ".join(
        structured_names(author.name)[0].merge_last_name_first
        for author in result.authors
    )
    return _entry_text(
        "article",
        {
            "author": author or None,
            "title": result.title,
            "journal": f"arXiv:{arxiv_id}",
            "eprint": base_id,
            "archiveprefix": "arXiv",
            "year": result.published.year,
            "url": f"https://doi.org/10.48550/arXiv.{base_id}",
            "abstract": (
                cleaned_abstract(result.summary) if include_abstract else None
            ),
        },
    )


# -- the Crossref backend ------------------------------------------------ #


def _check_response(response):
    """Raise {exc}`ValueError` unless `response` is a successful
    habanero/Crossref response dict."""
    if not isinstance(response, dict) or "status" not in response:
        raise ValueError(f"Crossref query returned invalid {response!r}")
    if response["status"] != "ok":
        raise ValueError(
            f"Crossref query returned status {response['status']!r}"
        )


def _names(record, field):
    """The `author`/`editor` names of a Crossref `record`, in
    `Last, First and ...` form (`None` if absent)."""
    people = record.get(field)
    if not people:
        return None
    names = []
    for person in people:
        family = person.get("family")
        given = person.get("given")
        if family and given:
            names.append(f"{family}, {given}")
        elif family:
            names.append(family)
        elif person.get("name"):  # e.g. a collaboration
            names.append(person["name"])
    return " and ".join(names) or None


def _first(record, key):
    """The first element of the list-valued Crossref field `key`
    (`None` if absent or empty)."""
    values = record.get(key) or []
    return values[0] if values else None


def _container(record):
    """The venue (journal/book) name of a Crossref `record`,
    preferring the abbreviated `short-container-title`."""
    for key in ("short-container-title", "container-title"):
        for name in record.get(key) or []:
            if name:
                return name
    return None


def _year(record):
    """The publication year of a Crossref `record` (`None` if it
    cannot be determined)."""
    for key in ("issued", "published-print", "published-online", "created"):
        try:
            year = record[key]["date-parts"][0][0]
        except (KeyError, IndexError, TypeError):
            continue
        if year is not None:
            return year
    return None


def _pages(record):
    """The page value of a Crossref `record`, preferring the article
    number (page-range normalization is the import pipeline's job)."""
    return record.get("article-number") or record.get("page")


def _event_location(record):
    """The conference location of a Crossref `record` (`None` if
    absent)."""
    try:
        return record["event"]["location"]
    except (KeyError, TypeError):
        return None


def _crossref_fields(record, include_abstract=False):
    """Map a Crossref `record` to `(entry_type, fields)` for
    `_entry_text`, or to `(None, None)` for a work type with no
    BibTeX equivalent."""
    entry_type = _CROSSREF_TYPES.get(record.get("type"))
    if entry_type is None:
        return None, None
    fields = {
        "author": _names(record, "author"),
        "title": _first(record, "title"),
        "year": _year(record),
        "doi": record.get("DOI"),
        "abstract": (
            cleaned_abstract(record.get("abstract"), jats=True)
            if include_abstract
            else None
        ),
    }
    if entry_type == "article":
        fields.update(
            journal=_container(record),
            pages=_pages(record),
            volume=record.get("volume"),
            number=record.get("issue"),
        )
    elif entry_type == "inproceedings":
        fields.update(
            booktitle=_container(record),
            pages=_pages(record),
            address=_event_location(record),
            editor=_names(record, "editor"),
        )
    elif entry_type == "incollection":
        fields.update(
            booktitle=_container(record),
            pages=_pages(record),
            editor=_names(record, "editor"),
            publisher=record.get("publisher"),
            volume=record.get("volume"),
        )
    else:  # book
        fields.update(
            editor=_names(record, "editor"),
            publisher=record.get("publisher"),
            isbn=_first(record, "ISBN"),
            volume=record.get("volume"),
        )
    return entry_type, fields


def _bibtex_from_record(record, include_abstract=False):
    """BibTeX text for a Crossref `record`: a minimal entry for the
    supported work types, else publisher BibTeX via DOI content
    negotiation (which never includes an abstract)."""
    entry_type, fields = _crossref_fields(record, include_abstract)
    if entry_type is not None:
        return _entry_text(entry_type, fields)
    doi = record.get("DOI")
    if doi is None:
        raise ValueError(
            f"Crossref record of type {record.get('type')!r} is not "
            "supported"
        )
    return cn.content_negotiation(ids=doi)


def _bibtex_from_doi(doi, include_abstract=False):
    """BibTeX text for the work identified by `doi`, from Crossref."""
    response = Crossref().works(ids=doi)
    _check_response(response)
    return _bibtex_from_record(response["message"], include_abstract)


def _bibtex_from_query(query, include_abstract=False):
    """BibTeX text for the best Crossref match of the bibliographic
    `query`."""
    response = Crossref().works(query_bibliographic=query, limit=1)
    _check_response(response)
    items = response["message"].get("items") or []
    if not items:
        raise ValueError(f"no Crossref match for query {query!r}")
    return _bibtex_from_record(items[0], include_abstract)


# -- entry points -------------------------------------------------------- #


def fetch_bibtex(query, *, include_abstract=False):
    """Fetch bibliographic data for `query` (an arXiv identifier, a
    DOI, a URL containing either, or free-form search text -- see
    {meth}`bibdeskparser.Library.add`) and return it as BibTeX text.

    With `include_abstract=True`, the abstract returned alongside the
    metadata (Crossref deposit or arXiv summary) is included as an
    `abstract` field, cleaned and validated via
    {func}`bibdeskparser.abstracttext.cleaned_abstract` (omitted if the
    source provides none or the text fails validation).

    Raises {exc}`ValueError` for anything that goes wrong (network
    errors, no match for the query, an unsupported record without a
    DOI)."""
    kind, identifier = _classify(query)
    try:
        if kind == "arxiv":
            return _bibtex_from_arxiv(identifier, include_abstract)
        if kind == "doi":
            return _bibtex_from_doi(identifier, include_abstract)
        return _bibtex_from_query(identifier, include_abstract)
    except ValueError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        # habanero/arxiv/httpx raise a wide variety of exception types
        # for network and data errors; the CLI (and any caller) gets
        # them as a single, clean error type.
        raise ValueError(
            f"could not fetch bibliographic data for {query!r}: {exc}"
        ) from exc


def fetch_text(url):
    """Download `url` and return the response body as text (for
    `import --url`). Raises {exc}`ValueError` on any HTTP error."""
    try:
        response = httpx.get(url, follow_redirects=True, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError(f"could not fetch {url}: {exc}") from exc
    return response.text
