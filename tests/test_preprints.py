"""Tests for the `preprints` module and `Library.add_preprint` (all
network clients mocked)."""

import warnings
from types import SimpleNamespace

import pytest

import bibdeskparser.config as config
import bibdeskparser.preprints as preprints
from bibdeskparser import Entry, Library
from bibdeskparser.preprints import PreprintResult

TITLE = "Robustness of high-fidelity Rydberg gates with single-site addressing"

#: A close-but-not-exact variant of TITLE (title ratio ~0.94: accepted
#: only together with an author match).
TITLE_CLOSE = (
    "Robustness of high-fidelity Rydberg gates with single-site "
    "addressability"
)

#: A clearly different title (ratio well below the acceptance floor).
TITLE_OTHER = "Optimal quantum control via semi-automatic differentiation"


class FakeResult:
    """A stand-in for an `arxiv.Result`."""

    def __init__(
        self,
        title,
        *,
        authors=(),
        doi=None,
        short_id="2205.15044v1",
        year=None,
        journal_ref=None,
    ):
        self.title = title
        self.authors = [SimpleNamespace(name=name) for name in authors]
        self.doi = doi
        self._short_id = short_id
        self.published = None if year is None else SimpleNamespace(year=year)
        self.journal_ref = journal_ref

    def get_short_id(self):
        return self._short_id


# -- identifier handling -------------------------------------------------- #


@pytest.mark.parametrize(
    "eprint, expected",
    [
        ("2205.15044", "2205.15044"),
        ("2205.15044v2", "2205.15044"),
        ("arXiv:2205.15044", "2205.15044"),
        ("arxiv: 2205.15044v1", "2205.15044"),
        ("  1103.6050 ", "1103.6050"),
        ("quant-ph/0106057", "quant-ph/0106057"),
        ("quant-ph/0106057v1", "quant-ph/0106057"),
        ("cond-mat.mes-hall/0106057", "cond-mat.mes-hall/0106057"),
    ],
)
def test_normalize_eprint(eprint, expected):
    assert preprints.normalize_eprint(eprint) == expected


@pytest.mark.parametrize(
    "eprint",
    ["", None, "not-an-id", "10.1103/PhysRevA.89.032334", "2205", "v1"],
)
def test_normalize_eprint_invalid(eprint):
    with pytest.raises(ValueError, match="not a valid arXiv identifier"):
        preprints.normalize_eprint(eprint)


# -- normalization helpers ------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "Charting the {QED} Design Landscape",
            "charting the qed design" " landscape",
        ),
        (r"Optimization of $\lambda$-systems", "optimization of systems"),
        ('K{\\"o}rner--Fike bounds', "korner fike bounds"),
        (None, ""),
        ("", ""),
    ],
)
def test_norm_title(raw, expected):
    assert preprints._norm_title(raw) == expected


@pytest.mark.parametrize(
    "authors, expected",
    [
        ("Goerz, Michael H.", "goerz"),
        ("Michael H. Goerz", "goerz"),
        ("Goerz, Michael H. and Reich, Daniel M.", "goerz"),
        ("van der Meer, Jan and Smith, John", "meer"),
        ("Gonz{\\'a}lez, Mar{\\'\\i}a", "gonzalez"),
        ("", ""),
        (None, ""),
    ],
)
def test_first_author_lastname(authors, expected):
    assert preprints._first_author_lastname(authors) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2014", 2014),
        ("1997", 1997),
        ("c. 2014", 2014),
        ("forthcoming", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_year(raw, expected):
    assert preprints._parse_year(raw) == expected


# -- query building --------------------------------------------------------- #


def test_build_queries_order():
    queries = preprints._build_queries(TITLE, "goerz")
    assert queries[0] == (
        'ti:"robustness of high fidelity rydberg gates with single site '
        'addressing" AND au:goerz'
    )
    assert queries[1] == (
        'ti:"robustness of high fidelity rydberg gates with single site '
        'addressing"'
    )
    # distinctive words: longest first, ANDed, with/without author
    assert queries[2].startswith("ti:") and queries[2].endswith("au:goerz")
    assert " AND " in queries[3] and "au:" not in queries[3]
    assert len(queries) == 4


def test_build_queries_no_author():
    queries = preprints._build_queries(TITLE, "")
    assert len(queries) == 2
    assert all("au:" not in query for query in queries)


def test_build_queries_empty_title():
    assert preprints._build_queries("{}", "goerz") == []


def test_distinctive_words_short_title():
    assert preprints._distinctive_words("On Maps") == ["maps", "on"]


# -- matching --------------------------------------------------------------- #


def test_pick_match_doi():
    results = [
        FakeResult(TITLE_OTHER, doi="10.1103/other"),
        FakeResult(TITLE_OTHER, doi="10.1103/PhysRevA.89.032334"),
    ]
    result, _ratio, reason = preprints._pick_match(
        TITLE, "10.1103/physreva.89.032334", "goerz", results
    )
    assert result is results[1]
    assert reason == "doi"


def test_pick_match_doi_postdated_ok():
    """A DOI match is accepted regardless of the submission date."""
    results = [
        FakeResult(TITLE_OTHER, doi="10.1103/x", year=2025),
    ]
    result, _ratio, reason = preprints._pick_match(
        TITLE, "10.1103/x", "goerz", results, year=2002
    )
    assert result is results[0]
    assert reason == "doi"


def test_pick_match_title():
    results = [FakeResult(TITLE)]
    result, ratio, reason = preprints._pick_match(TITLE, None, "", results)
    assert result is results[0]
    assert ratio == pytest.approx(1.0)
    assert reason == "title"


def test_pick_match_title_author():
    results = [FakeResult(TITLE_CLOSE, authors=["Michael H. Goerz"])]
    result, ratio, reason = preprints._pick_match(
        TITLE, None, "goerz", results
    )
    assert result is results[0]
    assert 0.92 <= ratio < 0.97
    assert reason == "title+author"


def test_pick_match_close_title_wrong_author():
    results = [FakeResult(TITLE_CLOSE, authors=["Jane Doe"])]
    result, ratio, reason = preprints._pick_match(
        TITLE, None, "goerz", results
    )
    assert result is None
    assert 0.92 <= ratio < 0.97
    assert reason == ""


def test_pick_match_different_title():
    results = [FakeResult(TITLE_OTHER, authors=["Michael H. Goerz"])]
    result, _ratio, reason = preprints._pick_match(
        TITLE, None, "goerz", results
    )
    assert result is None
    assert reason == ""


def test_pick_match_no_results():
    assert preprints._pick_match(TITLE, None, "goerz", []) == (None, 0.0, "")


def test_pick_match_postdated_rejected():
    """An uncorroborated title match years after publication is a
    title collision, not a preprint."""
    results = [FakeResult(TITLE, year=2025)]
    result, _ratio, reason = preprints._pick_match(
        TITLE, None, "goerz", results, year=1999
    )
    assert result is None
    assert reason == "postdated-unverified(2025>1999)"


def test_pick_match_postdated_journal_ref_corroborates():
    """A late posting whose journal-ref names the entry year passes."""
    results = [
        FakeResult(TITLE, year=2025, journal_ref="Nature 415, 39 (2002)")
    ]
    result, _ratio, reason = preprints._pick_match(
        TITLE, None, "goerz", results, year=2002
    )
    assert result is results[0]
    assert reason == "title"


def test_pick_match_next_year_ok():
    """Publication the year after arXiv submission is the normal case;
    so is submission (up to a year) after publication."""
    results = [FakeResult(TITLE, year=2015)]
    result, _ratio, reason = preprints._pick_match(
        TITLE, None, "goerz", results, year=2014
    )
    assert result is results[0]
    assert reason == "title"


# -- find_preprint ---------------------------------------------------------- #


def test_find_preprint_match(monkeypatch):
    searches = []

    def search(title, lastname):
        searches.append((title, lastname))
        return [FakeResult(TITLE, short_id="2205.15044v3")]

    monkeypatch.setattr(preprints, "_search", search)
    result = preprints.find_preprint(
        title=TITLE, author="Goerz, Michael H.", year="2022"
    )
    assert result == PreprintResult(
        "2205.15044", "title", pytest.approx(1.0), "", False
    )
    assert searches == [(TITLE, "goerz")]


def test_find_preprint_no_results(monkeypatch):
    monkeypatch.setattr(preprints, "_search", lambda title, lastname: [])
    result = preprints.find_preprint(title=TITLE)
    assert result == PreprintResult("", "none", 0.0, "no-results", False)


def test_find_preprint_no_confident_match(monkeypatch):
    monkeypatch.setattr(
        preprints,
        "_search",
        lambda title, lastname: [FakeResult(TITLE_OTHER)],
    )
    result = preprints.find_preprint(title=TITLE)
    assert result.eprint == ""
    assert result.match == "none"
    assert result.note.startswith("best-ratio=")


def test_find_preprint_postdated_note(monkeypatch):
    monkeypatch.setattr(
        preprints,
        "_search",
        lambda title, lastname: [FakeResult(TITLE, year=2025)],
    )
    result = preprints.find_preprint(title=TITLE, year="1999")
    assert result.match == "none"
    assert result.note.startswith("postdated-unverified(2025>1999); ")


def test_find_preprint_error(monkeypatch):
    def search(title, lastname):
        raise ConnectionError("boom")

    monkeypatch.setattr(preprints, "_search", search)
    result = preprints.find_preprint(title=TITLE)
    assert result.match == "error"
    assert result.note == "arxiv-error(ConnectionError: boom)"


def test_find_preprint_no_title():
    result = preprints.find_preprint(title=None)
    assert result == PreprintResult("", "error", 0.0, "no-title", False)
    assert preprints.find_preprint(title="{}").match == "error"


# -- Library.add_preprint --------------------------------------------------- #


def _library_with_entry(fields):
    lib = Library()
    lib["Key2020"] = Entry("article", "Key2020", fields=fields)
    return lib


def _mock_find(monkeypatch, result, calls=None):
    def find_preprint(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return result

    monkeypatch.setattr(preprints, "find_preprint", find_preprint)


def _forbid_find(monkeypatch):
    def find_preprint(**kwargs):  # pragma: no cover
        raise AssertionError("must not search")

    monkeypatch.setattr(preprints, "find_preprint", find_preprint)


FOUND_RESULT = PreprintResult("2205.15044", "doi", 1.0, "", False)
NONE_RESULT = PreprintResult("", "none", 0.55, "best-ratio=0.55", False)
ERROR_RESULT = PreprintResult("", "error", 0.0, "arxiv-error(X: y)", False)


def test_add_preprint_stores_match(monkeypatch):
    calls = []
    _mock_find(monkeypatch, FOUND_RESULT, calls)
    lib = _library_with_entry(
        {
            "title": "A Title",
            "author": "Goerz, Michael H.",
            "doi": "10.1103/x",
            "year": "2022",
        }
    )
    result = lib.add_preprint("Key2020")
    assert result.applied is True
    assert lib["Key2020"]["eprint"] == "2205.15044"
    assert lib["Key2020"]["archiveprefix"] == "arXiv"
    assert calls == [
        {
            "title": "A Title",
            "author": "Goerz, Michael H.",
            "doi": "10.1103/x",
            "year": "2022",
        }
    ]


def test_add_preprint_keeps_archiveprefix(monkeypatch):
    _mock_find(monkeypatch, FOUND_RESULT)
    lib = _library_with_entry({"title": "A Title", "archiveprefix": "arxiv"})
    lib.add_preprint("Key2020")
    assert lib["Key2020"]["archiveprefix"] == "arxiv"


def test_add_preprint_existing_skipped(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title", "eprint": "1103.6050"})
    result = lib.add_preprint("Key2020")
    assert result.applied is False
    assert result.match == "existing"
    assert result.eprint == "1103.6050"
    assert lib["Key2020"]["eprint"] == "1103.6050"


def test_add_preprint_overwrite(monkeypatch):
    _mock_find(monkeypatch, FOUND_RESULT)
    lib = _library_with_entry({"title": "A Title", "eprint": "1103.6050"})
    result = lib.add_preprint("Key2020", overwrite=True)
    assert result.applied is True
    assert lib["Key2020"]["eprint"] == "2205.15044"


def test_add_preprint_empty_marker_researched(monkeypatch):
    """An empty eprint (the searched-no-preprint marker) is re-searched
    without `overwrite`."""
    _mock_find(monkeypatch, FOUND_RESULT)
    lib = _library_with_entry({"title": "A Title", "eprint": ""})
    result = lib.add_preprint("Key2020")
    assert result.applied is True
    assert lib["Key2020"]["eprint"] == "2205.15044"


def test_add_preprint_no_match(monkeypatch):
    _mock_find(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    result = lib.add_preprint("Key2020")
    assert result.applied is False
    assert "eprint" not in lib["Key2020"]


def test_add_preprint_mark_empty(monkeypatch):
    _mock_find(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    result = lib.add_preprint("Key2020", mark_empty=True)
    assert result.applied is True
    assert lib["Key2020"]["eprint"] == ""
    assert "archiveprefix" not in lib["Key2020"]


def test_add_preprint_mark_empty_config(monkeypatch):
    """`mark_empty` defaults to the `[add_preprint]` configuration."""
    _mock_find(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    monkeypatch.setattr(config.active.add_preprint, "mark_empty", True)
    result = lib.add_preprint("Key2020")
    assert result.applied is True
    assert lib["Key2020"]["eprint"] == ""


def test_add_preprint_error_never_marks(monkeypatch):
    """A failed search must not store the empty marker (a re-run
    should pick the entry up again)."""
    _mock_find(monkeypatch, ERROR_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    result = lib.add_preprint("Key2020", mark_empty=True)
    assert result.applied is False
    assert result.match == "error"
    assert "eprint" not in lib["Key2020"]


def test_add_preprint_explicit(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title"})
    result = lib.add_preprint("Key2020", "arXiv:2205.15044v2")
    assert result == PreprintResult("2205.15044", "explicit", None, "", True)
    assert lib["Key2020"]["eprint"] == "2205.15044"
    assert lib["Key2020"]["archiveprefix"] == "arXiv"


def test_add_preprint_explicit_invalid(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title"})
    with pytest.raises(ValueError, match="not a valid arXiv identifier"):
        lib.add_preprint("Key2020", "10.1103/x")
    assert "eprint" not in lib["Key2020"]


def test_add_preprint_explicit_existing(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title", "eprint": "1103.6050"})
    result = lib.add_preprint("Key2020", "2205.15044")
    assert result.applied is False
    assert result.match == "existing"
    assert lib["Key2020"]["eprint"] == "1103.6050"
    result = lib.add_preprint("Key2020", "2205.15044", overwrite=True)
    assert result.applied is True
    assert lib["Key2020"]["eprint"] == "2205.15044"


def test_add_preprint_unknown_key():
    lib = _library_with_entry({"title": "A Title"})
    with pytest.raises(KeyError):
        lib.add_preprint("NoSuchKey")


def test_entry_add_preprint_detached(monkeypatch):
    """`Entry.add_preprint` works on an entry outside any library."""
    _mock_find(monkeypatch, FOUND_RESULT)
    entry = Entry("article", "Key2020", fields={"title": "A Title"})
    result = entry.add_preprint()
    assert result.applied is True
    assert entry["eprint"] == "2205.15044"
    assert entry["archiveprefix"] == "arXiv"


def test_entry_add_preprint_explicit_detached(monkeypatch):
    _forbid_find(monkeypatch)
    entry = Entry("article", "Key2020")
    result = entry.add_preprint("arXiv:2205.15044v2")
    assert result.applied is True
    assert entry["eprint"] == "2205.15044"


# -- Library.add(add_preprint=...) ------------------------------------------ #

_FETCHED_BIBTEX = """
@article{Fetched,
    author = {Goerz, Michael H. and Reich, Daniel M.},
    title = {Optimal control theory for a quantum gate},
    journal = {Phys. Rev. A},
    year = {2014},
    doi = {10.1103/PhysRevA.89.032334},
    pages = {032334},
    volume = {89},
}
"""

_FETCHED_ARXIV_BIBTEX = """
@article{Fetched,
    author = {Goerz, Michael H.},
    title = {Quantum optimal control via semi-automatic differentiation},
    journal = {arXiv:2205.15044},
    eprint = {2205.15044},
    archiveprefix = {arXiv},
    year = {2022},
}
"""


def _mock_fetch(monkeypatch, bibtex):
    import bibdeskparser.fetch as fetch

    monkeypatch.setattr(
        fetch, "fetch_bibtex", lambda query, include_abstract=False: bibtex
    )


def test_add_with_add_preprint(monkeypatch):
    _mock_fetch(monkeypatch, _FETCHED_BIBTEX)
    calls = []
    _mock_find(
        monkeypatch, PreprintResult("1401.1858", "doi", 1.0, "", False), calls
    )
    lib = Library()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # new journal macro
        key = lib.add("10.1103/PhysRevA.89.032334", add_preprint=True)
    assert lib[key]["eprint"] == "1401.1858"
    assert lib[key]["archiveprefix"] == "arXiv"
    assert len(calls) == 1


def test_add_without_add_preprint(monkeypatch):
    _mock_fetch(monkeypatch, _FETCHED_BIBTEX)
    _forbid_find(monkeypatch)
    lib = Library()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # new journal macro
        key = lib.add("10.1103/PhysRevA.89.032334")
    assert "eprint" not in lib[key]


def test_add_add_preprint_config_default(monkeypatch):
    """`add_preprint` defaults to the `[add]` configuration."""
    _mock_fetch(monkeypatch, _FETCHED_BIBTEX)
    _mock_find(monkeypatch, PreprintResult("1401.1858", "doi", 1.0, "", False))
    lib = Library()
    monkeypatch.setattr(config.active.add, "add_preprint", True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # new journal macro
        key = lib.add("10.1103/PhysRevA.89.032334")
    assert lib[key]["eprint"] == "1401.1858"


def test_add_add_preprint_skips_arxiv_entry(monkeypatch):
    """An entry fetched from an arXiv query already has an eprint; the
    preprint search must not run for it."""
    _mock_fetch(monkeypatch, _FETCHED_ARXIV_BIBTEX)
    _forbid_find(monkeypatch)
    lib = Library()
    key = lib.add("2205.15044", add_preprint=True)
    assert lib[key]["eprint"] == "2205.15044"
