"""Retrieving abstracts from online sources and PDF attachments.

Provides {func}`fetch_abstract`, the free function backing
{meth}`bibdeskparser.Library.add_abstract`: gather candidate abstracts
for an entry from Crossref (by DOI), from the text of the entry's PDF
attachment, from the arXiv API (by eprint), and from Semantic Scholar
as a last resort; clean and validate each candidate (via
{mod}`bibdeskparser.abstracttext`); and combine the candidates into a
single result with an explicit confidence level.

This module is imported lazily (by `Library.add_abstract`): it pulls in
the network client libraries and `bibdeskparser.abstracttext` (and
through it `pylatexenc`), which nothing else in the package needs.
"""

import re
import subprocess
import time
import urllib.parse
from collections import namedtuple

import arxiv
import httpx
from habanero import Crossref

from .abstracttext import _clean_text, _jats_to_text, _overlap, _validate
from .identifiers import _arxiv_id, _normalize_doi

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "AbstractResult",
    "CONFIDENCE_LEVELS",
    "fetch_abstract",
]


#: The result of `fetch_abstract` (and of `Library.add_abstract`,
#: which sets `applied`); see the `Library.add_abstract` docstring for
#: the meaning of each field.
AbstractResult = namedtuple(
    "AbstractResult", ["abstract", "source", "confidence", "note", "applied"]
)

#: Confidence levels, in increasing order of trust.
CONFIDENCE_LEVELS = ("none", "low", "medium", "high")


# --------------------------------------------------------------------- #
# Candidate cleaning (delegated to `abstracttext`)
# --------------------------------------------------------------------- #


def _valid_or_none(text, label, note):
    """`_clean_text(text)` if it validates, else `None` (appending
    `label`-invalid:reason to the `note` list)."""
    text = _clean_text(text)
    if not text:
        return None
    ok, reason = _validate(text)
    if not ok:
        note.append(f"{label}-invalid:{reason}")
        return None
    return text


# --------------------------------------------------------------------- #
# PDF extraction
# --------------------------------------------------------------------- #


def _pdftotext(pdf_path, pages=4):
    """The text of the first `pages` pages of `pdf_path` via the
    `pdftotext` command-line tool; `(text, None)`, or `(None, reason)`
    if the tool is missing or fails."""
    cmd = ["pdftotext", "-q", "-f", "1", "-l", str(pages), str(pdf_path), "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except FileNotFoundError:
        return None, "pdftotext-missing"
    # pylint: disable-next=broad-except
    except Exception:
        return None, "pdftotext-failed"
    if out.returncode != 0:
        return None, "pdftotext-failed"
    return out.stdout.decode("utf-8", "replace"), None


# section headers that mark the END of an abstract
_END = re.compile(
    r"(?im)^\s*("
    r"DOI:|PACS|Keywords|Key words|Subject Areas|"
    r"I\.\s+INTRODUCTION|1\.\s+Introduction|1\s+Introduction|"
    r"INTRODUCTION\b|Contents\b|CONTENTS\b|"
    r"\(Some figures may appear|Published by|©|"
    r"This is an open access|Received\b)"
)

_RECVD_LINE = re.compile(
    r"(?im)^.*?\b(Received|Dated|published|Published)\b.*\)\s*$"
)

_ABS_HEADER = re.compile(
    r"(?im)^\s*(a\s?b\s?s\s?t\s?r\s?a\s?c\s?t|A\s?B\s?S\s?T\s?R\s?A\s?C\s?T)"
    r"\.?\s*[:\-—]?\s*$"
)

_PARA_END = re.compile(r"\n[ \t]*\n")  # blank line = paragraph break


def _abstract_until(rest):
    """Trim `rest` to the abstract: up to the earliest of a blank
    line, a PACS/DOI line, or a section header (`_END`)."""
    ends = []
    end_match = _END.search(rest)
    if end_match:
        ends.append(end_match.start())
    # skip a leading blank line (between header and body), then find
    # the first real paragraph break
    leading = re.match(r"\s*", rest)
    para = _PARA_END.search(rest, leading.end())
    if para:
        ends.append(para.start())
    cut = min(ends) if ends else min(len(rest), 3500)
    return rest[:cut].strip()


def _extract_pdf_abstract(text):
    """The abstract paragraph of the PDF `text`, as
    `(abstract_or_None, note)`; publisher-agnostic heuristics."""
    if not text:
        return None, "no-pdf-text"
    # pdftotext sometimes renders the parens around "(Published ...)"
    # as CJK brackets; normalize those (and sibling glyphs) first
    text = text.translate(str.maketrans("共兲⬍⬎", "()<>"))

    # APS / arXiv: the paragraph after a "(Received .../ Dated .../
    # published ...)" line. Try each such line in reading order; the
    # first that yields a valid paragraph wins (long review articles
    # repeat "published" deep in the body).
    for match in _RECVD_LINE.finditer(text):
        block = _abstract_until(text[match.end() :])
        if 150 < len(block) < 4000:
            return block, "pdf-received"

    # IOP / Elsevier: an explicit (possibly spaced) "Abstract" header
    for match in _ABS_HEADER.finditer(text):
        block = _abstract_until(text[match.end() :])
        if 150 < len(block) < 4000:
            return block, "pdf-abstract-header"

    # inline "Abstract. ..." (text on the same line)
    match = re.search(r"(?im)^\s*(abstract|ABSTRACT)[.:\-—]\s+(?=\S)", text)
    if match:
        block = _abstract_until(text[match.end() :])
        if 150 < len(block) < 4000:
            return block, "pdf-abstract-inline"

    return None, "pdf-no-delimiter"


# --------------------------------------------------------------------- #
# Online sources
# --------------------------------------------------------------------- #


def _crossref_abstract(doi):
    """The raw (JATS) abstract deposited with Crossref for `doi`, or
    `None` (no deposit, or any network/data error)."""
    try:
        response = Crossref().works(ids=doi)
        if not isinstance(response, dict):
            return None
        message = response.get("message") or {}
        return message.get("abstract")
    # pylint: disable-next=broad-except
    except Exception:
        return None


def _arxiv_summary(arxiv_id):
    """The abstract ("summary") of `arxiv_id` from the arXiv API, or
    `None` (no such paper, or any network error). `arxiv.Client`
    enforces the arXiv API's rate limits."""
    try:
        search = arxiv.Search(id_list=[arxiv_id])
        results = list(arxiv.Client().results(search))
        return results[0].summary if results else None
    # pylint: disable-next=broad-except
    except Exception:
        return None


_SS_API = "https://api.semanticscholar.org/graph/v1/paper/"


def _semanticscholar_abstract(ident):
    """The abstract for `ident` (`"DOI:..."` or `"arXiv:..."`) from
    the Semantic Scholar Graph API, or `None`. The public API is
    rate-limited (~1 request/second): retry twice with a backoff."""
    url = _SS_API + urllib.parse.quote(ident, safe=":/") + "?fields=abstract"
    for attempt in range(3):
        try:
            response = httpx.get(url, timeout=30)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json().get("abstract")
        # pylint: disable-next=broad-except
        except Exception:
            time.sleep(1 + 2 * attempt)
    return None


# --------------------------------------------------------------------- #
# Arbitration
# --------------------------------------------------------------------- #

# Token overlap above which two sources describe the same text (they
# are never identical: unicode cleanup, de-hyphenation, and JATS
# conversion all differ between sources).
_AGREE = 0.5


def _result(abstract, source, confidence, note):
    return AbstractResult(abstract, source, confidence, "; ".join(note), False)


def fetch_abstract(*, doi=None, eprint=None, key=None, pdf_path=None):
    """Fetch the best-supported abstract for an entry; the free
    function backing {meth}`bibdeskparser.Library.add_abstract` (see
    there for the source-selection and confidence semantics).

    All identifying data is passed explicitly: the entry's `doi` and
    `eprint` field values (either may be `None`), its citation `key`
    (used only to guess an arXiv identifier when `eprint` is absent),
    and the resolved path of its PDF attachment (`None` if it has
    none). Returns an `AbstractResult` with `applied=False`; network
    problems never raise (an unreachable source is skipped, see the
    result's `note`).
    """
    note = []
    doi = _normalize_doi(doi)
    arxiv_id, arxiv_certain = _arxiv_id(eprint, key)

    # --- Crossref (publisher JATS deposit, by DOI) -------------------- #
    cr_text = None
    if doi:
        raw = _crossref_abstract(doi)
        if raw is None:
            note.append("cr-miss")
        else:
            cr_text = _valid_or_none(_jats_to_text(raw), "cr", note)

    # --- PDF ----------------------------------------------------------- #
    pdf_text = None
    pdf_high = False
    if pdf_path is None:
        note.append("no-pdf")
    else:
        text, error = _pdftotext(pdf_path)
        if text is None:
            note.append(error)
        else:
            block, pdf_note = _extract_pdf_abstract(text)
            note.append(pdf_note)
            pdf_text = _valid_or_none(block, "pdf", note)
            pdf_high = pdf_note in ("pdf-received", "pdf-abstract-header")

    # The DOI guarantees the Crossref abstract belongs to this exact
    # paper; when it agrees with the PDF, prefer Crossref (cleaner
    # unicode). When the two *disagree*, one of them grabbed the wrong
    # text: keep the PDF (it is literally this file) but flag it.
    if cr_text and pdf_text:
        overlap = _overlap(pdf_text, cr_text)
        note.append(f"ov={overlap:.2f}")
        if overlap >= _AGREE:
            return _result(cr_text, "crossref", "high", note)
        note.append("cr-disagree")
        return _result(pdf_text, "pdf", "low", note)
    if cr_text:
        return _result(cr_text, "crossref", "high", note)
    # An unambiguous PDF extraction needs no online confirmation
    # (fast path: skips the rate-limited arXiv/Semantic Scholar calls)
    if pdf_text and pdf_high:
        return _result(pdf_text, "pdf", "high", note)

    # --- arXiv (by eprint, or an id guessed from the key) ------------- #
    if arxiv_id:
        ax_text = _valid_or_none(_arxiv_summary(arxiv_id), "arxiv", note)
        confidence = "high" if arxiv_certain else "medium"
        if ax_text and pdf_text:
            overlap = _overlap(pdf_text, ax_text)
            note.append(f"arxiv-ov={overlap:.2f}")
            if overlap >= _AGREE:
                return _result(ax_text, "arxiv", confidence, note)
            note.append("arxiv-disagree")
            return _result(pdf_text, "pdf", "low", note)
        if ax_text:
            return _result(ax_text, "arxiv", confidence, note)

    # --- Semantic Scholar (clean fallback; only when needed) ---------- #
    ident = certain = None
    if doi:
        ident, certain = f"DOI:{doi}", True
    elif arxiv_id:
        ident, certain = f"arXiv:{arxiv_id}", arxiv_certain
    if ident:
        ss_text = _valid_or_none(_semanticscholar_abstract(ident), "ss", note)
        confidence = "high" if certain else "medium"
        if ss_text and pdf_text:
            overlap = _overlap(pdf_text, ss_text)
            note.append(f"ss-ov={overlap:.2f}")
            if overlap >= _AGREE:
                return _result(ss_text, "semanticscholar", confidence, note)
            note.append("ss-disagree")
            return _result(pdf_text, "pdf", "low", note)
        if ss_text:
            return _result(ss_text, "semanticscholar", confidence, note)

    if pdf_text:
        return _result(pdf_text, "pdf", "medium", note)
    return _result("", "none", "none", note)
