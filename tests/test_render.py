"""Tests for `bibdeskparser.render`."""

from pathlib import Path

import bibtexparser
import pytest

import bibdeskparser.config as config
from bibdeskparser import ValueString
from bibdeskparser.entry import Entry
from bibdeskparser.middleware import parse_stack
from bibdeskparser.render import (
    _bold,
    _detex,
    _format_authors,
    _format_eprint,
    _format_pages,
    _italic,
    _join_parts,
    _link,
    _mono,
    render_entries,
    render_entry,
)

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the process-global configuration around every test
    (rendering reads the `preprint_archives` setting)."""
    config.active.reset()
    yield
    config.active.reset()


def _load_refs():
    """Load `tests/Refs/refs.bib` and return a `{key: Entry}` dict."""
    text = REFS_BIB.read_text(encoding="utf-8")
    bib = bibtexparser.parse_string(text, parse_stack=parse_stack())
    return {
        model_entry.key: Entry._wrap(model_entry)
        for model_entry in bib.entries
    }


@pytest.fixture(scope="module")
def refs():
    """`{key: Entry}` for every entry in `tests/Refs/refs.bib`."""
    return _load_refs()


def _make_entry(entry_type, key, **fields):
    """Build a standalone `Entry` from plain string fields."""
    return Entry(entry_type, key, fields=fields)


# -- golden strings for hand-built entries ---------------------------- #


def test_render_entry_article_markdown_golden():
    """Full golden string for a minimal article, markdown format."""
    entry = _make_entry(
        "article",
        "Doe2024",
        author="Doe, Jane and Roe, Richard",
        title="A Great Discovery",
        journal="Phys. Rev. A",
        volume="99",
        year="2024",
        doi="10.1103/PhysRevA.99.012345",
    )
    assert render_entry(entry) == (
        "J. Doe and R. Roe. *A Great Discovery*. "
        "[Phys. Rev. A **99**]"
        "(https://doi.org/10.1103/PhysRevA.99.012345) (2024)."
    )


def test_render_entry_article_tex_golden():
    """Full golden string for a minimal article, tex format."""
    entry = _make_entry(
        "article",
        "Doe2024",
        author="Doe, Jane and Roe, Richard",
        title="A Great Discovery",
        journal="Phys. Rev. A",
        volume="99",
        year="2024",
        doi="10.1103/PhysRevA.99.012345",
    )
    assert render_entry(entry, format="tex") == (
        "J. Doe and R. Roe. \\textit{A Great Discovery}. "
        "\\href{https://doi.org/10.1103/PhysRevA.99.012345}"
        "{Phys. Rev. A \\textbf{99}} (2024)."
    )


def test_render_entry_article_html_golden():
    """Full golden string for a minimal article, html format."""
    entry = _make_entry(
        "article",
        "Doe2024",
        author="Doe, Jane and Roe, Richard",
        title="A Great Discovery",
        journal="Phys. Rev. A",
        volume="99",
        year="2024",
        doi="10.1103/PhysRevA.99.012345",
    )
    assert render_entry(entry, format="html") == (
        "J. Doe and R. Roe. <i>A Great Discovery</i>. "
        '<a href="https://doi.org/10.1103/PhysRevA.99.012345">'
        "Phys. Rev. A <b>99</b></a> (2024)."
    )


def test_render_entries_markdown_golden():
    """Full golden string for a 2-entry bibliography, markdown."""
    entry1 = _make_entry(
        "article",
        "Doe2024",
        author="Doe, Jane",
        title="A Great Discovery",
        journal="Phys. Rev. A",
        volume="99",
        year="2024",
    )
    entry2 = _make_entry(
        "mastersthesis",
        "Smith2020",
        author="Smith, John",
        title="A Thesis",
        school="Test University",
        year="2020",
    )
    assert render_entries([entry1, entry2]) == (
        "J. Doe. *A Great Discovery*. Phys. Rev. A **99** (2024).\n\n"
        "J. Smith. *A Thesis*. Master's thesis, "
        "Test University (2020)."
    )


def test_render_entries_tex_golden():
    """Full golden string for a 2-entry bibliography, tex format."""
    entry1 = _make_entry(
        "article",
        "Doe2024",
        author="Doe, Jane",
        title="A Great Discovery",
        journal="Phys. Rev. A",
        volume="99",
        year="2024",
    )
    entry2 = _make_entry(
        "mastersthesis",
        "Smith2020",
        author="Smith, John",
        title="A Thesis",
        school="Test University",
        year="2020",
    )
    assert render_entries([entry1, entry2], format="tex") == (
        "J. Doe. \\textit{A Great Discovery}. "
        "Phys. Rev. A \\textbf{99} (2024).\n\n"
        "J. Smith. \\textit{A Thesis}. Master's thesis, "
        "Test University (2020)."
    )


def test_render_entries_html_golden():
    """Full golden string for a 2-entry bibliography, html format."""
    entry1 = _make_entry(
        "article",
        "Doe2024",
        author="Doe, Jane",
        title="A Great Discovery",
        journal="Phys. Rev. A",
        volume="99",
        year="2024",
    )
    entry2 = _make_entry(
        "mastersthesis",
        "Smith2020",
        author="Smith, John",
        title="A Thesis",
        school="Test University",
        year="2020",
    )
    assert render_entries([entry1, entry2], format="html") == (
        "<p>J. Doe. <i>A Great Discovery</i>. "
        "Phys. Rev. A <b>99</b> (2024).</p>\n\n"
        "<p>J. Smith. <i>A Thesis</i>. Master's thesis, "
        "Test University (2020).</p>"
    )


def _two_entries():
    entry1 = _make_entry(
        "article",
        "Doe2024",
        author="Doe, Jane",
        title="A Great Discovery",
        journal="Phys. Rev. A",
        volume="99",
        year="2024",
    )
    entry2 = _make_entry(
        "mastersthesis",
        "Smith2020",
        author="Smith, John",
        title="A Thesis",
        school="Test University",
        year="2020",
    )
    return [entry1, entry2]


def test_render_entries_numbered_list_golden():
    """`style="numbered list"` per format."""
    entries = _two_entries()
    assert render_entries(entries, style="numbered list") == (
        "1. J. Doe. *A Great Discovery*. Phys. Rev. A **99** (2024).\n"
        "2. J. Smith. *A Thesis*. Master's thesis, "
        "Test University (2020)."
    )
    assert render_entries(entries, format="tex", style="numbered list") == (
        "\\begin{enumerate}\n"
        "\\item J. Doe. \\textit{A Great Discovery}. "
        "Phys. Rev. A \\textbf{99} (2024).\n"
        "\\item J. Smith. \\textit{A Thesis}. Master's thesis, "
        "Test University (2020).\n"
        "\\end{enumerate}"
    )
    assert render_entries(entries, format="html", style="numbered list") == (
        "<ol>\n"
        "<li>J. Doe. <i>A Great Discovery</i>. "
        "Phys. Rev. A <b>99</b> (2024).</li>\n"
        "<li>J. Smith. <i>A Thesis</i>. Master's thesis, "
        "Test University (2020).</li>\n"
        "</ol>"
    )


def test_render_entries_itemized_list_golden():
    """`style="itemized list"` per format."""
    entries = _two_entries()
    assert render_entries(entries, style="itemized list") == (
        "- J. Doe. *A Great Discovery*. Phys. Rev. A **99** (2024).\n"
        "- J. Smith. *A Thesis*. Master's thesis, "
        "Test University (2020)."
    )
    assert render_entries(entries, format="tex", style="itemized list") == (
        "\\begin{itemize}\n"
        "\\item J. Doe. \\textit{A Great Discovery}. "
        "Phys. Rev. A \\textbf{99} (2024).\n"
        "\\item J. Smith. \\textit{A Thesis}. Master's thesis, "
        "Test University (2020).\n"
        "\\end{itemize}"
    )
    assert render_entries(entries, format="html", style="itemized list") == (
        "<ul>\n"
        "<li>J. Doe. <i>A Great Discovery</i>. "
        "Phys. Rev. A <b>99</b> (2024).</li>\n"
        "<li>J. Smith. <i>A Thesis</i>. Master's thesis, "
        "Test University (2020).</li>\n"
        "</ul>"
    )


def test_render_entries_default_vs_paragraphs_single_html():
    """A single HTML citation is unwrapped for `"default"` but wrapped
    in a `<p>` for `"paragraphs"`; both wrap when there are several."""
    [entry] = [_two_entries()[0]]
    bare = render_entry(entry, format="html")
    # single entry: default is unwrapped, paragraphs is wrapped
    assert render_entries([entry], format="html", style="default") == bare
    assert render_entries([entry], format="html", style="paragraphs") == (
        f"<p>{bare}</p>"
    )
    # default and paragraphs agree once there is more than one entry
    entries = _two_entries()
    assert render_entries(
        entries, format="html", style="default"
    ) == render_entries(entries, format="html", style="paragraphs")
    # for markdown/tex, default and paragraphs are identical throughout
    for fmt in ("markdown", "tex"):
        assert render_entries(
            [entry], format=fmt, style="default"
        ) == render_entries([entry], format=fmt, style="paragraphs")


# -- structural tests on real fixture entries -------------------------- #


@pytest.mark.parametrize("fmt", ["markdown", "tex", "html"])
def test_render_article_with_doi(refs, fmt):
    """An article with a DOI, eprint, and a URL: author/title/DOI/arXiv
    all present, title links to the URL (not the DOI)."""
    entry = refs["GoerzJPB2011"]
    rendered = render_entry(entry, format=fmt)
    assert "Goerz" in rendered
    assert "Calarco" in rendered
    assert "Koch" in rendered
    if fmt == "markdown":
        # no stray title-protection braces leak into markdown output
        # (tex/html legitimately use braces for their own markup)
        assert "{" not in rendered
    assert "quantum speed limit" in rendered
    # title links to the entry's URL, not the DOI
    assert "stacks.iop.org" in rendered
    # DOI links the journal/volume/pages segment
    assert "https://doi.org/10.1088/0953-4075/44/15/154011" in rendered
    # arXiv eprint is linked
    assert "arXiv:1103.6050" in rendered
    assert "https://arxiv.org/abs/1103.6050" in rendered
    assert rendered.endswith(".")


@pytest.mark.parametrize("fmt", ["markdown", "tex", "html"])
def test_render_article_no_bdsk_url_uses_doi_journal_link(refs, fmt):
    """An article with a DOI/eprint but no `bdsk-url-N` field: the
    title itself is unlinked (articles never fall back to the DOI for
    the title link), but the DOI still links the journal segment."""
    entry = refs["GoerzA2023"]
    assert entry.urls == ()
    rendered = render_entry(entry, format=fmt)
    assert "Robust Optimized Pulse Schemes" in rendered
    assert "https://doi.org/10.3390/atoms11020036" in rendered
    assert "arXiv:2212.12602" in rendered
    if fmt == "markdown":
        assert "{" not in rendered


@pytest.mark.parametrize("fmt", ["markdown", "tex", "html"])
def test_render_mastersthesis(refs, fmt):
    """A `mastersthesis` with a `type` override ("Diplomarbeit")."""
    entry = refs["GoerzDiploma2010"]
    rendered = render_entry(entry, format=fmt)
    assert "M. Goerz" in rendered
    assert "Diplomarbeit" in rendered
    assert "Master's thesis" not in rendered
    assert "Freie Universit" in rendered
    assert "2010" in rendered
    # title links to the bdsk-url
    assert "michaelgoerz.net" in rendered
    if fmt == "markdown":
        assert "{" not in rendered


@pytest.mark.parametrize("fmt", ["markdown", "tex", "html"])
def test_render_phdthesis(refs, fmt):
    """A `phdthesis` with no `type` override: default "Ph.D. thesis"
    label, no title link (no URL, no DOI)."""
    entry = refs["BrionPhd2004"]
    assert entry.urls == ()
    assert entry.get("doi") is None
    rendered = render_entry(entry, format=fmt)
    assert "E. Brion" in rendered
    assert "Ph.D. thesis" in rendered
    assert "Universit" in rendered
    assert "2014" in rendered


@pytest.mark.parametrize("fmt", ["markdown", "tex", "html"])
def test_render_inproceedings(refs, fmt):
    """An `inproceedings` entry: booktitle italicized, DOI links the
    title (no `bdsk-url-N` field present)."""
    entry = refs["SuominenSGS2014"]
    assert entry.urls == ()
    rendered = render_entry(entry, format=fmt)
    assert "Suominen" in rendered
    assert "In:" in rendered
    assert "Quantum Information and Coherence" in rendered
    assert "https://doi.org/10.1007/978-3-319-04063-9_10" in rendered
    assert "2014" in rendered


def test_render_title_strips_protection_braces(refs):
    """A title with BibDesk title-case "protection" braces (e.g.
    `"{QED}"`) renders without the literal brace characters, but keeps
    the protected text itself."""
    entry = refs["GoerzNPJQI2017"]
    assert "{QED}" in entry.get("title", "")
    rendered = render_entry(entry)
    assert "circuit QED design landscape" in rendered
    assert "{" not in rendered
    assert "}" not in rendered


# -- TeX markup in stored field values ---------------------------------- #


@pytest.mark.parametrize("fmt", ["markdown", "html"])
@pytest.mark.parametrize(
    "key", ["GoerzSPP2019", "GoerzPhd2015", "SciPy", "jax"]
)
def test_render_no_raw_tex_commands(refs, key, fmt):
    """TeX markup in stored fields (`\\url`, `\\href`, `\\texttt`,
    `\\textit`) must not appear verbatim in markdown/html output."""
    rendered = render_entry(refs[key], format=fmt)
    for command in ("\\url", "\\href", "\\texttt", "\\textit"):
        assert command not in rendered


def test_render_note_tex_commands_markdown(refs):
    """`\\url` and `\\href` in a note render as markdown links, and
    `\\texttt` as a code span."""
    rendered = render_entry(refs["GoerzPhd2015"])
    assert "[https://michaelgoerz.net](https://michaelgoerz.net)" in rendered
    assert "[Github](https://github.com/goerz/dissertation)" in rendered
    rendered = render_entry(refs["GoerzSPP2019"])
    assert "The `krotov` Python package" in rendered


def test_render_note_tex_commands_html(refs):
    """`\\url` and `\\textit` in a note render as HTML markup."""
    rendered = render_entry(refs["SciPy"], format="html")
    assert '<a href="https://scipy.org">https://scipy.org</a>' in rendered
    rendered = render_entry(refs["DevoretLH1995"], format="html")
    assert "<i>Les Houches Summer School</i>" in rendered


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_render_texttt_title(refs, fmt):
    """`\\texttt{JAX}` in a title renders as monospace markup; in
    particular, the protection-brace stripping must not mangle it
    into `\\textttJAX`."""
    rendered = render_entry(refs["jax"], format=fmt)
    if fmt == "markdown":
        assert "*`JAX`: composable transformations" in rendered
    else:
        assert "<i><code>JAX</code>: composable transformations" in rendered


def test_render_tex_format_keeps_tex_markup(refs):
    """For tex output, TeX commands in stored fields pass through
    verbatim (including their braces)."""
    rendered = render_entry(refs["jax"], format="tex")
    assert "\\texttt{JAX}: composable transformations" in rendered
    rendered = render_entry(refs["GoerzPhd2015"], format="tex")
    assert "\\url{https://michaelgoerz.net}" in rendered
    assert "\\href{https://github.com/goerz/dissertation}{Github}" in rendered


@pytest.mark.parametrize(
    "key, snippets",
    [
        (
            "Shapiro2012",
            ["M. Shapiro and P. Brumer", "Wiley and Sons", "(2012)"],
        ),
        (
            "Giles2008",
            ["In: *Advances in Automatic Differentiation*", "Springer"],
        ),
        (
            "Giles2008b",
            ["Technical Report", "Oxford University Computing Laboratory"],
        ),
        ("MATLAB:2014", ["The MathWorks Inc.", "Natick, Massachusetts"]),
        ("TedRyd", ["T. Corcovilos and D. S. Weiss", "Private communication"]),
        ("WP_Schroedinger", ["Schrödinger equation", "wikipedia.org"]),
    ],
)
def test_render_more_entry_types(refs, key, snippets):
    """A book, incollection, techreport, manual, unpublished (without
    a year), and misc entry from the example database each render with
    their type-specific content."""
    rendered = render_entry(refs[key])
    for snippet in snippets:
        assert snippet in rendered
    # a missing year must not leave empty parentheses behind
    assert "()" not in rendered


def test_render_inbook_includes_publisher_and_series(refs):
    """An `inbook` entry renders its publisher (with `\\&` converted),
    series and volume (with `~` converted), chapter, and pages."""
    rendered = render_entry(refs["Nolting1997Coulomb"])
    assert "Vieweg & Teubner Verlag" in rendered
    assert "Grundkurs Theoretische Physik Vol. 5.2" in rendered
    assert "Chapter 6" in rendered
    assert "p.\N{NO-BREAK SPACE}100" in rendered


def test_render_inbook_with_booktitle(refs):
    """An `inbook` entry with a `booktitle` renders it like an
    `incollection` entry."""
    rendered = render_entry(refs["NielsenChuangCh10QEC"])
    assert "In: *Quantum Computation and Quantum Information*" in rendered
    assert "Cambridge University Press (2000)" in rendered
    assert "Chapter 10" in rendered


def test_render_incollection_includes_editors_and_pages(refs):
    """An `incollection` entry renders its editors, series/volume,
    and pages (like an `inproceedings` entry already does)."""
    rendered = render_entry(refs["Giles2008"])
    assert "edited by" in rendered
    assert "C. H. Bischof" in rendered
    assert (
        "Lecture Notes in Computational Science and Engineering Vol. 64"
        in rendered
    )
    assert "pp.\N{NO-BREAK SPACE}35–44" in rendered


def test_render_proceedings_includes_publisher_and_series(refs):
    """A `proceedings` entry renders its series and publisher like a
    `book` (previously, `proceedings` fell back to just the year)."""
    rendered = render_entry(refs["AnderssonSGS2014"])
    assert "Scottish Graduate Series" in rendered
    assert "Springer (2014)" in rendered


def test_render_entries_numbers_and_wraps(refs):
    """`render_entries` separates entries by a blank line per format."""
    entries = [refs["GoerzDiploma2010"], refs["GoerzPhd2015"]]
    md = render_entries(entries)
    paragraphs = md.split("\n\n")
    assert len(paragraphs) == 2

    tex = render_entries(entries, format="tex")
    assert tex.split("\n\n") == [
        render_entry(entries[0], format="tex"),
        render_entry(entries[1], format="tex"),
    ]

    html = render_entries(entries, format="html")
    assert html.count("<p>") == 2
    assert html.count("</p>") == 2
    assert html.split("\n\n") == [
        f"<p>{render_entry(entries[0], format='html')}</p>",
        f"<p>{render_entry(entries[1], format='html')}</p>",
    ]


# -- unit tests for building blocks ------------------------------------ #


def test_format_authors_truncates_with_et_al():
    """More than 6 authors are truncated to 3, with "et al." appended."""
    author_str = " and ".join(
        f"Last{i}, First{i}" for i in range(1, 9)
    )  # 8 authors
    entry = _make_entry("article", "k", author=author_str)
    rendered = _format_authors(entry, "markdown")
    assert rendered == "F. Last1, F. Last2, F. Last3, *et al.*"


def test_format_authors_no_truncation_at_six():
    """Exactly 6 authors are not truncated."""
    author_str = " and ".join(
        f"Last{i}, First{i}" for i in range(1, 7)
    )  # 6 authors
    entry = _make_entry("article", "k", author=author_str)
    rendered = _format_authors(entry, "markdown")
    assert "et al." not in rendered
    assert rendered.count(" and ") == 1
    assert rendered.startswith("F. Last1")
    assert rendered.endswith("F. Last6")


def test_format_authors_empty():
    """No `author` field: authors segment is empty."""
    entry = _make_entry("article", "k")
    assert _format_authors(entry, "markdown") == ""


def test_format_authors_von_name():
    """A "von"-style name is rendered as "Initials von Last"."""
    entry = _make_entry("article", "k", author="Ludwig van Beethoven")
    assert _format_authors(entry, "markdown") == "L. van Beethoven"


def test_format_authors_jr_name():
    """A "Jr"-suffixed name is rendered as "Initials Last, Jr"."""
    entry = _make_entry("article", "k", author="Smith, Jr, John")
    assert _format_authors(entry, "markdown") == "J. Smith, Jr"


def test_format_authors_hyphenated_first_name():
    """A hyphenated first name is initialed hyphen-by-hyphen."""
    entry = _make_entry("article", "k", author="Dupont, Jean-Paul")
    assert _format_authors(entry, "markdown") == "J.-P. Dupont"


def test_format_pages_single():
    """A single page number renders as "p.<nbsp>N"."""
    entry = _make_entry("article", "k", pages="154011")
    assert _format_pages(entry) == "p. 154011"


def test_format_pages_range():
    """A page range renders as "pp.<nbsp>N1<endash>N2"."""
    entry = _make_entry("article", "k", pages="45-52")
    assert _format_pages(entry) == "pp. 45–52"


def test_format_pages_range_multiple_hyphens():
    """A page range using an em/en-dash-like run of hyphens is still
    recognized."""
    entry = _make_entry("article", "k", pages="45--52")
    assert _format_pages(entry) == "pp. 45–52"


def test_format_pages_absent():
    """No `pages` field: pages segment is empty."""
    entry = _make_entry("article", "k")
    assert _format_pages(entry) == ""


def test_detex_nested_commands():
    """Commands nested in a `\\href` label are converted recursively."""
    assert _detex(r"\href{https://x.org}{\texttt{code}}", "markdown") == (
        "[`code`](https://x.org)"
    )


def test_detex_escapes_and_nonbreaking_space():
    """Escaped characters lose their backslash and `~` becomes a
    space in markdown/html output; tex output is untouched."""
    assert _detex(r"Vieweg \& Teubner", "markdown") == "Vieweg & Teubner"
    assert _detex(r"Vol.~5.2", "html") == "Vol. 5.2"
    assert _detex(r"Vieweg \& Teubner, Vol.~5.2", "tex") == (
        r"Vieweg \& Teubner, Vol.~5.2"
    )


def test_detex_unknown_command_verbatim():
    """An unrecognized command passes through verbatim, with its
    braced argument intact even under `drop_braces`."""
    text = r"in \textsc{Small Caps} and {Protected} text"
    assert _detex(text, "markdown") == text
    assert _detex(text, "markdown", drop_braces=True) == (
        r"in \textsc{Small Caps} and Protected text"
    )


def test_detex_malformed_verbatim():
    """Unbalanced braces or a missing `\\href` label pass through
    verbatim."""
    assert _detex(r"\texttt{oops", "markdown") == r"\texttt{oops"
    assert _detex(r"see \href{https://x.org} now", "markdown") == (
        r"see \href{https://x.org} now"
    )


def test_format_eprint_with_primaryclass():
    """`eprint` + `primaryclass` are both included, linked to arXiv."""
    entry = _make_entry(
        "article",
        "k",
        eprint="1234.5678",
        archiveprefix="arXiv",
        primaryclass=ValueString("quant-ph"),
    )
    assert _format_eprint(entry, "markdown") == (
        "[arXiv:1234.5678 [quant-ph]]" "(https://arxiv.org/abs/1234.5678)"
    )


def test_format_eprint_without_primaryclass():
    """`eprint` without `primaryclass`: no bracketed class suffix."""
    entry = _make_entry("article", "k", eprint="1234.5678")
    assert _format_eprint(entry, "markdown") == (
        "[arXiv:1234.5678](https://arxiv.org/abs/1234.5678)"
    )


def test_format_eprint_absent():
    """No `eprint` field: eprint segment is empty."""
    entry = _make_entry("article", "k")
    assert _format_eprint(entry, "markdown") == ""


def test_format_eprint_hal():
    """A HAL `archiveprefix` names and links the HAL archive, with the
    prefix canonicalized (`hal` -> `HAL`)."""
    entry = _make_entry(
        "article", "k", eprint="hal-03612955", archiveprefix="hal"
    )
    assert _format_eprint(entry, "markdown") == (
        "[HAL:hal-03612955](https://hal.science/hal-03612955)"
    )


def test_format_eprint_unknown_archive():
    """An unrecognized `archiveprefix` renders verbatim, unlinked."""
    entry = _make_entry(
        "article", "k", eprint="X5129", archiveprefix="EarthArXiv"
    )
    assert _format_eprint(entry, "markdown") == "EarthArXiv:X5129"


def test_format_eprint_no_url_template():
    """An archive without identifier-based URLs (ChemRxiv) names the
    archive but produces no link."""
    entry = _make_entry(
        "article",
        "k",
        eprint="10.26434/chemrxiv-2021-h5g1x",
        archiveprefix="chemrxiv",
    )
    assert _format_eprint(entry, "markdown") == (
        "ChemRxiv:10.26434/chemrxiv-2021-h5g1x"
    )


def test_format_eprint_omitted_for_preprint_only():
    """A preprint-only entry (either stored form) omits the separate
    eprint segment: the preprint reference renders in the journal
    position instead."""
    entry = _make_entry(
        "article",
        "k",
        journal="arXiv:1234.5678",
        eprint="1234.5678",
        archiveprefix="arXiv",
    )
    assert _format_eprint(entry, "markdown") == ""
    entry = _make_entry("misc", "k", eprint="1234.5678", archiveprefix="arXiv")
    assert _format_eprint(entry, "markdown") == ""


def test_format_eprint_kept_for_published():
    """A published article with an eprint keeps the eprint segment
    (the "published, with preprint" form)."""
    entry = _make_entry(
        "article",
        "k",
        journal="Phys. Rev. A",
        volume="99",
        eprint="1234.5678",
        archiveprefix="arXiv",
    )
    assert _format_eprint(entry, "markdown") == (
        "[arXiv:1234.5678](https://arxiv.org/abs/1234.5678)"
    )


def test_format_eprint_kept_for_thesis():
    """A thesis deposited on a preprint server is not preprint-only
    (only `misc` counts): its eprint renders as a separate segment."""
    entry = _make_entry(
        "phdthesis",
        "k",
        eprint="tel-00007910v2",
        archiveprefix="hal",
    )
    assert _format_eprint(entry, "markdown") == (
        "[HAL:tel-00007910v2](https://hal.science/tel-00007910v2)"
    )


# -- preprint-only entries ---------------------------------------------- #


def test_render_preprint_only_arxiv(refs):
    """A preprint-only arXiv entry (stored as `@unpublished`): the
    preprint reference renders in the journal position, with the
    category tag from `primaryclass`, linked to the DOI, with the
    status note appended; no separate eprint link."""
    entry = refs["Wilhelm2003.10132"]
    assert entry.entry_type == "unpublished"
    rendered = render_entry(entry)
    assert rendered == (
        "F. K. Wilhelm, S. Kirchhoff, S. Machnes, N. Wittler and "
        "D. Sugny. [*An introduction into optimal control for quantum "
        "technologies*](https://arxiv.org/abs/2003.10132), "
        "[arXiv:2003.10132 [quant-ph]]"
        "(https://doi.org/10.48550/arxiv.2003.10132) (2020), "
        "preprint only."
    )


def test_render_preprint_only_legacy_article():
    """A preprint-only entry in the legacy `@article` form renders
    identically to the `@misc` form."""
    fields = {
        "author": "Doe, Jane",
        "title": "A Title",
        "journal": "arXiv:1234.5678",
        "eprint": "1234.5678",
        "archiveprefix": "arXiv",
        "doi": "10.48550/arxiv.1234.5678",
        "year": "2024",
    }
    as_article = Entry("article", "k", fields=dict(fields))
    as_misc = Entry("misc", "k", fields=dict(fields))
    assert render_entry(as_article) == render_entry(as_misc)


def test_render_preprint_only_misc_without_journal():
    """A `@misc` entry with only the eprint fields (e.g. imported
    from arXiv's own BibTeX export) renders its preprint reference in
    the journal position."""
    entry = _make_entry(
        "misc",
        "k",
        author="Doe, Jane",
        title="A Title",
        eprint="1234.5678",
        archiveprefix="arXiv",
        year="2024",
    )
    assert render_entry(entry) == (
        "J. Doe. *A Title*, "
        "[arXiv:1234.5678](https://arxiv.org/abs/1234.5678) (2024)."
    )


def test_render_preprint_only_hal_url_fallback(refs):
    """A preprint-only HAL entry without a DOI: the pseudo-journal
    links to the entry's first URL, and the status note appends."""
    rendered = render_entry(refs["TuriniciHAL00640217"])
    assert rendered == (
        "G. Turinici. [*Quantum control*]"
        "(https://hal.science/hal-00640217). "
        "[HAL:hal-00640217](https://hal.science/hal-00640217) (2012), "
        "lecture notes."
    )


def test_render_preprint_only_archive_url_fallback():
    """A preprint-only entry without DOI or URL: the preprint
    reference links to the archive's page for the identifier."""
    entry = _make_entry(
        "misc",
        "k",
        author="Doe, Jane",
        title="A Title",
        journal="arXiv:1234.5678",
        eprint="1234.5678",
        archiveprefix="arXiv",
        year="2024",
    )
    assert render_entry(entry) == (
        "J. Doe. *A Title*, "
        "[arXiv:1234.5678](https://arxiv.org/abs/1234.5678) (2024)."
    )


def test_render_preprint_only_biorxiv(refs):
    """A preprint-only bioRxiv entry, linked via its DOI."""
    rendered = render_entry(refs["Vecheck2022.09.09.507322"])
    assert "bioRxiv:2022.09.09.507322" in rendered
    assert "https://doi.org/10.1101/2022.09.09.507322" in rendered
    assert rendered.count("2022.09.09.507322") == 2  # journal + link only


def test_render_published_with_hal_eprint(refs):
    """A published article with a HAL eprint: journal from the macro,
    plus a correctly linked `HAL:...` eprint segment."""
    entry = refs["SauvagePRXQ2020"]
    rendered = render_entry(entry)
    assert "HAL:hal-03612955" in rendered
    assert "https://hal.science/hal-03612955" in rendered
    assert "arXiv" not in rendered


def test_render_published_with_biorxiv_eprint(refs):
    """A published article with a bioRxiv eprint: the eprint segment
    names bioRxiv (canonicalized from `archiveprefix = {biorxiv}`)
    and links to biorxiv.org, not arxiv.org."""
    entry = refs["KatrukhaNC2017"]
    assert entry["archiveprefix"].lower() == "biorxiv"
    rendered = render_entry(entry)
    assert "bioRxiv:089284" in rendered
    assert "https://www.biorxiv.org/content/10.1101/089284" in rendered
    assert "arXiv" not in rendered


# -- _join_parts punctuation rules -------------------------------------- #


def test_join_parts_uppercase_next_uses_period():
    """An uppercase-starting next part is joined with ". "."""
    assert _join_parts(["Foo", "Bar"]) == "Foo. Bar."


def test_join_parts_lowercase_next_uses_comma():
    """A lowercase-starting next part is joined with ", "."""
    assert _join_parts(["Foo", "bar"]) == "Foo, bar."


def test_join_parts_parenthesis_next_uses_space():
    """A next part starting with "(" is joined with a bare space."""
    assert _join_parts(["Foo", "(bar)"]) == "Foo (bar)."


def test_join_parts_terminal_punctuation_already_present():
    """If the current part already ends in terminal punctuation, a
    bare space is used regardless of the next part's case."""
    assert _join_parts(["Foo:", "Bar"]) == "Foo: Bar."
    assert _join_parts(["Foo:", "bar"]) == "Foo: bar."
    assert _join_parts(["Foo.", "Bar"]) == "Foo. Bar."


def test_join_parts_no_double_trailing_period():
    """No extra trailing period if the result already ends in one of
    `.:!?`."""
    assert _join_parts(["Foo."]) == "Foo."
    assert _join_parts(["Foo!"]) == "Foo!"
    assert _join_parts(["Foo?"]) == "Foo?"
    assert _join_parts(["Foo:"]) == "Foo:"


def test_join_parts_drops_falsy():
    """Falsy parts are dropped before joining."""
    assert _join_parts(["Foo", "", None, "Bar"]) == "Foo. Bar."


def test_join_parts_empty():
    """No parts at all: empty string, no trailing period added."""
    assert _join_parts([]) == ""
    assert _join_parts(["", None]) == ""


def test_join_parts_ignores_markup_for_case_check():
    """The "starts with uppercase" check looks past our own Markdown/
    HTML markup wrappers to the first visible letter."""
    assert _join_parts(["Foo", "*Bar*"]) == "Foo. *Bar*."
    assert _join_parts(["Foo", "*bar*"]) == "Foo, *bar*."
    assert _join_parts(["Foo", "<i>Bar</i>"]) == "Foo. <i>Bar</i>."
    assert _join_parts(["Foo", "[Bar](url)"]) == "Foo. [Bar](url)."


# -- format-aware primitives -------------------------------------------- #


@pytest.mark.parametrize(
    "fmt, expected",
    [
        ("markdown", "[text](http://example.org)"),
        ("tex", "\\href{http://example.org}{text}"),
        ("html", '<a href="http://example.org">text</a>'),
    ],
)
def test_link(fmt, expected):
    """`_link` formats a hyperlink per format."""
    assert _link("text", "http://example.org", fmt) == expected


@pytest.mark.parametrize("fmt", ["markdown", "tex", "html"])
def test_link_no_url(fmt):
    """`_link` with an empty/`None` url returns the text unlinked."""
    assert _link("text", "", fmt) == "text"
    assert _link("text", None, fmt) == "text"


@pytest.mark.parametrize(
    "fmt, expected",
    [
        ("markdown", "*text*"),
        ("tex", "\\textit{text}"),
        ("html", "<i>text</i>"),
    ],
)
def test_italic(fmt, expected):
    """`_italic` formats text per format."""
    assert _italic("text", fmt) == expected


@pytest.mark.parametrize(
    "fmt, expected",
    [
        ("markdown", "**text**"),
        ("tex", "\\textbf{text}"),
        ("html", "<b>text</b>"),
    ],
)
def test_bold(fmt, expected):
    """`_bold` formats text per format."""
    assert _bold("text", fmt) == expected


@pytest.mark.parametrize(
    "fmt, expected",
    [
        ("markdown", "`text`"),
        ("tex", "\\texttt{text}"),
        ("html", "<code>text</code>"),
    ],
)
def test_mono(fmt, expected):
    """`_mono` formats text per format."""
    assert _mono("text", fmt) == expected


# -- format validation --------------------------------------------------- #


def test_render_entry_invalid_format():
    """`render_entry` raises `ValueError` for an unknown format."""
    entry = _make_entry("article", "k", title="T")
    with pytest.raises(ValueError, match="format must be one of"):
        render_entry(entry, format="bogus")


def test_render_entries_invalid_format():
    """`render_entries` raises `ValueError` for an unknown format."""
    entry = _make_entry("article", "k", title="T")
    with pytest.raises(ValueError, match="format must be one of"):
        render_entries([entry], format="bogus")


def test_render_entries_invalid_style():
    """`render_entries` raises `ValueError` for an unknown style."""
    entry = _make_entry("article", "k", title="T")
    with pytest.raises(ValueError, match="style must be one of"):
        render_entries([entry], style="bogus")


def test_render_preprint_only_unpublished():
    """An `@unpublished` entry with an eprint is preprint-only: the
    preprint reference renders in the journal position, and a status
    note appends."""
    entry = _make_entry(
        "unpublished",
        "k",
        author="Doe, Jane",
        title="A Title",
        eprint="1234.5678",
        archiveprefix="arXiv",
        note="submitted to Phys. Rev. A",
        doi="10.48550/arxiv.1234.5678",
        year="2024",
    )
    assert render_entry(entry) == (
        "J. Doe. *A Title*, "
        "[arXiv:1234.5678](https://doi.org/10.48550/arxiv.1234.5678) "
        "(2024), submitted to Phys. Rev. A."
    )
