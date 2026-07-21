r"""Render citations in an APS-journal-like numeric style.

A citation is assembled from *authors*, *title*, *published-in*,
*eprint*, and *note* segments, each rendered independently and then
joined with sentence-like punctuation.

Three output formats are supported (the `format` argument of
{func}`render_entry`/{func}`render_entries`): `"markdown"` (the default),
`"tex"`, and `"html"`. When rendering several citations at once,
{func}`render_entries` also takes a `style` argument controlling their
layout (paragraphs, a numbered list, or an itemized list).

The *published-in* segment has dedicated formatting for the
following `Entry.entry_type` values:

- `article`: `journal **volume**, pages (year)`, linked to the DOI (if
  any); the title links to the entry's first URL instead (never the
  DOI).
- `inproceedings`: `In: *booktitle*, edited by ... (address, month
  year), pages`.
- `mastersthesis`/`phdthesis`: `label, school (year)`, where `label` is
  `"Master's thesis"`/`"Ph.D. thesis"` unless overridden by a `type`
  field.
- `book`/`incollection`: `publisher, address (year)`, prefixed by `In:
  *booktitle*, ` for `incollection`.
- `techreport`: `Technical Report, institution (year)`.

Any other entry type (e.g. `misc`, `unpublished`) falls back to a
minimal `(year)` (or `""` if there is no year); such types are expected
to carry their full citation information in the `note` field instead.

A *preprint-only* entry -- a `misc` (or `unpublished`) entry with
an `eprint` from a recognized preprint archive, or any entry whose
`journal` is a recognized preprint pseudo-journal like
`arXiv:2401.00001` -- renders
its preprint reference (with the category tag from `primaryclass`,
e.g. `arXiv:2401.00001 [quant-ph]`) in the published-in position,
linked to the DOI, the entry's first URL, or the archive's own page
for the identifier, in that order of preference. For any *other*
entry, the *eprint* segment links the `eprint` field into its
preprint archive (named by the `archiveprefix` field, defaulting to
arXiv), e.g. `arXiv:2401.00001 [quant-ph]` -- the "published, with
preprint" rendering.

```python
>>> from bibdeskparser.entry import Entry
>>> from bibdeskparser.render import render_entry
>>> article = Entry(
...     "article",
...     "Doe2024",
...     fields={
...         "author": "Doe, Jane and Roe, Richard",
...         "title": "A Great Discovery",
...         "journal": "Phys. Rev. A",
...         "volume": "99",
...         "year": "2024",
...     },
... )
>>> render_entry(article, format="html")
'J. Doe and R. Roe. <i>A Great Discovery</i>. Phys. Rev. A <b>99</b> (2024).'

```
"""

import re

from .config import active
from .identifiers import _archive_url, _entry_preprint

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["render_entry", "render_entries"]

#: Output formats understood by {func}`render_entry`/{func}`render_entries`.
_VALID_FORMATS = ("markdown", "tex", "html")

#: Layout styles understood by {func}`render_entries` (its `style`
#: argument).
_VALID_STYLES = ("default", "paragraphs", "numbered list", "itemized list")

_MONTH_ABBR = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

_MONTH_FULL = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

_BRACES_RE = re.compile(r"[{}]")

_PAGE_RANGE_RE = re.compile(r"(\d+)-+(\d+)")

#: Markup our own `_link`/`_italic`/`_bold` primitives may produce at
#: the *start* of a rendered segment, longest-first so that, e.g.,
#: `"**"` (bold) is stripped before `"*"` (italic).
_LEADING_MARKUP_RE = re.compile(
    r"^(\*\*|\*|\[|\\textbf\{|\\textit\{|\\href\{[^}]*\}\{"
    r'|<b>|<i>|<a href="[^"]*">)'
)

#: Markup our own primitives may produce at the *end* of a rendered
#: segment.
_TRAILING_MARKUP_RE = re.compile(r"(\*\*|\*|\}|</b>|</i>|</a>|\]\([^)]*\))$")


def _strip_braces(text):
    """Remove (but not the contents of) any `{...}` from `text`.

    Used for `title`/`type`/`booktitle` fields, which may carry BibDesk
    title-casing "protection" braces (LaTeX-only, invisible to a
    reader).
    """
    return _BRACES_RE.sub("", text)


def _link(text, url, fmt):
    """Format `text` as a hyperlink to `url` in format `fmt`.

    Returns `text` unchanged if `url` is falsy. Does not validate
    `fmt` (see the module docstring: validation happens in the public
    entry points).
    """
    if not url:
        return text
    if fmt == "markdown":
        return f"[{text}]({url})"
    if fmt == "tex":
        return f"\\href{{{url}}}{{{text}}}"
    return f'<a href="{url}">{text}</a>'


def _italic(text, fmt):
    """Format `text` in italics in format `fmt`."""
    if fmt == "markdown":
        return f"*{text}*"
    if fmt == "tex":
        return f"\\textit{{{text}}}"
    return f"<i>{text}</i>"


def _bold(text, fmt):
    """Format `text` in bold in format `fmt`."""
    if fmt == "markdown":
        return f"**{text}**"
    if fmt == "tex":
        return f"\\textbf{{{text}}}"
    return f"<b>{text}</b>"


def _strip_leading_markup(text):
    """Strip markup produced by `_link`/`_italic`/`_bold` from the
    start of `text`, repeatedly (e.g. a bold+linked segment has both a
    link and a bold wrapper at its start)."""
    while True:
        stripped = _LEADING_MARKUP_RE.sub("", text, count=1)
        if stripped == text:
            return text
        text = stripped


def _strip_trailing_markup(text):
    """Like `_strip_leading_markup`, but from the end of `text`."""
    while True:
        stripped = _TRAILING_MARKUP_RE.sub("", text, count=1)
        if stripped == text:
            return text
        text = stripped


def _visible_edges(text):
    """Return `text` with markup stripped from both ends.

    Used only to inspect the first/last *visible* character of an
    already-formatted segment (e.g. to decide whether a segment
    "starts with an uppercase letter" although it may actually start
    with a Markdown `"*"` or an HTML `"<i>"`), never returned to a
    caller of {func}`render_entry`.
    """
    return _strip_trailing_markup(_strip_leading_markup(text))


def _join_parts(parts):
    r"""Join formatted citation segments with sentence-like punctuation.

    ```python
    _join_parts(parts)
    ```

    `parts` is an iterable of already-formatted strings (some of which
    may be empty/falsy, and are dropped). Consecutive parts are joined
    by inspecting the *visible* text at the boundary (ignoring any
    Markdown/TeX/HTML markup our own formatting primitives may have
    added):

    - if the next part starts with `"("`, or the current part already
      ends in one of `` :,;.!? ``, join with a single space;
    - otherwise, join with `". "` if the next part starts with an
      uppercase letter, else with `", "`.

    Finally, a trailing `"."` is appended unless the result already
    ends in one of `` .:!? ``.

    ```python
    >>> _join_parts(["Foo", "Bar"])
    'Foo. Bar.'
    >>> _join_parts(["Foo", "bar"])
    'Foo, bar.'
    >>> _join_parts(["Foo:", "bar"])
    'Foo: bar.'
    >>> _join_parts(["Foo", "(bar)"])
    'Foo (bar).'
    >>> _join_parts(["Foo.", ""])
    'Foo.'
    >>> _join_parts([])
    ''

    ```
    """
    parts = [part for part in parts if part]
    if not parts:
        return ""
    result = parts[0]
    for part in parts[1:]:
        current_visible = _visible_edges(result)
        next_visible = _visible_edges(part)
        if part.startswith("(") or (
            current_visible and current_visible[-1] in ":,;.!?"
        ):
            sep = " "
        elif next_visible and next_visible[0].isupper():
            sep = ". "
        else:
            sep = ", "
        result += sep + part
    visible_result = _visible_edges(result)
    if not visible_result or visible_result[-1] not in ".:!?":
        result += "."
    return result


def _initial(name_part):
    """Return the initial(s) of a single first/middle-name part.

    Hyphenated parts are initialed hyphen-by-hyphen, e.g.
    `"Jean-Paul"` -> `"J.-P."`.
    """
    if not name_part:
        return ""
    subparts = [p for p in name_part.split("-") if p]
    return "-".join(f"{p[0]}." for p in subparts)


def _format_name(name):
    """Format a single `NameParts` as `"Initials von Last, Jr"`."""
    first_initials = " ".join(_initial(part) for part in name.first if part)
    von = " ".join(part.lower() for part in name.von if part)
    last = " ".join(part for part in name.last if part)
    core = " ".join(part for part in (first_initials, von, last) if part)
    jr = " ".join(part for part in name.jr if part)
    if jr:
        core = f"{core}, {jr}" if core else jr
    return core


def _join_names(names, et_al_limit=None, et_al_text=None):
    """Join a list of `NameParts` into a single string.

    Uses `", "` between all but the last two names, and `" and "`
    before the final name. If `et_al_limit` is given and there are
    more than `et_al_limit` names, only the first 3 are kept and
    `et_al_text` (e.g. `"*et al.*"`) is appended.
    """
    formatted = [_format_name(name) for name in names]
    if not formatted:
        return ""
    if et_al_limit is not None and len(formatted) > et_al_limit:
        joined = ", ".join(formatted[:3])
        return f"{joined}, {et_al_text}" if et_al_text else joined
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + " and " + formatted[-1]


def _format_authors(entry, fmt):
    """Format `entry.author` (truncated to "et al." beyond 6 names)."""
    names = entry.author
    if not names:
        return ""
    et_al_text = _italic("et al.", fmt)
    return _join_names(names, et_al_limit=6, et_al_text=et_al_text)


def _format_editors(entry):
    """Format `entry.editor` (no "et al." truncation)."""
    return _join_names(entry.editor)


def _format_title(entry, fmt):
    """Format the `title` field, italicized and linked.

    Linked to `entry.urls[0]` if present; for non-`article` entries,
    falls back to a `doi`-based link if there is no URL. `article`
    and preprint-only entries never fall back to the DOI here, since
    `_format_published_in` links the DOI to the journal info/preprint
    reference instead.
    """
    title = entry.get("title", "").strip()
    if not title:
        return ""
    title = _italic(_strip_braces(title), fmt)

    url = None
    if entry.urls:
        url = entry.urls[0]
    elif entry.entry_type.lower() != "article" and (
        _entry_preprint(entry, active.preprint_archives) is None
    ):
        doi = entry.get("doi", "").strip()
        if doi:
            url = f"https://doi.org/{doi}"
    return _link(title, url, fmt)


def _format_pages(entry):
    """Format the `pages` field as `"p. N"` or `"pp. N1–N2"`."""
    pages = entry.get("pages", "").strip()
    if not pages:
        return ""
    match = _PAGE_RANGE_RE.match(pages)
    if match:
        return f"pp. {match.group(1)}–{match.group(2)}"
    return f"p. {pages}"


def _format_month(entry):
    """Format the `month` field as a 3-letter abbreviation, e.g. `"Jan"`.

    Understands an integer 1-12 or a full/abbreviated month name
    (case-insensitively). Returns `""` if `month` is absent or not
    recognized.
    """
    month = entry.get("month", "").strip()
    if not month:
        return ""
    if month.isdigit():
        index = int(month)
        if 1 <= index <= 12:
            return _MONTH_ABBR[index - 1]
        return ""
    lower = month.lower()
    for abbr, full in zip(_MONTH_ABBR, _MONTH_FULL):
        if lower in (abbr.lower(), full.lower()):
            return abbr
    return ""


def _format_published_in_preprint(entry, fmt, preprint):
    """Published-in for a preprint-only entry (either stored form):
    the preprint reference `Archive:identifier` in the journal
    position -- with the category tag from `primaryclass`
    (`[quant-ph]`), like a rendered eprint -- linked to the DOI, the
    entry's first URL, or the archive's own page for the identifier
    -- in that order of preference -- with the year in parens."""
    archive, identifier = preprint
    year = entry.get("year", "").strip()
    doi = entry.get("doi", "").strip()
    if doi:
        url = f"https://doi.org/{doi}"
    elif entry.urls:
        url = entry.urls[0]
    else:
        url = _archive_url(archive, identifier)
    text = f"{archive.name}:{identifier}"
    primaryclass = entry.get("primaryclass", "").strip()
    if primaryclass:
        text = f"{text} [{primaryclass}]"
    segment = _link(text, url, fmt)
    pieces = [
        piece for piece in (segment, f"({year})" if year else "") if piece
    ]
    return " ".join(pieces)


def _format_published_in_article(entry, fmt):
    """Published-in for `article`: journal/volume/pages, linked to
    DOI, with the year in parens."""
    journal = entry.get("journal", "").strip()
    volume = entry.get("volume", "").strip()
    pages = _format_pages(entry)
    year = entry.get("year", "").strip()
    doi = entry.get("doi", "").strip()

    segment = journal
    if volume:
        bold_volume = _bold(volume, fmt)
        segment = f"{segment} {bold_volume}" if segment else bold_volume
    if pages:
        segment = f"{segment}, {pages}" if segment else pages
    if doi and segment:
        segment = _link(segment, f"https://doi.org/{doi}", fmt)

    pieces = [
        piece for piece in (segment, f"({year})" if year else "") if piece
    ]
    return " ".join(pieces)


def _format_published_in_inproceedings(entry, fmt):
    """Published-in for `inproceedings`: booktitle/editors, then
    organization/address/month/year in parens, then pages."""
    booktitle = _strip_braces(entry.get("booktitle", "").strip())
    editors = entry.editor
    organization = entry.get("organization", "").strip()
    address = entry.get("address", "").strip()
    year = entry.get("year", "").strip()
    month = _format_month(entry)
    pages = _format_pages(entry)

    head = f"In: {_italic(booktitle, fmt)}" if booktitle else ""
    if editors:
        editor_names = _format_editors(entry)
        head = (
            f"{head}, edited by {editor_names}"
            if head
            else f"edited by {editor_names}"
        )

    paren_bits = [bit for bit in (organization, address) if bit]
    if year:
        paren_bits.append(f"{month} {year}".strip())
    paren = f"({', '.join(paren_bits)})" if paren_bits else ""

    result = " ".join(piece for piece in (head, paren) if piece)
    if pages:
        result = f"{result}, {pages}" if result else pages
    return result


def _format_published_in_thesis(entry):
    """Published-in for `mastersthesis`/`phdthesis`: label, school,
    year. `label` defaults to "Master's thesis"/"Ph.D. thesis" but is
    overridden by a `type` field, if present."""
    default_label = (
        "Master's thesis"
        if entry.entry_type.lower() == "mastersthesis"
        else "Ph.D. thesis"
    )
    type_field = entry.get("type", "").strip()
    label = _strip_braces(type_field) if type_field else default_label
    school = entry.get("school", "").strip()
    year = entry.get("year", "").strip()

    result = ", ".join(bit for bit in (label, school) if bit)
    if year:
        result = f"{result} ({year})" if result else f"({year})"
    return result


def _format_published_in_book(entry, fmt):
    """Published-in for `book`/`incollection`: publisher, address,
    year; `incollection` is prefixed by the booktitle."""
    prefix = ""
    if entry.entry_type.lower() == "incollection":
        booktitle = _strip_braces(entry.get("booktitle", "").strip())
        if booktitle:
            prefix = f"In: {_italic(booktitle, fmt)}"

    publisher = entry.get("publisher", "").strip()
    address = entry.get("address", "").strip()
    year = entry.get("year", "").strip()

    pub_addr = ", ".join(bit for bit in (publisher, address) if bit)
    tail = f"({year})" if year else ""
    if pub_addr and tail:
        rest = f"{pub_addr} {tail}"
    else:
        rest = pub_addr or tail

    if prefix:
        return f"{prefix}, {rest}" if rest else prefix
    return rest


def _format_published_in_techreport(entry):
    """Published-in for `techreport`: "Technical Report, institution
    (year)"."""
    institution = entry.get("institution", "").strip()
    year = entry.get("year", "").strip()

    bits = ["Technical Report"]
    if institution:
        bits.append(institution)
    result = ", ".join(bits)
    if year:
        result = f"{result} ({year})"
    return result


def _format_published_in_fallback(entry):
    """Published-in for any other entry type: just `"(year)"`, or
    `""` if there is no year."""
    year = entry.get("year", "").strip()
    return f"({year})" if year else ""


def _format_published_in(entry, fmt):
    """Format the "published-in" segment: the preprint reference for
    a preprint-only entry, else dispatching on `entry.entry_type`
    (see the module docstring for which types have dedicated
    formatting)."""
    preprint = _entry_preprint(entry, active.preprint_archives)
    if preprint is not None:
        return _format_published_in_preprint(entry, fmt, preprint)
    etype = entry.entry_type.lower()
    if etype == "article":
        return _format_published_in_article(entry, fmt)
    if etype == "inproceedings":
        return _format_published_in_inproceedings(entry, fmt)
    if etype in ("mastersthesis", "phdthesis"):
        return _format_published_in_thesis(entry)
    if etype in ("book", "incollection"):
        return _format_published_in_book(entry, fmt)
    if etype == "techreport":
        return _format_published_in_techreport(entry)
    return _format_published_in_fallback(entry)


def _format_eprint(entry, fmt):
    """Format the `eprint` field as a link into its preprint archive,
    e.g. `"arXiv:2401.00001 [quant-ph]"`.

    The archive is named by the `archiveprefix` field (arXiv if
    absent); a recognized archive (see the `preprint_archives`
    [configuration](configuration)) supplies the canonical prefix
    spelling and the link target, an unrecognized one renders
    verbatim, without a link. Returns `""` for a preprint-only
    entry: there, the published-in segment already shows the
    preprint reference."""
    eprint = entry.get("eprint", "").strip()
    if not eprint:
        return ""
    if _entry_preprint(entry, active.preprint_archives) is not None:
        return ""
    prefix = entry.get("archiveprefix", "").strip() or "arXiv"
    archive = active.preprint_archives.get(prefix.lower())
    if archive is None:
        name, url = prefix, None
    else:
        name, url = archive.name, _archive_url(archive, eprint)
    text = f"{name}:{eprint}"
    primaryclass = entry.get("primaryclass", "").strip()
    if primaryclass:
        text = f"{text} [{primaryclass}]"
    return _link(text, url, fmt)


def _format_note(entry):
    """Format the `note` field verbatim (stripped)."""
    return entry.get("note", "").strip()


def render_entry(entry, format="markdown"):  # noqa: A002 (shadows builtin)
    # pylint: disable=redefined-builtin
    r"""Render a single citation for `entry`.

    ```python
    render_entry(entry, format="markdown")
    ```

    Assembles the citation from *authors*, *title*, *published-in*,
    *eprint*, and *note* segments (see the module docstring), joined
    with sentence-like punctuation.

    * `entry`: a {class}`bibdeskparser.entry.Entry`.
    * `format`: one of `"markdown"` (default), `"tex"`, `"html"`.

    Raises {exc}`ValueError` if `format` is not one of the above.

    ```python
    >>> from bibdeskparser.entry import Entry
    >>> entry = Entry(
    ...     "article",
    ...     "Doe2024",
    ...     fields={
    ...         "author": "Doe, J and Roe, R",
    ...         "title": "Title",
    ...         "journal": "PRA",
    ...         "volume": "1",
    ...         "year": "2024",
    ...         "doi": "10.1/x",
    ...     },
    ... )
    >>> render_entry(entry)
    'J. Doe and R. Roe. *Title*. [PRA **1**](https://doi.org/10.1/x) (2024).'
    >>> render_entry(entry, format="bogus")
    Traceback (most recent call last):
        ...
    ValueError: format must be one of ('markdown', 'tex', 'html'), not 'bogus'

    ```
    """
    if format not in _VALID_FORMATS:
        raise ValueError(
            f"format must be one of {_VALID_FORMATS}, not {format!r}"
        )
    parts = [
        _format_authors(entry, format),
        _format_title(entry, format),
        _format_published_in(entry, format),
        _format_eprint(entry, format),
        _format_note(entry),
    ]
    return _join_parts(parts)


def render_entries(entries, format="markdown", style="default"):  # noqa: A002
    # pylint: disable=redefined-builtin
    r"""Render a bibliography for `entries`.

    ```python
    render_entries(entries, format="markdown", style="default")
    ```

    * `entries`: an iterable of {class}`bibdeskparser.entry.Entry`,
      rendered in the given order.
    * `format`: one of `"markdown"` (default), `"tex"`, `"html"`.
    * `style`: the layout of the citations relative to one another; one
      of:
      * `"paragraphs"`: each citation is a paragraph, separated from the
        next by a blank line (for `"html"`, each citation is wrapped in
        a `<p>...</p>` instead, since blank lines are not significant in
        HTML).
      * `"numbered list"`: a numbered list (`"markdown"`: `1.`, `2.`,
        ...; `"tex"`: an `enumerate` environment; `"html"`: an `<ol>`).
      * `"itemized list"`: a bulleted list (`"markdown"`: `-`; `"tex"`:
        an `itemize` environment; `"html"`: a `<ul>`).
      * `"default"` (the default): like `"paragraphs"`, except that a
        single `"html"` citation is *not* wrapped in a `<p>...</p>`.

    Each citation is rendered with {func}`render_entry`.

    Raises {exc}`ValueError` if `format` or `style` is not one of the
    above.

    ```python
    >>> from bibdeskparser.entry import Entry
    >>> entry1 = Entry(
    ...     "article",
    ...     "Doe2024",
    ...     fields={
    ...         "author": "Doe, Jane",
    ...         "title": "A Great Discovery",
    ...         "journal": "Phys. Rev. A",
    ...         "volume": "99",
    ...         "year": "2024",
    ...     },
    ... )
    >>> entry2 = Entry(
    ...     "mastersthesis",
    ...     "Smith2020",
    ...     fields={
    ...         "author": "Smith, John",
    ...         "title": "A Thesis",
    ...         "school": "Test University",
    ...         "year": "2020",
    ...     },
    ... )
    >>> print(render_entries([entry1, entry2]))
    J. Doe. *A Great Discovery*. Phys. Rev. A **99** (2024).
    <BLANKLINE>
    J. Smith. *A Thesis*. Master's thesis, Test University (2020).
    >>> print(render_entries([entry1, entry2], style="numbered list"))
    1. J. Doe. *A Great Discovery*. Phys. Rev. A **99** (2024).
    2. J. Smith. *A Thesis*. Master's thesis, Test University (2020).

    ```
    """
    if format not in _VALID_FORMATS:
        raise ValueError(
            f"format must be one of {_VALID_FORMATS}, not {format!r}"
        )
    if style not in _VALID_STYLES:
        raise ValueError(
            f"style must be one of {_VALID_STYLES}, not {style!r}"
        )
    rendered = [render_entry(entry, format) for entry in entries]
    if style in ("default", "paragraphs"):
        if format == "html":
            if style == "default" and len(rendered) == 1:
                return rendered[0]
            return "\n\n".join(f"<p>{item}</p>" for item in rendered)
        return "\n\n".join(rendered)
    # numbered/itemized list styles
    if format == "markdown":
        if style == "numbered list":
            return "\n".join(
                f"{i}. {item}" for i, item in enumerate(rendered, start=1)
            )
        return "\n".join(f"- {item}" for item in rendered)
    env = "enumerate" if style == "numbered list" else "itemize"
    if format == "tex":
        items = "\n".join(f"\\item {item}" for item in rendered)
        return f"\\begin{{{env}}}\n{items}\n\\end{{{env}}}"
    tag = "ol" if style == "numbered list" else "ul"
    items = "\n".join(f"<li>{item}</li>" for item in rendered)
    return f"<{tag}>\n{items}\n</{tag}>"
