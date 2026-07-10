"""Tests for `bibdeskparser.render`."""

from pathlib import Path

import bibtexparser
import pytest

from bibdeskparser.entry import Entry, ValueString
from bibdeskparser.middleware import parse_stack
from bibdeskparser.render import (
    _bold,
    _format_authors,
    _format_eprint,
    _format_pages,
    _italic,
    _join_parts,
    _link,
    render_entries,
    render_entry,
)

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"


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
    entry = refs["GoerzPhd2015"]
    assert entry.urls == ()
    assert entry.get("doi") is None
    rendered = render_entry(entry, format=fmt)
    assert "M. Goerz" in rendered
    assert "Ph.D. thesis" in rendered
    assert "Universit" in rendered
    assert "2015" in rendered


@pytest.mark.parametrize("fmt", ["markdown", "tex", "html"])
def test_render_inproceedings(refs, fmt):
    """An `inproceedings` entry: booktitle italicized, DOI links the
    title (no `bdsk-url-N` field present)."""
    entry = refs["GoerzSPIEO2021"]
    assert entry.urls == ()
    rendered = render_entry(entry, format=fmt)
    assert "Goerz" in rendered
    assert "Kasevich" in rendered
    assert "Malinovsky" in rendered
    assert "In:" in rendered
    assert "Proc. SPIE" in rendered
    assert "https://doi.org/10.1117/12.2587002" in rendered
    assert "2021" in rendered


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
