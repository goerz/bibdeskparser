"""Tests for the `dois` module and `Library.add_doi` (all network
clients mocked)."""

from types import SimpleNamespace

import pytest

import bibdeskparser.config as config
import bibdeskparser.dois as dois
from bibdeskparser import Entry, Library
from bibdeskparser.dois import DoiResult

TITLE = "Robustness of high-fidelity Rydberg gates with single-site addressing"

#: A close-but-not-exact variant of TITLE (title ratio ~0.94: accepted
#: only together with an author match).
TITLE_CLOSE = (
    "Robustness of high-fidelity Rydberg gates with single-site "
    "addressability"
)

#: A clearly different title (ratio well below the acceptance floor).
TITLE_OTHER = "Optimal quantum control via semi-automatic differentiation"

DOI = "10.1103/physreva.89.032334"


def _item(title, *, doi=DOI, families=(), year=None):
    """A fake Crossref work item."""
    item = {"DOI": doi, "title": [title]}
    if families:
        item["author"] = [{"family": family} for family in families]
    if year is not None:
        item["issued"] = {"date-parts": [[year, 3, 14]]}
    return item


# -- identifier handling -------------------------------------------------- #


@pytest.mark.parametrize(
    "doi, expected",
    [
        ("10.1103/PhysRevA.89.032334", "10.1103/physreva.89.032334"),
        ("doi:10.1103/PhysRevA.89.032334", "10.1103/physreva.89.032334"),
        (
            "https://doi.org/10.1103/PhysRevA.89.032334",
            "10.1103/physreva.89.032334",
        ),
        (
            "http://dx.doi.org/10.1088/0953-4075/44/15/154011",
            "10.1088/0953-4075/44/15/154011",
        ),
        ("  10.48550/arXiv.2205.15044 ", "10.48550/arxiv.2205.15044"),
    ],
)
def test_normalize_doi(doi, expected):
    assert dois.normalize_doi(doi) == expected


@pytest.mark.parametrize(
    "doi",
    ["", None, "not-a-doi", "2205.15044", "10.1103", "10./x", "doi:"],
)
def test_normalize_doi_invalid(doi):
    with pytest.raises(ValueError, match="not a valid DOI"):
        dois.normalize_doi(doi)


# -- Crossref item helpers ------------------------------------------------- #


@pytest.mark.parametrize(
    "title, expected",
    [
        (TITLE, False),
        ("Erratum: " + TITLE, True),
        ("Erratum to: " + TITLE, True),
        ("Corrigendum to " + TITLE, True),
        ("Publisher's Note: " + TITLE, True),
        ("Publisher Correction: " + TITLE, True),
        ("Retraction: " + TITLE, True),
        ("Comment on “" + TITLE + "”", True),
        ("Reply to Comment on " + TITLE, True),
        ("Correcting quantum errors with entanglement", False),
    ],
)
def test_is_amendment(title, expected):
    assert dois._is_amendment(title) is expected


def test_item_title():
    assert dois._item_title(_item(TITLE)) == TITLE
    assert dois._item_title({"DOI": DOI}) == ""
    assert dois._item_title({"DOI": DOI, "title": []}) == ""


def test_item_year():
    assert dois._item_year(_item(TITLE, year=2014)) == 2014
    assert dois._item_year(_item(TITLE)) is None
    assert dois._item_year({"issued": {"date-parts": [[None]]}}) is None


def test_author_matches():
    item = _item(TITLE, families=["González", "Goerz"])
    assert dois._author_matches("goerz", item) is True
    assert dois._author_matches("gonzalez", item) is True
    assert dois._author_matches("doe", item) is False
    assert dois._author_matches("", item) is False
    assert dois._author_matches("goerz", {"DOI": DOI}) is False


# -- matching --------------------------------------------------------------- #


def test_pick_match_title():
    items = [_item(TITLE_OTHER, doi="10.1103/other"), _item(TITLE)]
    item, ratio, reason = dois._pick_match(TITLE, "", items)
    assert item is items[1]
    assert ratio == pytest.approx(1.0)
    assert reason == "title"


def test_pick_match_title_author():
    items = [_item(TITLE_CLOSE, families=["Goerz"])]
    item, ratio, reason = dois._pick_match(TITLE, "goerz", items)
    assert item is items[0]
    assert 0.92 <= ratio < 0.97
    assert reason == "title+author"


def test_pick_match_close_title_wrong_author():
    items = [_item(TITLE_CLOSE, families=["Doe"])]
    item, ratio, reason = dois._pick_match(TITLE, "goerz", items)
    assert item is None
    assert 0.92 <= ratio < 0.97
    assert reason == ""


def test_pick_match_different_title():
    items = [_item(TITLE_OTHER, families=["Goerz"])]
    item, _ratio, reason = dois._pick_match(TITLE, "goerz", items)
    assert item is None
    assert reason == ""


def test_pick_match_no_results():
    assert dois._pick_match(TITLE, "goerz", []) == (None, 0.0, "")


def test_pick_match_skips_incomplete_items():
    items = [{"title": [TITLE]}, {"DOI": DOI, "title": []}]
    assert dois._pick_match(TITLE, "goerz", items) == (None, 0.0, "")


def test_pick_match_year_mismatch():
    """An exact title match published in a very different year is a
    title collision, not this paper."""
    items = [_item(TITLE, year=2025)]
    item, _ratio, reason = dois._pick_match(TITLE, "goerz", items, year=1999)
    assert item is None
    assert reason == "year-mismatch(2025!=1999)"


def test_pick_match_adjacent_year_ok():
    """Online-first publication makes off-by-one years routine."""
    items = [_item(TITLE, year=2013)]
    item, _ratio, reason = dois._pick_match(TITLE, "goerz", items, year=2014)
    assert item is items[0]
    assert reason == "title"


def test_pick_match_no_entry_year():
    items = [_item(TITLE, year=2025)]
    item, _ratio, reason = dois._pick_match(TITLE, "goerz", items)
    assert item is items[0]
    assert reason == "title"


def test_pick_match_rejects_erratum():
    """An erratum embeds the original title (and shares the authors),
    but must never match the original paper."""
    items = [
        _item("Erratum: " + TITLE + " [Phys. Rev. A 89, 032334 (2014)]"),
        _item(TITLE_CLOSE, families=["Goerz"], doi="10.1103/close"),
    ]
    item, _ratio, reason = dois._pick_match(TITLE, "goerz", items)
    assert item is items[1]
    assert item["DOI"] == "10.1103/close"
    assert reason == "title+author"


def test_pick_match_amendment_entry_matches_amendment():
    """An entry that *is* an erratum matches only amendment records."""
    erratum_title = "Erratum: " + TITLE
    items = [_item(TITLE, doi="10.1103/original"), _item(erratum_title)]
    item, _ratio, reason = dois._pick_match(erratum_title, "goerz", items)
    assert item is items[1]
    assert reason == "title"


# -- find_doi --------------------------------------------------------------- #


def _mock_arxiv_doi(monkeypatch, doi, calls=None):
    def _arxiv_doi(arxiv_id):
        if calls is not None:
            calls.append(arxiv_id)
        if isinstance(doi, Exception):
            raise doi
        return doi

    monkeypatch.setattr(dois, "_arxiv_doi", _arxiv_doi)


def _mock_search(monkeypatch, items, calls=None):
    def _search(title, lastname):
        if calls is not None:
            calls.append((title, lastname))
        if isinstance(items, Exception):
            raise items
        return items

    monkeypatch.setattr(dois, "_search", _search)


def _forbid_search(monkeypatch):
    def _search(title, lastname):  # pragma: no cover
        raise AssertionError("must not search")

    monkeypatch.setattr(dois, "_search", _search)


def _forbid_arxiv(monkeypatch):
    def _arxiv_doi(arxiv_id):  # pragma: no cover
        raise AssertionError("must not contact arXiv")

    monkeypatch.setattr(dois, "_arxiv_doi", _arxiv_doi)


def test_find_doi_via_eprint(monkeypatch):
    calls = []
    _mock_arxiv_doi(monkeypatch, DOI, calls)
    _forbid_search(monkeypatch)
    result = dois.find_doi(title=TITLE, eprint="2205.15044v2")
    assert result == DoiResult(DOI, "eprint", None, "", False)
    assert calls == ["2205.15044"]


def test_find_doi_eprint_no_doi_falls_back(monkeypatch):
    """An eprint without a DOI on arXiv falls back to the Crossref
    search."""
    _mock_arxiv_doi(monkeypatch, None)
    _mock_search(monkeypatch, [_item(TITLE)])
    result = dois.find_doi(title=TITLE, eprint="2205.15044")
    assert result.doi == DOI
    assert result.match == "title"
    assert "arxiv-no-doi" in result.note


def test_find_doi_ignores_invalid_eprint(monkeypatch):
    """A non-arXiv eprint value is ignored (no arXiv lookup)."""
    _forbid_arxiv(monkeypatch)
    _mock_search(monkeypatch, [_item(TITLE)])
    result = dois.find_doi(title=TITLE, eprint="hal-00640217")
    assert result.doi == DOI
    assert result.match == "title"


def test_find_doi_search_match(monkeypatch):
    calls = []
    _mock_search(monkeypatch, [_item(TITLE)], calls)
    result = dois.find_doi(title=TITLE, author="Goerz, Michael H.")
    assert result == DoiResult(DOI, "title", pytest.approx(1.0), "", False)
    assert calls == [(TITLE, "goerz")]


def test_find_doi_uppercase_result_lowercased(monkeypatch):
    _mock_search(monkeypatch, [_item(TITLE, doi="10.1103/PhysRevA.89.032334")])
    result = dois.find_doi(title=TITLE)
    assert result.doi == DOI


def test_find_doi_no_results(monkeypatch):
    _mock_search(monkeypatch, [])
    result = dois.find_doi(title=TITLE)
    assert result == DoiResult("", "none", 0.0, "no-results", False)


def test_find_doi_no_confident_match(monkeypatch):
    _mock_search(monkeypatch, [_item(TITLE_OTHER)])
    result = dois.find_doi(title=TITLE)
    assert result.doi == ""
    assert result.match == "none"
    assert result.note.startswith("best-ratio=")


def test_find_doi_year_mismatch_note(monkeypatch):
    _mock_search(monkeypatch, [_item(TITLE, year=2025)])
    result = dois.find_doi(title=TITLE, year="1999")
    assert result.match == "none"
    assert result.note.startswith("year-mismatch(2025!=1999); ")


def test_find_doi_search_error(monkeypatch):
    _mock_search(monkeypatch, ConnectionError("boom"))
    result = dois.find_doi(title=TITLE)
    assert result.match == "error"
    assert result.note == "crossref-error(ConnectionError: boom)"


def test_find_doi_arxiv_error_no_match_is_error(monkeypatch):
    """When the arXiv lookup failed, a clean Crossref no-match is not
    conclusive (the paper's DOI may be on arXiv)."""
    _mock_arxiv_doi(monkeypatch, ConnectionError("boom"))
    _mock_search(monkeypatch, [])
    result = dois.find_doi(title=TITLE, eprint="2205.15044")
    assert result.match == "error"
    assert result.note.startswith("arxiv-error(ConnectionError: boom); ")


def test_find_doi_arxiv_error_search_match_ok(monkeypatch):
    """A failed arXiv lookup does not spoil a confident Crossref
    match."""
    _mock_arxiv_doi(monkeypatch, ConnectionError("boom"))
    _mock_search(monkeypatch, [_item(TITLE)])
    result = dois.find_doi(title=TITLE, eprint="2205.15044")
    assert result.doi == DOI
    assert result.match == "title"


def test_find_doi_no_title(monkeypatch):
    _forbid_arxiv(monkeypatch)
    _forbid_search(monkeypatch)
    result = dois.find_doi(title=None)
    assert result == DoiResult("", "error", None, "no-title", False)
    assert dois.find_doi(title="{}").match == "error"


def test_find_doi_no_title_after_arxiv_miss(monkeypatch):
    _mock_arxiv_doi(monkeypatch, None)
    _forbid_search(monkeypatch)
    result = dois.find_doi(eprint="2205.15044")
    assert result.match == "error"
    assert result.note == "arxiv-no-doi; no-title"


# -- _arxiv_doi ------------------------------------------------------------- #


def _mock_arxiv_results(monkeypatch, results):
    import bibdeskparser.preprints as preprints

    class FakeClient:
        def results(self, search):
            return iter(results)

    monkeypatch.setattr(preprints, "_CLIENT", FakeClient())


def test_arxiv_doi(monkeypatch):
    _mock_arxiv_results(
        monkeypatch,
        [SimpleNamespace(doi="10.1103/PhysRevA.89.032334")],
    )
    assert dois._arxiv_doi("1401.1858") == DOI


def test_arxiv_doi_none_recorded(monkeypatch):
    _mock_arxiv_results(monkeypatch, [SimpleNamespace(doi=None)])
    assert dois._arxiv_doi("1401.1858") is None


def test_arxiv_doi_no_such_paper(monkeypatch):
    _mock_arxiv_results(monkeypatch, [])
    assert dois._arxiv_doi("1401.1858") is None


def test_arxiv_doi_datacite_ignored(monkeypatch):
    """arXiv's own DataCite DOI merely restates the identifier."""
    _mock_arxiv_results(
        monkeypatch,
        [SimpleNamespace(doi="10.48550/arXiv.2205.15044")],
    )
    assert dois._arxiv_doi("2205.15044") is None


# -- Library.add_doi -------------------------------------------------------- #


def _library_with_entry(fields, entry_type="article"):
    lib = Library()
    lib["Key2020"] = Entry(entry_type, "Key2020", fields=fields)
    return lib


def _mock_find(monkeypatch, result, calls=None):
    def find_doi(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return result

    monkeypatch.setattr(dois, "find_doi", find_doi)


def _forbid_find(monkeypatch):
    def find_doi(**kwargs):  # pragma: no cover
        raise AssertionError("must not search")

    monkeypatch.setattr(dois, "find_doi", find_doi)


FOUND_RESULT = DoiResult(DOI, "title", 1.0, "", False)
NONE_RESULT = DoiResult("", "none", 0.55, "best-ratio=0.55", False)
ERROR_RESULT = DoiResult("", "error", 0.0, "crossref-error(X: y)", False)


def test_add_doi_stores_match(monkeypatch):
    calls = []
    _mock_find(monkeypatch, FOUND_RESULT, calls)
    lib = _library_with_entry(
        {
            "title": "A Title",
            "author": "Goerz, Michael H.",
            "year": "2014",
            "eprint": "1401.1858",
        }
    )
    result = lib.add_doi("Key2020")
    assert result.applied is True
    assert lib["Key2020"]["doi"] == DOI
    assert calls == [
        {
            "title": "A Title",
            "author": "Goerz, Michael H.",
            "year": "2014",
            "eprint": "1401.1858",
        }
    ]


def test_add_doi_existing_skipped(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title", "doi": "10.1103/x"})
    result = lib.add_doi("Key2020")
    assert result.applied is False
    assert result.match == "existing"
    assert result.doi == "10.1103/x"
    assert lib["Key2020"]["doi"] == "10.1103/x"


def test_add_doi_overwrite(monkeypatch):
    _mock_find(monkeypatch, FOUND_RESULT)
    lib = _library_with_entry({"title": "A Title", "doi": "10.1103/x"})
    result = lib.add_doi("Key2020", overwrite=True)
    assert result.applied is True
    assert lib["Key2020"]["doi"] == DOI


def test_add_doi_no_match(monkeypatch):
    _mock_find(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    result = lib.add_doi("Key2020")
    assert result.applied is False
    assert "doi" not in lib["Key2020"]


def test_add_doi_skips_preprint_only(monkeypatch):
    """A preprint-only entry is never searched: the search would find
    the published version's DOI."""
    _forbid_find(monkeypatch)
    lib = _library_with_entry(
        {"title": "A Title", "journal": "arXiv:2205.15044"},
    )
    result = lib.add_doi("Key2020")
    assert result.match == "preprint"
    assert result.applied is False
    assert result.doi == ""
    assert "doi" not in lib["Key2020"]


def test_add_doi_overwrite_preprint_only_keeps_doi(monkeypatch):
    """`overwrite=True` on a preprint-only entry that has a DOI (the
    normal state for an imported arXiv preprint) still skips the
    search, and the result reports the entry's stored DOI, not an
    empty one."""
    _forbid_find(monkeypatch)
    lib = _library_with_entry(
        {
            "title": "A Title",
            "journal": "arXiv:2205.15044",
            "doi": "10.48550/arxiv.2205.15044",
        },
    )
    result = lib.add_doi("Key2020", overwrite=True)
    assert result.match == "preprint"
    assert result.applied is False
    assert result.doi == "10.48550/arxiv.2205.15044"
    assert lib["Key2020"]["doi"] == "10.48550/arxiv.2205.15044"


def test_add_doi_preprint_only_never_marked(monkeypatch):
    """A skipped preprint-only entry is not "verified to have no
    DOI"; it must not enter the known-missing group."""
    _forbid_find(monkeypatch)
    lib = _library_with_entry(
        {"title": "A Title", "eprint": "2205.15044"},
        entry_type="unpublished",
    )
    monkeypatch.setattr(config.active, "known_missing", {"doi": "No DOI"})
    result = lib.add_doi("Key2020")
    assert result.match == "preprint"
    assert result.applied is False
    assert "No DOI" not in lib.groups


def test_add_doi_explicit_on_preprint_only(monkeypatch):
    """An explicitly given DOI is stored even on a preprint-only
    entry (the caller asserts the match)."""
    _forbid_find(monkeypatch)
    lib = _library_with_entry(
        {"title": "A Title", "journal": "arXiv:2205.15044"},
    )
    result = lib.add_doi("Key2020", "10.48550/arXiv.2205.15044")
    assert result.applied is True
    assert lib["Key2020"]["doi"] == "10.48550/arxiv.2205.15044"


def test_add_doi_marks_known_missing(monkeypatch):
    """With a group configured for `doi`, a clean no-match adds the
    entry to the group (creating it on first use), and group members
    are skipped by later runs without any lookup."""
    _mock_find(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    monkeypatch.setattr(config.active, "known_missing", {"doi": "No DOI"})
    result = lib.add_doi("Key2020")
    assert result.applied is True
    assert "doi" not in lib["Key2020"]
    assert lib.groups["No DOI"] == ("Key2020",)
    _forbid_find(monkeypatch)
    result = lib.add_doi("Key2020")
    assert result.match == "known-missing"
    assert result.applied is False
    assert "'No DOI'" in result.note


def test_add_doi_overwrite_researches_known_missing(monkeypatch):
    """`overwrite=True` re-runs the lookup for a group member; a
    repeated clean no-match leaves the membership unchanged."""
    _mock_find(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    monkeypatch.setattr(config.active, "known_missing", {"doi": "No DOI"})
    lib.groups["No DOI"] = ("Key2020",)
    result = lib.add_doi("Key2020", overwrite=True)
    assert result.match == "none"
    assert result.applied is False
    assert lib.groups["No DOI"] == ("Key2020",)


def test_add_doi_unmarks_on_match(monkeypatch):
    """A lookup match removes the entry from the group."""
    _mock_find(monkeypatch, FOUND_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    monkeypatch.setattr(config.active, "known_missing", {"doi": "No DOI"})
    lib.groups["No DOI"] = ("Key2020",)
    result = lib.add_doi("Key2020", overwrite=True)
    assert result.applied is True
    assert lib["Key2020"]["doi"] == DOI
    assert lib.groups["No DOI"] == ()


def test_add_doi_explicit_unmarks(monkeypatch):
    """An explicitly given DOI (the caller asserts it exists) removes
    a stale group membership, without any lookup."""
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title"})
    monkeypatch.setattr(config.active, "known_missing", {"doi": "No DOI"})
    lib.groups["No DOI"] = ("Key2020",)
    result = lib.add_doi("Key2020", "10.1103/PhysRevA.89.032334")
    assert result.applied is True
    assert lib["Key2020"]["doi"] == DOI
    assert lib.groups["No DOI"] == ()


def test_add_doi_no_match_without_config(monkeypatch):
    """Without a `[known_missing]` configuration, a clean no-match
    modifies nothing."""
    _mock_find(monkeypatch, NONE_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    result = lib.add_doi("Key2020")
    assert result.applied is False
    assert "doi" not in lib["Key2020"]
    assert dict(lib.groups) == {}


def test_add_doi_error_never_marks(monkeypatch):
    """A failed lookup must not record a verified absence (a re-run
    should pick the entry up again)."""
    _mock_find(monkeypatch, ERROR_RESULT)
    lib = _library_with_entry({"title": "A Title"})
    monkeypatch.setattr(config.active, "known_missing", {"doi": "No DOI"})
    result = lib.add_doi("Key2020")
    assert result.applied is False
    assert result.match == "error"
    assert "doi" not in lib["Key2020"]
    assert "No DOI" not in lib.groups


def test_add_doi_explicit(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title"})
    result = lib.add_doi(
        "Key2020", "https://doi.org/10.1103/PhysRevA.89.032334"
    )
    assert result == DoiResult(DOI, "explicit", None, "", True)
    assert lib["Key2020"]["doi"] == DOI


def test_add_doi_explicit_invalid(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title"})
    with pytest.raises(ValueError, match="not a valid DOI"):
        lib.add_doi("Key2020", "2205.15044")
    assert "doi" not in lib["Key2020"]


def test_add_doi_explicit_existing(monkeypatch):
    _forbid_find(monkeypatch)
    lib = _library_with_entry({"title": "A Title", "doi": "10.1103/x"})
    result = lib.add_doi("Key2020", DOI)
    assert result.applied is False
    assert result.match == "existing"
    assert lib["Key2020"]["doi"] == "10.1103/x"
    result = lib.add_doi("Key2020", DOI, overwrite=True)
    assert result.applied is True
    assert lib["Key2020"]["doi"] == DOI


def test_add_doi_unknown_key():
    lib = _library_with_entry({"title": "A Title"})
    with pytest.raises(KeyError):
        lib.add_doi("NoSuchKey")


def test_entry_add_doi_detached(monkeypatch):
    """`Entry._add_doi` works on an entry outside any library."""
    _mock_find(monkeypatch, FOUND_RESULT)
    entry = Entry("article", "Key2020", fields={"title": "A Title"})
    result = entry._add_doi()
    assert result.applied is True
    assert entry["doi"] == DOI


def test_entry_add_doi_explicit_detached(monkeypatch):
    _forbid_find(monkeypatch)
    entry = Entry("article", "Key2020")
    result = entry._add_doi("doi:10.1103/PhysRevA.89.032334")
    assert result.applied is True
    assert entry["doi"] == DOI
