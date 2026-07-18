"""Tests for the `fetch` module (all network clients mocked)."""

import datetime
from types import SimpleNamespace

import httpx
import pytest

import bibdeskparser.config as config
import bibdeskparser.fetch as fetch
from bibdeskparser import Library


@pytest.fixture(autouse=True)
def _reset_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config.active.reset()
    yield
    config.active.reset()


# -- query classification ----------------------------------------------- #


@pytest.mark.parametrize(
    "query, expected",
    [
        ("10.1103/PhysRevA.89.032334", ("doi", "10.1103/PhysRevA.89.032334")),
        (
            "https://doi.org/10.21468/SciPostPhys.7.6.080",
            ("doi", "10.21468/SciPostPhys.7.6.080"),
        ),
        (
            "https://journals.aps.org/pra/abstract/10.1103/PhysRevA.89.032334",
            ("doi", "10.1103/PhysRevA.89.032334"),
        ),
        ("arXiv:2205.15044", ("arxiv", "2205.15044")),
        ("2205.15044", ("arxiv", "2205.15044")),
        ("2205.15044v2", ("arxiv", "2205.15044v2")),
        (
            "https://arxiv.org/abs/2104.07687v1",
            ("arxiv", "2104.07687v1"),
        ),
        ("quant-ph/0106057", ("arxiv", "quant-ph/0106057")),
        (
            "https://arxiv.org/abs/cond-mat/0411174",
            ("arxiv", "cond-mat/0411174"),
        ),
        # an arXiv identifier wins over a DOI
        (
            "https://doi.org/10.48550/arXiv.2205.15044",
            ("arxiv", "2205.15044"),
        ),
        (
            "optimal control of open quantum systems",
            ("query", "optimal control of open quantum systems"),
        ),
        # a space rules out a DOI
        (
            "krotov 10.1103/xyz optimal",
            ("query", "krotov 10.1103/xyz optimal"),
        ),
    ],
)
def test_classify(query, expected):
    assert fetch._classify(query) == expected


# -- Crossref ------------------------------------------------------------ #


ABSTRACT = (
    "We show that optimizing a quantum gate for an open quantum "
    "system requires the time evolution of only three states. This "
    "represents a significant reduction in computational resources "
    "compared to the complete basis of Liouville space that is "
    "commonly believed necessary for this task, and we illustrate "
    "the reduction for a controlled phasegate with trapped atoms."
)

ARTICLE_RECORD = {
    "type": "journal-article",
    "DOI": "10.1103/physreva.89.032334",
    "title": ["Optimal control theory for a quantum gate"],
    "author": [
        {"family": "Goerz", "given": "Michael"},
        {"family": "Reich", "given": "Daniel M."},
    ],
    "issued": {"date-parts": [[2014, 3, 25]]},
    "short-container-title": ["Phys. Rev. A"],
    "container-title": ["Physical Review A"],
    "volume": "89",
    "issue": "3",
    "article-number": "032334",
    "page": "032334-032340",
    "publisher": "American Physical Society",
}


def _mock_crossref(monkeypatch, response):
    """Replace the Crossref client; returns the list of `works()`
    call kwargs."""
    calls = []

    class FakeCrossref:
        def works(self, **kwargs):
            calls.append(kwargs)
            return response

    monkeypatch.setattr(fetch, "Crossref", FakeCrossref)
    return calls


def test_crossref_article(monkeypatch):
    calls = _mock_crossref(
        monkeypatch, {"status": "ok", "message": ARTICLE_RECORD}
    )
    text = fetch.fetch_bibtex("10.1103/PhysRevA.89.032334")
    assert calls == [{"ids": "10.1103/PhysRevA.89.032334"}]
    assert "@article{Fetched," in text
    assert "author = {Goerz, Michael and Reich, Daniel M.}," in text
    assert "journal = {Phys. Rev. A}," in text
    assert "year = {2014}," in text
    assert "pages = {032334}," in text  # article-number preferred
    assert "number = {3}," in text
    assert "publisher" not in text


def test_crossref_article_with_abstract(monkeypatch):
    record = dict(ARTICLE_RECORD)
    record["abstract"] = (
        f"<jats:title>Abstract</jats:title><jats:p>{ABSTRACT}</jats:p>"
    )
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    text = fetch.fetch_bibtex("10.1103/PhysRevA.89.032334")
    assert "abstract" not in text  # off by default
    text = fetch.fetch_bibtex(
        "10.1103/PhysRevA.89.032334", include_abstract=True
    )
    assert f"abstract = {{{ABSTRACT}}}," in text


def test_crossref_invalid_abstract_omitted(monkeypatch):
    record = dict(ARTICLE_RECORD)
    record["abstract"] = "<jats:p>too short</jats:p>"
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    text = fetch.fetch_bibtex(
        "10.1103/PhysRevA.89.032334", include_abstract=True
    )
    assert "abstract" not in text


def test_crossref_article_page_fallback(monkeypatch):
    record = dict(ARTICLE_RECORD)
    del record["article-number"]
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    text = fetch.fetch_bibtex("10.1103/PhysRevA.89.032334")
    assert "pages = {032334-032340}," in text  # pipeline collapses this


def test_crossref_inproceedings(monkeypatch):
    record = {
        "type": "proceedings-article",
        "DOI": "10.1000/proc.123",
        "title": ["A Conference Talk"],
        "author": [{"family": "Goerz", "given": "Michael"}],
        "editor": [{"family": "Doe", "given": "Jane"}],
        "issued": {"date-parts": [[2019]]},
        "container-title": ["Proceedings of the European Control Conference"],
        "event": {"location": "Naples, Italy"},
        "page": "100-110",
    }
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    text = fetch.fetch_bibtex("10.1000/proc.123")
    assert "@inproceedings{Fetched," in text
    assert (
        "booktitle = {Proceedings of the European Control Conference}," in text
    )
    assert "address = {Naples, Italy}," in text
    assert "editor = {Doe, Jane}," in text
    assert "pages = {100-110}," in text


def test_crossref_book(monkeypatch):
    record = {
        "type": "book",
        "DOI": "10.1002/9781119541219",
        "title": ["Matrix Differential Calculus"],
        "author": [
            {"family": "Magnus", "given": "Jan R."},
            {"family": "Neudecker", "given": "Heinz"},
        ],
        "issued": {"date-parts": [[2019]]},
        "publisher": "Wiley",
        "ISBN": ["9781119541202"],
    }
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    text = fetch.fetch_bibtex("10.1002/9781119541219")
    assert "@book{Fetched," in text
    assert "publisher = {Wiley}," in text
    assert "isbn = {9781119541202}," in text


def test_crossref_collaboration_author(monkeypatch):
    record = dict(ARTICLE_RECORD)
    record["author"] = [
        {"name": "The LIGO Collaboration"},
        {"family": "Goerz", "given": "Michael"},
    ]
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    text = fetch.fetch_bibtex("10.1103/physreva.89.032334")
    assert "author = {The LIGO Collaboration and Goerz, Michael}," in text


def test_crossref_unsupported_type_content_negotiation(monkeypatch):
    record = {"type": "dataset", "DOI": "10.5281/zenodo.1234"}
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    negotiated = []

    def content_negotiation(ids):
        negotiated.append(ids)
        return "@misc{raw, title = {Raw}}"

    monkeypatch.setattr(
        fetch, "cn", SimpleNamespace(content_negotiation=content_negotiation)
    )
    text = fetch.fetch_bibtex("10.5281/zenodo.1234")
    assert negotiated == ["10.5281/zenodo.1234"]
    assert text == "@misc{raw, title = {Raw}}"


def test_crossref_unsupported_type_without_doi(monkeypatch):
    record = {"type": "component"}
    _mock_crossref(
        monkeypatch,
        {"status": "ok", "message": {"items": [record]}},
    )
    with pytest.raises(ValueError, match="not supported"):
        fetch.fetch_bibtex("some free form query")


def test_crossref_query(monkeypatch):
    calls = _mock_crossref(
        monkeypatch,
        {"status": "ok", "message": {"items": [ARTICLE_RECORD]}},
    )
    text = fetch.fetch_bibtex("optimal control theory quantum gate")
    assert calls == [
        {
            "query_bibliographic": "optimal control theory quantum gate",
            "limit": 1,
        }
    ]
    assert "@article{Fetched," in text


def test_crossref_query_no_match(monkeypatch):
    _mock_crossref(monkeypatch, {"status": "ok", "message": {"items": []}})
    with pytest.raises(ValueError, match="no Crossref match"):
        fetch.fetch_bibtex("this query matches nothing")


def test_crossref_bad_status(monkeypatch):
    _mock_crossref(monkeypatch, {"status": "error", "message": {}})
    with pytest.raises(ValueError, match="status 'error'"):
        fetch.fetch_bibtex("10.1103/physreva.89.032334")


def test_crossref_invalid_response(monkeypatch):
    _mock_crossref(monkeypatch, "not a dict")
    with pytest.raises(ValueError, match="invalid"):
        fetch.fetch_bibtex("10.1103/physreva.89.032334")


def test_network_errors_become_valueerror(monkeypatch):
    class FakeCrossref:
        def works(self, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(fetch, "Crossref", FakeCrossref)
    with pytest.raises(ValueError, match="could not fetch"):
        fetch.fetch_bibtex("10.1103/physreva.89.032334")


# -- arXiv ---------------------------------------------------------------- #


def _mock_arxiv(monkeypatch, results):
    """Replace the arxiv module; returns the list of queried id
    lists."""
    searches = []

    class FakeSearch:
        def __init__(self, id_list):
            searches.append(id_list)

    class FakeClient:
        def results(self, search):
            return iter(results)

    monkeypatch.setattr(
        fetch, "arxiv", SimpleNamespace(Client=FakeClient, Search=FakeSearch)
    )
    return searches


def _arxiv_result():
    return SimpleNamespace(
        title="Quantum optimal control via semi-automatic differentiation",
        authors=[
            SimpleNamespace(name="Michael H. Goerz"),
            SimpleNamespace(name="Sebastián C. Carrasco"),
        ],
        published=datetime.datetime(2022, 5, 30, tzinfo=datetime.timezone.utc),
        summary=ABSTRACT,
    )


def test_arxiv(monkeypatch):
    searches = _mock_arxiv(monkeypatch, [_arxiv_result()])
    text = fetch.fetch_bibtex("https://arxiv.org/abs/2205.15044")
    assert searches == [["2205.15044"]]
    assert "@article{Fetched," in text
    assert "author = {Goerz, Michael H. and Carrasco, Sebastián C.}," in text
    assert "journal = {arXiv:2205.15044}," in text
    assert "eprint = {2205.15044}," in text
    assert "archiveprefix = {arXiv}," in text
    assert "year = {2022}," in text
    assert "url = {https://doi.org/10.48550/arXiv.2205.15044}," in text


def test_arxiv_versioned_id(monkeypatch):
    _mock_arxiv(monkeypatch, [_arxiv_result()])
    text = fetch.fetch_bibtex("arXiv:2205.15044v2")
    assert "journal = {arXiv:2205.15044v2}," in text
    assert "eprint = {2205.15044}," in text
    assert "url = {https://doi.org/10.48550/arXiv.2205.15044}," in text


def test_arxiv_with_abstract(monkeypatch):
    _mock_arxiv(monkeypatch, [_arxiv_result()])
    text = fetch.fetch_bibtex("arXiv:2205.15044")
    assert "abstract" not in text  # off by default
    _mock_arxiv(monkeypatch, [_arxiv_result()])
    text = fetch.fetch_bibtex("arXiv:2205.15044", include_abstract=True)
    assert f"abstract = {{{ABSTRACT}}}," in text


def test_arxiv_no_result(monkeypatch):
    _mock_arxiv(monkeypatch, [])
    with pytest.raises(ValueError, match="returned no result"):
        fetch.fetch_bibtex("arXiv:2205.15044")


# -- fetch_text ----------------------------------------------------------- #


def test_fetch_text(monkeypatch):
    def get(url, follow_redirects, timeout):
        assert follow_redirects is True
        return SimpleNamespace(
            raise_for_status=lambda: None, text="@article{x, year = {2020}}"
        )

    monkeypatch.setattr(
        fetch, "httpx", SimpleNamespace(get=get, HTTPError=httpx.HTTPError)
    )
    assert fetch.fetch_text("https://example.com/x.bib") == (
        "@article{x, year = {2020}}"
    )


def test_fetch_text_http_error(monkeypatch):
    def get(url, follow_redirects, timeout):
        raise httpx.HTTPError("404 Not Found")

    monkeypatch.setattr(
        fetch, "httpx", SimpleNamespace(get=get, HTTPError=httpx.HTTPError)
    )
    with pytest.raises(ValueError, match="could not fetch"):
        fetch.fetch_text("https://example.com/missing.bib")


# -- Library.add integration --------------------------------------------- #


def test_library_add(monkeypatch):
    bib = Library()
    bib.strings["pra"] = "Phys. Rev. A"
    _mock_crossref(monkeypatch, {"status": "ok", "message": ARTICLE_RECORD})
    key = bib.add(
        "https://journals.aps.org/pra/abstract/10.1103/PhysRevA.89.032334"
    )
    assert key == "GoerzPRA2014"
    entry = bib[key]
    assert entry["journal"] == "pra"
    assert entry["doi"] == "10.1103/physreva.89.032334"
    assert entry["pages"] == "032334"


def test_library_add_arxiv(monkeypatch):
    bib = Library()
    _mock_arxiv(monkeypatch, [_arxiv_result()])
    key = bib.add("2205.15044")
    assert key == "Goerz2205.15044"
    entry = bib[key]
    assert entry["journal"] == "arXiv:2205.15044"
    assert entry["eprint"] == "2205.15044"
    assert entry["author"] == ("Goerz, Michael H. and Carrasco, Sebastián C.")
    assert "abstract" not in entry


def test_library_add_with_abstract(monkeypatch):
    bib = Library()
    record = dict(ARTICLE_RECORD)
    record["abstract"] = f"<jats:p>{ABSTRACT}</jats:p>"
    _mock_crossref(monkeypatch, {"status": "ok", "message": record})
    key = bib.add("10.1103/PhysRevA.89.032334", add_abstract=True)
    assert bib[key]["abstract"] == ABSTRACT
