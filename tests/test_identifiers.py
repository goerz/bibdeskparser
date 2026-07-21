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


@pytest.mark.parametrize(
    "value, expected",
    [
        ("arXiv:2205.15044", ("arXiv", "2205.15044")),
        ("  arXiv:2205.15044  ", ("arXiv", "2205.15044")),
        ("HAL:hal-00640217", ("HAL", "hal-00640217")),
        ("bioRxiv:2022.09.09.507322", ("bioRxiv", "2022.09.09.507322")),
        ("EarthArXiv:X5129", ("EarthArXiv", "X5129")),
        ("https://example.com/x", ("https", "//example.com/x")),
        ("Phys. Rev. A", None),
        ("J. Phys.: Condens. Matter", None),
        ("arXiv: 2205.15044", None),
        ("", None),
    ],
)
def test_pseudo_journal(value, expected):
    assert identifiers._pseudo_journal(value) == expected


@pytest.mark.parametrize(
    "value, name, identifier",
    [
        ("arXiv:2205.15044", "arXiv", "2205.15044"),
        ("arxiv:2205.15044", "arXiv", "2205.15044"),
        ("HAL:hal-00640217", "HAL", "hal-00640217"),
        ("hal:tel-00007910v2", "HAL", "tel-00007910v2"),
        ("bioRxiv:2022.09.09.507322", "bioRxiv", "2022.09.09.507322"),
        ("biorxiv:089284", "bioRxiv", "089284"),
        ("medRxiv:2020.03.24.20042937", "medRxiv", "2020.03.24.20042937"),
        (
            "ChemRxiv:10.26434/chemrxiv-2021-h5g1x",
            "ChemRxiv",
            "10.26434/chemrxiv-2021-h5g1x",
        ),
        ("SSRN:4466991", "SSRN", "4466991"),
    ],
)
def test_preprint_journal_builtin_archives(value, name, identifier):
    archives = identifiers._BUILTIN_ARCHIVES
    archive, found_id = identifiers._preprint_journal(value, archives)
    assert archive.name == name
    assert found_id == identifier


@pytest.mark.parametrize(
    "value",
    [
        "EarthArXiv:X5129",  # unknown archive
        "https://example.com/x",  # a URL is not a pseudo-journal
        "Phys. Rev. A",
        "J. Phys.: Condens. Matter",
    ],
)
def test_preprint_journal_unrecognized(value):
    archives = identifiers._BUILTIN_ARCHIVES
    assert identifiers._preprint_journal(value, archives) is None


def test_archive_url():
    archives = identifiers._BUILTIN_ARCHIVES
    assert (
        identifiers._archive_url(archives["arxiv"], "2205.15044")
        == "https://arxiv.org/abs/2205.15044"
    )
    assert (
        identifiers._archive_url(archives["hal"], "hal-00640217")
        == "https://hal.science/hal-00640217"
    )
    # ChemRxiv has no identifier-based URLs
    assert identifiers._archive_url(archives["chemrxiv"], "x") is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2205.15044", "2205.15044"),
        ("2205.15044v2", "2205.15044"),
        ("tel-00007910v2", "tel-00007910"),
        ("  2205.15044v10  ", "2205.15044"),
    ],
)
def test_strip_eprint_version(value, expected):
    assert identifiers._strip_eprint_version(value) == expected


@pytest.mark.parametrize(
    "eprint, identifier, expected",
    [
        ("2205.15044", "2205.15044", True),
        ("2205.15044", "2205.15044v2", True),
        ("2205.15044v1", "2205.15044v2", True),
        ("hal-00640217", "HAL-00640217", True),
        ("2205.15044", "2205.15045", False),
        ("hal-00640217", "tel-00007910", False),
    ],
)
def test_eprint_matches(eprint, identifier, expected):
    assert identifiers._eprint_matches(eprint, identifier) is expected


def test_entry_preprint_recognition():
    """The preprint-only predicate: pseudo-journal on any type;
    `misc`/`unpublished` with an eprint; nothing else."""
    archives = identifiers._BUILTIN_ARCHIVES

    class FakeEntry:
        def __init__(self, entry_type, **fields):
            self.entry_type = entry_type
            self._fields = fields

        def get(self, key, default=None):
            return self._fields.get(key, default)

    by_journal = FakeEntry("article", journal="arXiv:2205.15044")
    archive, identifier = identifiers._entry_preprint(by_journal, archives)
    assert (archive.name, identifier) == ("arXiv", "2205.15044")
    for entry_type in ("misc", "unpublished"):
        by_eprint = FakeEntry(entry_type, eprint="2205.15044")
        archive, identifier = identifiers._entry_preprint(by_eprint, archives)
        assert (archive.name, identifier) == ("arXiv", "2205.15044")
    # a thesis with an eprint is not preprint-only
    thesis = FakeEntry("phdthesis", eprint="tel-00007910v2")
    assert identifiers._entry_preprint(thesis, archives) is None
    # a published article with an eprint is not preprint-only
    published = FakeEntry(
        "article", journal="Phys. Rev. A", eprint="2205.15044"
    )
    assert identifiers._entry_preprint(published, archives) is None
    # an unknown archiveprefix is not recognized
    unknown = FakeEntry("misc", eprint="X5129", archiveprefix="EarthArXiv")
    assert identifiers._entry_preprint(unknown, archives) is None
