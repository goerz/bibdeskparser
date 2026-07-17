"""Parsing and normalizing bibliographic identifiers.

Pure helpers for the DOI and arXiv identifiers carried by an entry,
shared by `bibdeskparser.abstracts` and `bibdeskparser.preprints`. This
module has no dependencies beyond the standard library, so importing it
does not pull in the network client libraries (or `pylatexenc`) that
those two modules otherwise need.
"""

import re

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = []


def _normalize_doi(doi):
    """Strip a `doi:`/`https://doi.org/` prefix; `None` if empty."""
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"(?i)^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"(?i)^doi:\s*", "", doi)
    doi = doi.strip()
    return doi or None


_RX_ARXIV_ID = re.compile(
    r"^(\d{4}\.\d{4,5}|[a-z-]+(\.[A-Za-z-]+)?/\d{7})(v\d+)?$"
)

_RX_KEY_ARXIV = re.compile(r"(\d{4}\.\d{4,5})")


def _arxiv_id(eprint, key):
    """The arXiv identifier for an entry, as `(id, certain)`.

    An `eprint` field value that looks like an arXiv identifier (new
    or old style) is authoritative (`certain=True`); otherwise, a
    new-style identifier embedded in the citation `key` (e.g.
    `Karch2501.16995`) is a guess (`certain=False`). Returns
    `(None, False)` if neither yields an identifier.
    """
    if eprint and _RX_ARXIV_ID.match(eprint.strip()):
        return eprint.strip(), True
    match = _RX_KEY_ARXIV.search(key or "")
    if match:
        return match.group(1), False
    return None, False
