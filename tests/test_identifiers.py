"""Tests for the `identifiers` module (DOI/arXiv identifier parsing)."""

import pytest

import bibdeskparser.identifiers as identifiers


@pytest.mark.parametrize(
    "doi, expected",
    [
        (None, None),
        ("", None),
        ("10.1103/PhysRevA.89.032334", "10.1103/PhysRevA.89.032334"),
        ("https://doi.org/10.1103/x", "10.1103/x"),
        ("http://dx.doi.org/10.1103/x", "10.1103/x"),
        ("doi:10.1103/x", "10.1103/x"),
        ("  10.1103/x  ", "10.1103/x"),
    ],
)
def test_normalize_doi(doi, expected):
    assert identifiers._normalize_doi(doi) == expected


@pytest.mark.parametrize(
    "eprint, key, expected",
    [
        ("2205.15044", None, ("2205.15044", True)),
        ("2205.15044v2", None, ("2205.15044v2", True)),
        ("quant-ph/0106057", None, ("quant-ph/0106057", True)),
        ("not-an-id", "Karch2501.16995v1", ("2501.16995", False)),
        (None, "Karch2501.16995v1", ("2501.16995", False)),
        (None, "GoerzPRA2014", (None, False)),
        (None, None, (None, False)),
    ],
)
def test_arxiv_id(eprint, key, expected):
    assert identifiers._arxiv_id(eprint, key) == expected
