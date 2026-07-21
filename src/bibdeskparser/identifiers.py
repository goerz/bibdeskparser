"""Parsing and normalizing bibliographic identifiers.

Pure helpers for the DOI, arXiv, and preprint-archive identifiers
carried by an entry, shared by `bibdeskparser.abstracts`,
`bibdeskparser.preprints`, and the import/render/export modules. This
module has no dependencies beyond the standard library, so importing it
does not pull in the network client libraries (or `pylatexenc`) that
some of those modules otherwise need.
"""

import re
from collections import namedtuple

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


#: A preprint archive: `name` is the canonical spelling of the archive
#: prefix (e.g. `"arXiv"`), `url` a template for the online location of
#: a preprint, with `{id}` standing for the identifier (`""` if the
#: archive has no identifier-based URLs, e.g. ChemRxiv, whose pages are
#: reached through the DOI instead).
_Archive = namedtuple("_Archive", ["name", "url"])

#: The built-in preprint archives, mapping the lowercased archive
#: prefix to its `_Archive`. Extended (or overridden) by the
#: `[preprint_archives]` table of the configuration; use
#: `config.active.preprint_archives`, not this table, for lookups.
_BUILTIN_ARCHIVES = {
    "arxiv": _Archive("arXiv", "https://arxiv.org/abs/{id}"),
    "biorxiv": _Archive(
        "bioRxiv", "https://www.biorxiv.org/content/10.1101/{id}"
    ),
    "medrxiv": _Archive(
        "medRxiv", "https://www.medrxiv.org/content/10.1101/{id}"
    ),
    "chemrxiv": _Archive("ChemRxiv", ""),
    "hal": _Archive("HAL", "https://hal.science/{id}"),
    "ssrn": _Archive("SSRN", "https://ssrn.com/abstract={id}"),
}

#: The `<prefix>:<identifier>` shape of a preprint pseudo-journal,
#: e.g. `journal = {arXiv:2205.15044}`. A real journal name containing
#: a colon (`J. Phys.: Condens. Matter`) never matches: it has a space
#: after the colon.
_PSEUDO_JOURNAL_RX = re.compile(r"^(\w+):(\S+)$")

_EPRINT_VERSION_RX = re.compile(r"v\d+$")


def _pseudo_journal(value):
    """Split a `journal` field `value` of the `<prefix>:<identifier>`
    pseudo-journal shape into `(prefix, identifier)`; `None` if it
    does not have that shape (whatever the prefix -- see
    `_preprint_journal` for the archive lookup)."""
    match = _PSEUDO_JOURNAL_RX.match(value.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


def _preprint_journal(value, archives):
    """Resolve a `journal` field `value` that is a recognized preprint
    pseudo-journal (e.g. `"arXiv:2205.15044"`) to `(archive,
    identifier)`, where `archive` is the `_Archive` found in
    `archives` (a mapping of lowercased prefix to `_Archive`, e.g.
    `config.active.preprint_archives`) for the value's prefix.
    Returns `None` if `value` does not have the pseudo-journal shape
    or its prefix is not in `archives`."""
    split = _pseudo_journal(value)
    if split is None:
        return None
    prefix, identifier = split
    archive = archives.get(prefix.lower())
    if archive is None:
        return None
    return archive, identifier


def _entry_preprint(entry, archives):
    """Resolve a *preprint-only* entry to `(archive, identifier)`.

    An entry is preprint-only if its `journal` is a recognized
    preprint pseudo-journal (see `_preprint_journal`; any entry
    type), or if it is a `misc` or `unpublished` entry with a
    non-empty `eprint` whose `archiveprefix` names a recognized
    archive (an absent `archiveprefix` means arXiv). Returns `None`
    for anything else -- in particular for a published article that
    also carries an `eprint`, and for other entry types like a
    thesis deposited on a preprint server.

    `entry` is a {class}`bibdeskparser.entry.Entry` (or anything
    with `entry_type` and a `get` returning field values); `archives`
    a mapping of lowercased prefix to `_Archive`, e.g.
    `config.active.preprint_archives`."""
    journal = str(entry.get("journal") or "").strip()
    preprint = _preprint_journal(journal, archives)
    if preprint is not None:
        return preprint
    if entry.entry_type.lower() not in ("misc", "unpublished"):
        return None
    eprint = str(entry.get("eprint") or "").strip()
    if not eprint:
        return None
    prefix = str(entry.get("archiveprefix") or "").strip() or "arXiv"
    archive = archives.get(prefix.lower())
    if archive is None:
        return None
    return archive, eprint


_DOI_ORG_RX = re.compile(r"(?i)^https?://(?:dx\.)?doi\.org/(.+)$")


def _doi_from_url(url):
    """The DOI embedded in a `https://doi.org/...` resolver URL, or
    `None` if `url` is not such a URL."""
    match = _DOI_ORG_RX.match(url.strip())
    if match is None:
        return None
    return match.group(1)


def _archive_base(archive):
    """The base URL of `archive`'s identifier pages, for the BibTeX
    `archive` field that REVTeX's `apsrev4-x`/`aipnum4-x` styles use
    as the link base of an eprint (their built-in default is arXiv's
    `https://arxiv.org/abs`).

    Derived from the archive's URL template when it has the form
    `<base>/{id}`; `None` otherwise -- including for arXiv itself,
    where emitting the field would be redundant, and for archives
    like SSRN (`...?abstract_id={id}`) whose page URLs do not append
    the identifier as a path segment."""
    if archive.name.lower() == "arxiv":
        return None
    if archive.url.endswith("/{id}"):
        return archive.url[: -len("/{id}")]
    return None


def _archive_url(archive, identifier):
    """The online location of the preprint `identifier` in `archive`
    (an `_Archive`), or `None` if the archive has no identifier-based
    URLs."""
    if not archive.url:
        return None
    return archive.url.replace("{id}", identifier)


def _strip_eprint_version(value):
    """`value` (a preprint identifier or `eprint` field value) without
    any trailing version suffix (`2205.15044v2` -> `2205.15044`)."""
    return _EPRINT_VERSION_RX.sub("", value.strip())


def _eprint_matches(eprint, identifier):
    """Whether an `eprint` field value and a pseudo-journal
    `identifier` name the same preprint: equal after stripping any
    version suffix, compared case-insensitively."""
    return (
        _strip_eprint_version(eprint).lower()
        == _strip_eprint_version(identifier).lower()
    )


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
