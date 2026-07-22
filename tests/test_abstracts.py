"""Tests for the `abstracts` module and `Library.add_abstract` (all
network clients mocked)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import bibdeskparser.abstracts as abstracts
import bibdeskparser.config as config
from bibdeskparser import Entry, Library
from bibdeskparser.abstracts import AbstractResult

# Two *different* valid abstracts (each long enough to validate; token
# overlap between the two is far below the agreement threshold).
TEXT_A = (
    "We show that optimizing a quantum gate for an open quantum "
    "system requires the time evolution of only three states. This "
    "represents a significant reduction in computational resources "
    "compared to the complete basis of Liouville space that is "
    "commonly believed necessary for this task, and we illustrate "
    "the reduction for a controlled phasegate with trapped atoms."
)

TEXT_B = (
    "The measurement of weak magnetic fields with high spatial "
    "resolution is an outstanding problem in the biological and "
    "physical sciences. For example, at the cellular scale it can "
    "provide a window into the dynamics of neural networks, and in "
    "condensed matter physics it is used to probe spin textures in "
    "unconventional superconductors with great precision."
)


# -- PDF extraction --------------------------------------------------------- #

PDF_APS = f"""\
PHYSICAL REVIEW A 89, 032334 (2014)

Optimal control theory for a unitary operation

Michael Goerz
(Received 3 December 2013; published 25 March 2014)

{TEXT_A}

DOI: 10.1103/PhysRevA.89.032334

I. INTRODUCTION
"""

PDF_HEADER = f"""\
Journal of Physics B

Abstract

{TEXT_A}

Keywords: quantum control
"""

PDF_SPACED_HEADER = f"""\
Some Elsevier Journal

a b s t r a c t

{TEXT_A}

1. Introduction
"""

PDF_INLINE = f"""\
Some Journal

Abstract. {TEXT_A}

1. Introduction
"""


@pytest.mark.parametrize(
    "text, note",
    [
        (PDF_APS, "pdf-received"),
        (PDF_HEADER, "pdf-abstract-header"),
        (PDF_SPACED_HEADER, "pdf-abstract-header"),
        (PDF_INLINE, "pdf-abstract-inline"),
    ],
)
def test_extract_pdf_abstract(text, note):
    block, got_note = abstracts._extract_pdf_abstract(text)
    assert got_note == note
    assert block == TEXT_A


def test_extract_pdf_abstract_no_delimiter():
    assert abstracts._extract_pdf_abstract("Just some text.") == (
        None,
        "pdf-no-delimiter",
    )
    assert abstracts._extract_pdf_abstract("") == (None, "no-pdf-text")


def test_pdftotext_missing_binary(monkeypatch):
    def run(cmd, **kwargs):
        raise FileNotFoundError("pdftotext")

    monkeypatch.setattr(abstracts.subprocess, "run", run)
    assert abstracts._pdftotext(Path("x.pdf")) == (None, "pdftotext-missing")


def test_pdftotext_failure(monkeypatch):
    monkeypatch.setattr(
        abstracts.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(returncode=1, stdout=b""),
    )
    assert abstracts._pdftotext(Path("x.pdf")) == (None, "pdftotext-failed")


def test_pdftotext(monkeypatch):
    commands = []

    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout=TEXT_A.encode("utf-8"))

    monkeypatch.setattr(abstracts.subprocess, "run", run)
    text, error = abstracts._pdftotext(Path("x.pdf"))
    assert text == TEXT_A
    assert error is None
    assert commands[0][0] == "pdftotext"
    assert "x.pdf" in commands[0]


# -- online sources ------------------------------------------------------ #


def test_crossref_abstract(monkeypatch):
    class FakeCrossref:
        def works(self, ids):
            return {"message": {"abstract": f"<jats:p>{TEXT_A}</jats:p>"}}

    monkeypatch.setattr(abstracts, "Crossref", FakeCrossref)
    assert abstracts._crossref_abstract("10.1103/x") == (
        f"<jats:p>{TEXT_A}</jats:p>"
    )


def test_crossref_abstract_error(monkeypatch):
    """A network failure raises `_SourceError` (distinct from a
    definite negative), while a 404 (a DOI not registered with
    Crossref) is a definite negative."""

    class FakeCrossref:
        def works(self, ids):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(abstracts, "Crossref", FakeCrossref)
    with pytest.raises(abstracts._SourceError, match="connection refused"):
        abstracts._crossref_abstract("10.1103/x")

    class FakeCrossref404:
        def works(self, ids):
            error = RuntimeError("not found")
            error.response = SimpleNamespace(status_code=404)
            raise error

    monkeypatch.setattr(abstracts, "Crossref", FakeCrossref404)
    assert abstracts._crossref_abstract("10.1103/x") is None


def test_arxiv_summary(monkeypatch):
    searches = []

    class FakeSearch:
        def __init__(self, id_list):
            searches.append(id_list)

    class FakeClient:
        def results(self, search):
            return iter([SimpleNamespace(summary=TEXT_A)])

    monkeypatch.setattr(
        abstracts,
        "arxiv",
        SimpleNamespace(Client=FakeClient, Search=FakeSearch),
    )
    assert abstracts._arxiv_summary("2205.15044") == TEXT_A
    assert searches == [["2205.15044"]]


def test_arxiv_summary_no_result(monkeypatch):
    class FakeClient:
        def results(self, search):
            return iter([])

    monkeypatch.setattr(
        abstracts,
        "arxiv",
        SimpleNamespace(Client=FakeClient, Search=lambda id_list: None),
    )
    assert abstracts._arxiv_summary("2205.15044") is None


def test_semanticscholar_abstract(monkeypatch):
    urls = []

    def get(url, timeout):
        urls.append(url)
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"abstract": TEXT_A},
        )

    monkeypatch.setattr(abstracts, "httpx", SimpleNamespace(get=get))
    assert abstracts._semanticscholar_abstract("DOI:10.1103/x") == TEXT_A
    assert urls[0].startswith(abstracts._SS_API)
    assert "DOI:10.1103/x" in urls[0]


def test_semanticscholar_abstract_404(monkeypatch):
    monkeypatch.setattr(
        abstracts,
        "httpx",
        SimpleNamespace(
            get=lambda url, timeout: SimpleNamespace(status_code=404)
        ),
    )
    assert abstracts._semanticscholar_abstract("DOI:10.1103/x") is None


def test_semanticscholar_abstract_retries(monkeypatch):
    calls = []

    def get(url, timeout):
        calls.append(url)
        raise RuntimeError("rate limited")

    monkeypatch.setattr(abstracts, "httpx", SimpleNamespace(get=get))
    monkeypatch.setattr(abstracts.time, "sleep", lambda seconds: None)
    with pytest.raises(abstracts._SourceError, match="semanticscholar"):
        abstracts._semanticscholar_abstract("DOI:10.1103/x")
    assert len(calls) == 3


# -- arbitration (fetch_abstract) ------------------------------------------ #


def _mock_sources(
    monkeypatch, *, crossref=None, pdf=None, arxiv=None, ss=None
):
    """Mock all four candidate sources; returns a dict recording which
    ones were actually queried."""
    queried = {}

    def crossref_abstract(doi):
        queried["crossref"] = doi
        return crossref

    def pdftotext(pdf_path, pages=4):
        queried["pdf"] = pdf_path
        if pdf is None:
            return None, "pdftotext-failed"
        return pdf, None

    def arxiv_summary(arxiv_id):
        queried["arxiv"] = arxiv_id
        return arxiv

    def ss_abstract(ident):
        queried["ss"] = ident
        return ss

    monkeypatch.setattr(abstracts, "_crossref_abstract", crossref_abstract)
    monkeypatch.setattr(abstracts, "_pdftotext", pdftotext)
    monkeypatch.setattr(abstracts, "_arxiv_summary", arxiv_summary)
    monkeypatch.setattr(abstracts, "_semanticscholar_abstract", ss_abstract)
    return queried


def test_fetch_crossref_agrees_with_pdf(monkeypatch):
    queried = _mock_sources(
        monkeypatch, crossref=f"<jats:p>{TEXT_A}</jats:p>", pdf=PDF_APS
    )
    result = abstracts.fetch_abstract(doi="10.1103/x", pdf_path=Path("x.pdf"))
    assert result.abstract == TEXT_A
    assert result.source == "crossref"
    assert result.confidence == "high"
    assert result.applied is False
    assert "ov=1.00" in result.note
    assert "arxiv" not in queried  # no further lookup needed
    assert "ss" not in queried


def test_fetch_crossref_disagrees_with_pdf(monkeypatch):
    _mock_sources(
        monkeypatch, crossref=f"<jats:p>{TEXT_B}</jats:p>", pdf=PDF_APS
    )
    result = abstracts.fetch_abstract(doi="10.1103/x", pdf_path=Path("x.pdf"))
    assert result.abstract == TEXT_A  # the PDF text (this exact file)
    assert result.source == "pdf"
    assert result.confidence == "low"
    assert "cr-disagree" in result.note


def test_fetch_crossref_only(monkeypatch):
    _mock_sources(monkeypatch, crossref=f"<jats:p>{TEXT_A}</jats:p>")
    result = abstracts.fetch_abstract(doi="10.1103/x")
    assert (result.source, result.confidence) == ("crossref", "high")
    assert "no-pdf" in result.note


def test_fetch_pdf_high_confidence_shortcut(monkeypatch):
    queried = _mock_sources(monkeypatch, pdf=PDF_APS)
    result = abstracts.fetch_abstract(
        doi="10.1103/x", eprint="2205.15044", pdf_path=Path("x.pdf")
    )
    assert result.abstract == TEXT_A
    assert (result.source, result.confidence) == ("pdf", "high")
    # an unambiguous PDF extraction skips the arXiv/SS lookups
    assert "arxiv" not in queried
    assert "ss" not in queried


def test_fetch_arxiv_by_eprint(monkeypatch):
    _mock_sources(monkeypatch, arxiv=TEXT_A)
    result = abstracts.fetch_abstract(eprint="2205.15044")
    assert (result.source, result.confidence) == ("arxiv", "high")
    assert result.abstract == TEXT_A


def test_fetch_arxiv_guessed_from_key(monkeypatch):
    _mock_sources(monkeypatch, arxiv=TEXT_A)
    result = abstracts.fetch_abstract(key="Karch2501.16995v1")
    assert (result.source, result.confidence) == ("arxiv", "medium")


def test_fetch_arxiv_disagrees_with_pdf(monkeypatch):
    _mock_sources(monkeypatch, arxiv=TEXT_B, pdf=PDF_INLINE)
    result = abstracts.fetch_abstract(
        eprint="2205.15044", pdf_path=Path("x.pdf")
    )
    assert result.abstract == TEXT_A
    assert (result.source, result.confidence) == ("pdf", "low")
    assert "arxiv-disagree" in result.note


def test_fetch_semanticscholar_by_doi(monkeypatch):
    queried = _mock_sources(monkeypatch, ss=TEXT_A)
    result = abstracts.fetch_abstract(doi="10.1103/x")
    assert (result.source, result.confidence) == ("semanticscholar", "high")
    assert queried["ss"] == "DOI:10.1103/x"


def test_fetch_semanticscholar_agrees_with_pdf(monkeypatch):
    # PDF_INLINE is a *medium*-confidence extraction, so the SS lookup
    # runs and (agreeing) is preferred
    _mock_sources(monkeypatch, ss=TEXT_A, pdf=PDF_INLINE)
    result = abstracts.fetch_abstract(doi="10.1103/x", pdf_path=Path("x.pdf"))
    assert (result.source, result.confidence) == ("semanticscholar", "high")


def test_fetch_pdf_only_medium(monkeypatch):
    _mock_sources(monkeypatch, pdf=PDF_INLINE)
    result = abstracts.fetch_abstract(pdf_path=Path("x.pdf"))
    assert result.abstract == TEXT_A
    assert (result.source, result.confidence) == ("pdf", "medium")


def test_fetch_nothing_found(monkeypatch):
    _mock_sources(monkeypatch)
    result = abstracts.fetch_abstract(doi="10.1103/x")
    assert result == AbstractResult(
        abstract="",
        source="none",
        confidence="none",
        note=result.note,
        applied=False,
    )
    assert "cr-miss" in result.note


def test_fetch_invalid_candidates_rejected(monkeypatch):
    _mock_sources(monkeypatch, crossref="<jats:p>too short</jats:p>")
    result = abstracts.fetch_abstract(doi="10.1103/x")
    assert result.source == "none"
    assert "cr-invalid:too-short" in result.note


def test_fetch_source_failure_is_error(monkeypatch):
    """When a source fails (rather than definitely having nothing)
    and no abstract is found, the negative is not conclusive."""
    _mock_sources(monkeypatch)

    def crossref_error(doi):
        raise abstracts._SourceError("crossref: down")

    monkeypatch.setattr(abstracts, "_crossref_abstract", crossref_error)
    result = abstracts.fetch_abstract(doi="10.1103/x")
    assert result.source == "error"
    assert result.abstract == ""
    assert "cr-error" in result.note


def test_fetch_unreadable_pdf_is_error(monkeypatch):
    """An attached PDF that cannot be read is a failed source, not
    evidence that no abstract exists."""
    _mock_sources(monkeypatch)  # pdf=None -> "pdftotext-failed"
    result = abstracts.fetch_abstract(pdf_path=Path("x.pdf"))
    assert result.source == "error"
    assert "pdftotext-failed" in result.note


# -- Library.add_abstract --------------------------------------------------- #


def _library_with_entry(fields):
    lib = Library()
    lib["Key2020"] = Entry("article", "Key2020", fields=fields)
    return lib


def _mock_fetch(monkeypatch, result, calls=None):
    def fetch_abstract(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return result

    monkeypatch.setattr(abstracts, "fetch_abstract", fetch_abstract)


HIGH_RESULT = AbstractResult(TEXT_A, "crossref", "high", "ok", False)
MEDIUM_RESULT = AbstractResult(TEXT_A, "pdf", "medium", "pdf-only", False)
NONE_RESULT = AbstractResult("", "none", "none", "cr-miss; no-pdf", False)
ERROR_RESULT = AbstractResult("", "error", "none", "cr-error; no-pdf", False)


def test_add_abstract_stores_high(monkeypatch):
    calls = []
    _mock_fetch(monkeypatch, HIGH_RESULT, calls)
    lib = _library_with_entry({"doi": "10.1103/x", "year": "2020"})
    result = lib.add_abstract("Key2020")
    assert result.applied is True
    assert result.abstract == TEXT_A
    assert lib["Key2020"]["abstract"] == TEXT_A
    assert calls == [
        {
            "doi": "10.1103/x",
            "eprint": None,
            "key": "Key2020",
            "pdf_path": None,
        }
    ]


def test_add_abstract_below_min_confidence(monkeypatch):
    _mock_fetch(monkeypatch, MEDIUM_RESULT)
    lib = _library_with_entry({"year": "2020"})
    result = lib.add_abstract("Key2020")
    assert result.applied is False
    assert result.abstract == TEXT_A  # still reported, for review
    assert "abstract" not in lib["Key2020"]


def test_add_abstract_min_confidence_medium(monkeypatch):
    _mock_fetch(monkeypatch, MEDIUM_RESULT)
    lib = _library_with_entry({"year": "2020"})
    result = lib.add_abstract("Key2020", min_confidence="medium")
    assert result.applied is True
    assert lib["Key2020"]["abstract"] == TEXT_A


def test_add_abstract_invalid_min_confidence():
    lib = _library_with_entry({"year": "2020"})
    with pytest.raises(ValueError, match="min_confidence"):
        lib.add_abstract("Key2020", min_confidence="certain")


def test_add_abstract_unknown_key():
    lib = _library_with_entry({"year": "2020"})
    with pytest.raises(KeyError):
        lib.add_abstract("NoSuchKey")


def test_add_abstract_existing_skipped(monkeypatch):
    def fetch_abstract(**kwargs):  # pragma: no cover
        raise AssertionError("must not fetch")

    monkeypatch.setattr(abstracts, "fetch_abstract", fetch_abstract)
    lib = _library_with_entry({"abstract": "An existing abstract."})
    result = lib.add_abstract("Key2020")
    assert result.applied is False
    assert result.source == "existing"
    assert result.abstract == "An existing abstract."
    assert lib["Key2020"]["abstract"] == "An existing abstract."


def test_add_abstract_overwrite(monkeypatch):
    _mock_fetch(monkeypatch, HIGH_RESULT)
    lib = _library_with_entry({"abstract": "An existing abstract."})
    result = lib.add_abstract("Key2020", overwrite=True)
    assert result.applied is True
    assert lib["Key2020"]["abstract"] == TEXT_A


def test_add_abstract_empty_existing_refetched(monkeypatch):
    # an empty abstract counts as missing, so no overwrite is needed
    _mock_fetch(monkeypatch, HIGH_RESULT)
    lib = _library_with_entry({"abstract": ""})
    result = lib.add_abstract("Key2020")
    assert result.applied is True
    assert lib["Key2020"]["abstract"] == TEXT_A


def test_add_abstract_marks_known_missing(monkeypatch):
    """With a group configured for `abstract`, a clean none-result
    adds the entry to the group (creating it on first use), and group
    members are skipped by later runs without any fetch."""
    _mock_fetch(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"year": "2020"})
    monkeypatch.setattr(
        config.active, "known_missing", {"abstract": "No Abstract"}
    )
    result = lib.add_abstract("Key2020")
    assert result.applied is True
    assert "abstract" not in lib["Key2020"]
    assert lib.groups["No Abstract"] == ("Key2020",)
    assert lib["Key2020"].groups == ("No Abstract",)

    def fetch_abstract(**kwargs):  # pragma: no cover
        raise AssertionError("must not fetch")

    monkeypatch.setattr(abstracts, "fetch_abstract", fetch_abstract)
    result = lib.add_abstract("Key2020")
    assert result.source == "known-missing"
    assert result.applied is False
    assert "'No Abstract'" in result.note


def test_add_abstract_overwrite_researches_known_missing(monkeypatch):
    """`overwrite=True` re-runs the search for a group member; a
    repeated clean no-match leaves the membership (and the library)
    unchanged."""
    _mock_fetch(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"year": "2020"})
    monkeypatch.setattr(
        config.active, "known_missing", {"abstract": "No Abstract"}
    )
    lib.groups["No Abstract"] = ("Key2020",)
    result = lib.add_abstract("Key2020", overwrite=True)
    assert result.source == "none"
    assert result.applied is False
    assert lib.groups["No Abstract"] == ("Key2020",)


def test_add_abstract_unmarks_on_store(monkeypatch):
    """Storing an abstract removes the entry from the group."""
    _mock_fetch(monkeypatch, HIGH_RESULT)
    lib = _library_with_entry({"year": "2020"})
    monkeypatch.setattr(
        config.active, "known_missing", {"abstract": "No Abstract"}
    )
    lib.groups["No Abstract"] = ("Key2020",)
    result = lib.add_abstract("Key2020", overwrite=True)
    assert result.applied is True
    assert lib["Key2020"]["abstract"] == TEXT_A
    assert lib.groups["No Abstract"] == ()


def test_add_abstract_error_never_marks(monkeypatch):
    """A search during which a source failed must not record a
    verified absence (a re-run picks the entry up)."""
    _mock_fetch(monkeypatch, ERROR_RESULT)
    lib = _library_with_entry({"year": "2020"})
    monkeypatch.setattr(
        config.active, "known_missing", {"abstract": "No Abstract"}
    )
    result = lib.add_abstract("Key2020")
    assert result.source == "error"
    assert result.applied is False
    assert "No Abstract" not in lib.groups


def test_add_abstract_none_without_config(monkeypatch):
    """Without a `[known_missing]` configuration, a none-result
    modifies nothing."""
    _mock_fetch(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"year": "2020"})
    result = lib.add_abstract("Key2020")
    assert result.applied is False
    assert "abstract" not in lib["Key2020"]
    assert dict(lib.groups) == {}


def test_entry_add_abstract_detached(monkeypatch):
    """`Entry._add_abstract` works on an entry outside any library;
    without an explicit `pdf_path`, the PDF source is skipped."""
    calls = []
    _mock_fetch(monkeypatch, HIGH_RESULT, calls)
    entry = Entry("article", "Key2020", fields={"doi": "10.1103/x"})
    result = entry._add_abstract()
    assert result.applied is True
    assert entry["abstract"] == TEXT_A
    assert calls == [
        {
            "doi": "10.1103/x",
            "eprint": None,
            "key": "Key2020",
            "pdf_path": None,
        }
    ]


def test_entry_add_abstract_explicit_pdf_path(monkeypatch):
    """An explicitly given `pdf_path` is passed to the fetcher."""
    calls = []
    _mock_fetch(monkeypatch, HIGH_RESULT, calls)
    entry = Entry("article", "Key2020", fields={"doi": "10.1103/x"})
    entry._add_abstract(pdf_path=Path("/papers/x.pdf"))
    assert calls[0]["pdf_path"] == Path("/papers/x.pdf")


def test_add_abstract_finds_pdf_attachment(monkeypatch, tmp_path):
    """The first attached `.pdf` that exists is passed to the
    fetcher, resolved relative to the library directory."""
    refs_dir = Path(__file__).parent / "Refs"
    import shutil
    import warnings

    for pdf in refs_dir.glob("*.pdf"):
        shutil.copy(pdf, tmp_path)
    bibfile = shutil.copy(refs_dir / "refs.bib", tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lib = Library(bibfile)
    calls = []
    _mock_fetch(monkeypatch, HIGH_RESULT, calls)
    lib.add_abstract("GoerzNJP2014", overwrite=True)
    assert calls[0]["pdf_path"] == (
        Path(tmp_path).resolve() / "GoerzNJP2014.pdf"
    )
    assert calls[0]["doi"] == "10.1088/1367-2630/16/5/055012"
    assert calls[0]["eprint"] == "1312.0111"
