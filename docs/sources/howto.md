# How-to Guides

These short, task-oriented recipes assume you are already familiar with the
basics of `bibdeskparser` (see the [introduction](readme)); for background on
*why* things work this way, see [BibDesk's `.bib` Format](bibdesk_format).

## How to manage file attachments

```{tip}
Rather than naming and placing every attachment by hand, you can have
`bibdeskparser` *auto-file* them -- moving each file into a configured
location and renaming it by a file-name format (BibDesk's AutoFile
feature). See [How to auto-file attachments](howto-auto-file) below.
```

Linked files are stored with paths relative to the library's `.bib`
file, so attaching, replacing, unlinking, and renaming them are
`Library` operations ({py:attr}`~bibdeskparser.entry.Entry.files`
itself is a read-only list of the stored relative paths; see
[BibDesk's `.bib` Format](bibdesk_format) for the background). This
also means the library must have a `.bib`
path: a from-scratch library must be saved before files can be
attached.

Attach a file with {py:meth}`~bibdeskparser.library.Library.add_file`.
The filename may be absolute, or relative to the library's directory
or to the current working directory (a relative name that exists in
both places is rejected as ambiguous; pass an absolute path instead):

```python
>>> import tempfile
>>> import warnings
>>> from pathlib import Path
>>> from bibdeskparser import Entry, Library
>>> tmpdir = tempfile.TemporaryDirectory()
>>> libdir = Path(tmpdir.name)
>>> _ = (libdir / "Smith2020.pdf").write_bytes(b"%PDF-1.4 fake")
>>> _ = (libdir / "notes.pdf").write_bytes(b"%PDF-1.4 fake notes")
>>> bib = Library()
>>> bib["Smith2020"] = Entry(
...     "article", "Smith2020", fields={"title": "A Title"}
... )
>>> bib.save(libdir / "library.bib")
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     _ = bib.add_file("Smith2020", libdir / "Smith2020.pdf")
...     _ = bib.add_file("Smith2020", "notes.pdf")  # library-relative
>>> bib["Smith2020"].files
['Smith2020.pdf', 'notes.pdf']

```

For a file that exists, a macOS *bookmark* is created automatically
(with the `bibdeskparser[macos]` extra installed), so BibDesk can
still locate the file after it is moved or renamed outside of
`bibdeskparser`. To link a file that does not exist here -- say, one
that lives only on another machine -- pass
`check_that_file_exists=False`; the name is then stored as-is,
relative to the library directory, and BibDesk fills in the bookmark
on its next save, once the file appears.

{py:meth}`~bibdeskparser.library.Library.rename_file` renames (or,
given a path with a directory component, moves) the file on disk and
updates *every* entry that links it, each with a fresh bookmark; it
returns the new stored path (relative to the library directory), as
does `add_file`:

```python
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     bib.rename_file("Smith2020", "notes.pdf", "Smith2020-notes.pdf")
'Smith2020-notes.pdf'
>>> bib["Smith2020"].files
['Smith2020.pdf', 'Smith2020-notes.pdf']
>>> (libdir / "Smith2020-notes.pdf").exists()
True

```

{py:meth}`~bibdeskparser.library.Library.unlink_file` removes an
attachment, and {py:meth}`~bibdeskparser.library.Library.replace_file`
swaps one file for another in place. Both require an explicit
`remove` keyword argument: whether to also delete the (old) file from
the filesystem -- moved to the Trash on macOS (with the
`bibdeskparser[macos]` extra), deleted permanently elsewhere, and
never deleted while another entry still links it:

```python
>>> bib.unlink_file("Smith2020", "Smith2020-notes.pdf", remove=False)
>>> bib["Smith2020"].files
['Smith2020.pdf']
>>> (libdir / "Smith2020-notes.pdf").exists()  # remove=False
True
>>> bib.save()
>>> tmpdir.cleanup()

```

(howto-auto-file)=

## How to auto-file attachments

Instead of naming every attachment by hand, let `bibdeskparser`
*auto-file* them (BibDesk's AutoFile feature): move each file into a
configured location and rename it according to a
[file-name format](specifiers-files). Configure it once in the
[`[auto_file]` table](config-auto-file) of `bibdeskparser.toml`:

```toml
[auto_file]
format_spec = "%f{Cite Key}%u0%e"  # <citation key><the file's extension>
location = "."                     # directory, relative to the .bib file
```

(equivalently, for the current process only,
`Library.config.auto_file.format_spec = "%f{Cite Key}%u0%e"`).

With that in place,
{py:meth}`~bibdeskparser.library.Library.rename_file` *without* a new
filename files an existing attachment, and
{py:meth}`~bibdeskparser.library.Library.eval_format_spec` with a
`filename` previews the generated path without moving anything:

```python
>>> tmpdir = tempfile.TemporaryDirectory()
>>> libdir = Path(tmpdir.name)
>>> _ = (libdir / "1512.02079v2.pdf").write_bytes(b"%PDF-1.4 fake")
>>> bib = Library()
>>> bib["Smith2020"] = Entry(
...     "article", "Smith2020", fields={"title": "A Title"}
... )
>>> bib.save(libdir / "library.bib")
>>> bib.config.auto_file.format_spec = "%f{Cite Key}%u0%e"
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     rel = bib.add_file("Smith2020", libdir / "1512.02079v2.pdf")
>>> rel  # attached under its original name
'1512.02079v2.pdf'
>>> bib.eval_format_spec("Smith2020", filename=rel)  # preview only
'Smith2020.pdf'
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     bib.rename_file("Smith2020", rel)  # move and rename the file
'Smith2020.pdf'
>>> bib["Smith2020"].files
['Smith2020.pdf']

```

Re-running `rename_file` on an already-filed attachment is a no-op (a
name that matches the format is kept), so auto-filing can safely be
applied across a whole library.

By default, `add_file` attaches a file under its original name, as
above; filing is a separate, on-demand step. Setting
`file_automatically = true` in `[auto_file]` makes `add_file`
auto-file every new attachment immediately. Per call, an explicit
`auto_file_location` (or `format_spec`) also enables auto-filing --
here into a subdirectory next to the `.bib` file:

```python
>>> _ = (libdir / "notes.pdf").write_bytes(b"%PDF-1.4 fake notes")
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     bib.add_file("Smith2020", "notes.pdf", auto_file_location="Papers")
'Papers/Smith2020.pdf'
>>> bib.config.auto_file.format_spec = None  # restore the default
>>> bib.save()
>>> tmpdir.cleanup()

```

(Conversely, `auto_file_location=""` forces a plain attach even with
`file_automatically = true`.)

## How to define or rename a `@string` macro (journal abbreviation)

Define a macro through {py:attr}`~bibdeskparser.library.Library.strings`,
then reference it in a field with a bare (unquoted) string; rename it
everywhere it is used with
{py:meth}`~bibdeskparser.library.Library.rename_string`.

```python
>>> bib = Library()
>>> entry = Entry("article", "Smith2020", fields={"title": "A Title"})
>>> bib["Smith2020"] = entry
>>> bib.strings["prl"] = "Phys. Rev. Lett."
>>> entry["journal"] = "prl"  # macro-shaped str, stored as a bare reference
>>> entry["journal"]
'prl'
>>> bib.rename_string("prl", "prl2")  # updates every referencing entry
>>> entry["journal"]
'prl2'
>>> bib.strings["prl2"]
'Phys. Rev. Lett.'

```

## How to organize entries into groups

{py:attr}`~bibdeskparser.library.Library.groups` is a `dict`-like
mapping of each group name to the tuple of its members' citation keys.
Create, replace, or delete whole groups through the mapping interface;
add or remove individual keys with
{py:meth}`~bibdeskparser.library.Library.add_to_group` /
{py:meth}`~bibdeskparser.library.Library.remove_from_group`. Every
affected entry's {py:attr}`~bibdeskparser.entry.Entry.groups` (a
read-only tuple) updates immediately.

```python
>>> bib = Library()
>>> bib["Smith2020"] = Entry(
...     "article", "Smith2020", fields={"title": "A Title"}
... )
>>> bib["Doe2021"] = Entry(
...     "article", "Doe2021", fields={"title": "Another Title"}
... )
>>> bib.groups["Favorites"] = ()  # create an empty group
>>> bib.add_to_group("Favorites", "Smith2020", "Doe2021")
>>> bib.groups
{'Favorites': ('Smith2020', 'Doe2021')}
>>> bib["Smith2020"].groups
('Favorites',)
>>> bib.remove_from_group("Favorites", "Doe2021")
>>> bib.groups["Favorites"]
('Smith2020',)

```

Assigning to a group name replaces its membership wholesale (creating
the group if needed), and `del` removes the group entirely, dropping it
from every member entry's `.groups`:

```python
>>> bib.groups["Reading List"] = ("Doe2021", "Smith2020")
>>> bib["Doe2021"].groups
('Reading List',)
>>> del bib.groups["Reading List"]
>>> bib["Doe2021"].groups
()

```

Group values are always tuples, so a group's membership can never be
mutated in place; the mapping and every entry's `.groups` therefore
stay consistent -- including when an entry is deleted from the library
or renamed with {py:meth}`~bibdeskparser.library.Library.rekey`, which
update the group data as well. `add_to_group` requires the group to
exist already (create it first, e.g. with an empty tuple), and all
assigned keys must belong to entries in the library.

## How to tag entries with keywords

{py:attr}`~bibdeskparser.library.Library.keywords` works just like
`.groups`, mapping each keyword to the tuple of citation keys of the
entries carrying it, with
{py:meth}`~bibdeskparser.library.Library.add_to_keyword` /
{py:meth}`~bibdeskparser.library.Library.remove_from_keyword` for
per-key changes and {py:attr}`~bibdeskparser.entry.Entry.keywords` as
the read-only per-entry tuple:

```python
>>> bib.add_to_keyword("methods", "Smith2020", "Doe2021")
>>> bib.keywords
{'methods': ('Smith2020', 'Doe2021')}
>>> bib["Smith2020"].keywords
('methods',)
>>> bib.remove_from_keyword("methods", "Doe2021")
>>> bib.keywords["methods"]
('Smith2020',)
>>> del bib.keywords["methods"]
>>> bib["Smith2020"].keywords
()

```

Unlike groups, keywords live inside each entry (as its stored
`keywords` field), so there is no separate creation step:
`add_to_keyword` creates a keyword the moment the first entry carries
it, and a keyword with no entries simply does not exist (assigning
`()` is equivalent to deleting it). The `keywords` field is readable
through the entry's `dict` interface (`entry["keywords"]` returns the
comma-joined string), but deliberately *not* writable that way
(`entry["keywords"] = ...` raises `KeyError`); routing all keyword
edits through the `Library` is what keeps `bib.keywords` and every
entry's `.keywords` consistent at all times. Since these edits change
the entry's stored fields, they also bump its `date-modified` and mark
it as modified since it was loaded.

## How to search a library

{py:meth}`~bibdeskparser.library.Library.search` returns the entries
matching a query, best match first:

```python
>>> bib = Library()
>>> bib.strings["adp"] = "Ann. Phys."
>>> bib["Schroedinger1926"] = Entry(
...     "article",
...     "Schroedinger1926",
...     fields={
...         "author": "Schrödinger, Erwin",
...         "title": "Quantisierung als Eigenwertproblem",
...         "journal": "adp",
...         "year": "1926",
...     },
... )
>>> bib["Einstein1905"] = Entry(
...     "article",
...     "Einstein1905",
...     fields={
...         "author": "Einstein, Albert",
...         "title": "Zur Elektrodynamik bewegter Körper",
...         "journal": "adp",
...         "year": "1905",
...     },
... )
>>> [e.key for e in bib.search("quantisierung eigenwertproblem")]
['Schroedinger1926']

```

Accented text is found by its accented, accent-stripped, and
transliterated spellings alike:

```python
>>> for query in ("Schrödinger", "Schrodinger", "Schroedinger"):
...     print([e.key for e in bib.search(query, fields=["author"])])
['Schroedinger1926']
['Schroedinger1926']
['Schroedinger1926']

```

A bare `@string` macro reference is found both by the macro's name and
by its expansion (and `fields` limits the search, with the pseudo-field
`"key"` selecting the citation key):

```python
>>> [e.key for e in bib.search("adp", fields=["journal"], match="exact")]
['Schroedinger1926', 'Einstein1905']
>>> [e.key for e in bib.search("Ann. Phys.", match="exact")]
['Schroedinger1926', 'Einstein1905']
>>> [e.key for e in bib.search("einstein", fields=["key"])]
['Einstein1905']

```

The `match` argument sets the match strictness, from `"exact"`
(verbatim substring, up to case) through `"folded"` (accent-insensitive)
and `"words"` (the default: most of the query's words occur, in any
order) to `"fuzzy"` (tolerates small typos); `match="regex"` instead
treats the query as a regular expression:

```python
>>> bib.search("Schrodinger", match="exact")
[]
>>> [e.key for e in bib.search("Schrodinger", match="folded")]
['Schroedinger1926']
>>> [e.key for e in bib.search("Eigenwertproblm", match="fuzzy")]
['Schroedinger1926']
>>> [e.key for e in bib.search(r"^Zur ", fields=["title"], match="regex")]
['Einstein1905']

```

At the `"fuzzy"` level, two words match when they agree on about 80% of
their letters. In practice this forgives a single typo per word -- one
wrong, missing, or extra letter, or one adjacent swap -- and along the
way bridges US/UK spellings and the plain-ASCII spelling of a
transliterated name. Because the threshold is a *fraction* of the word,
shorter words tolerate less: a four-letter word can lose or gain a
letter but not swap one for another, and a three-letter word is
essentially exact-only. A second typo survives only in longer words.

| Query word | Entry word | Matches? | Note |
| --- | --- | --- | --- |
| `quantom` | `quantum` | yes | one wrong letter |
| `hamltonian` | `hamiltonian` | yes | one missing letter |
| `controll` | `control` | yes | one extra letter |
| `theroy` | `theory` | yes | adjacent swap |
| `optimisation` | `optimization` | yes | US/UK spelling |
| `schrodinger` | `schroedinger` | yes | ASCII vs. transliteration |
| `gate` | `gates` | yes | short word, missing letter |
| `gate` | `rate` | no | short word, wrong letter |
| `cat` | `hat` | no | three-letter word |

A complementary guard rejects word pairs whose lengths differ by more
than two characters, and the `"words"`/`"fuzzy"` levels additionally
require at least 70% of the query's words to match, so a two-word query
tolerates one unmatched word but a three-word query still needs two of
its three.

On the command line, the `search` subcommand prints the matching keys
one per line, which composes with the other subcommands:

```console
$ bibdeskparser render library.bib $(bibdeskparser search library.bib "Schroedinger")
```

## How to find and resolve duplicate citation keys

A `.bib` file with two entries sharing a key still loads; the
duplicated keys are reported via
{py:attr}`~bibdeskparser.library.Library.duplicate_keys` (and a
`UserWarning` at load time). Give the offending entry a new key
directly in the `.bib` file, then reload:

```python
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # the duplicate-key warning itself
...     bib = Library("tests/Refs/refs.bib")
>>> bib.duplicate_keys
('GoerzJOSS2025',)

```

(howto-auto-keys)=

## How to automatically generate citation keys

Configure an auto-key format (in BibDesk's
[format-specifier language](format-specifiers)) in your
`bibdeskparser.toml`, then call
{py:meth}`~bibdeskparser.library.Library.rekey` with just the old
key:

```toml
[auto_key]
format_spec = "%a1%c{journal}0%Y%u0"
```

This particular format is a recommended scheme for a journal article:
first author's last name, the journal's initials, the full year, and
(only if needed) a disambiguating letter — e.g. `GoerzPRA2014`. For a
library that mixes entry types, give `format_spec` a
[per-type table](config-auto-key-per-type) instead (naming `booktitle`
for conference papers, `series` for books, and so on). The `[initials]`
table of the configuration handles venues whose initials should not be
the plain acronym (see [Venue initials](specifiers-initials)).

```python
>>> bib.rekey("GoerzPRA2014")               # doctest: +SKIP
'GoerzPRA2014'
```

The `format_spec` argument overrides the configured format ad hoc; keys
that already match the format are kept unchanged, so regenerating is
idempotent and safe to run over a whole library:

```python
>>> bib.rekey("GoerzPRA2014", format_spec="%a1%c{journal}0%Y%u0")
'GoerzPRA2014'
>>> for key in list(bib):
...     _ = bib.rekey(key, format_spec="%a1:%Y%u0")
>>> bib.rekey("Goerz:2014", format_spec="%a1%c{journal}0%Y%u0")
'GoerzNJP2014'

```

{py:meth}`~bibdeskparser.library.Library.eval_format_spec` evaluates
a format for an entry and returns the resulting key *without renaming
anything*. Since a key that already matches the format evaluates to
itself, this finds all citation keys that do not follow a given
format:

```python
>>> fmt = "%a1:%Y%u0"
>>> [key for key in bib if bib.eval_format_spec(key, fmt) != key]
['GoerzNJP2014']

```

On the command line, the same is available as `bibdeskparser rekey
BIBFILE OLD_KEY` (see the {ref}`CLI reference <cli-rekey>`), which
prints the generated key, and as the read-only `bibdeskparser
eval_format_spec BIBFILE KEY [FORMAT]`.

## How to add a reference from a DOI, arXiv ID, or search query

{py:meth}`~bibdeskparser.library.Library.add` fetches the metadata
from the appropriate online source (Crossref for a DOI or free-text
search, the arXiv API for an arXiv identifier), sanitizes it, and
adds a new entry:

```python
bib.add("10.1103/PhysRevA.89.032334")        # a DOI
bib.add("https://arxiv.org/abs/2205.15044")  # an arXiv preprint
bib.add("pulser open-source pulse sequences")  # best search match
bib.save()
```

On the command line ({ref}`CLI reference <cli-add>`):

```console
$ bibdeskparser add library.bib 10.1103/PhysRevA.89.032334
MuellerPRA2014
$ bibdeskparser add library.bib --dry-run some paper title  # no write
```

The new entry follows the library's conventions automatically: the
journal is stored as an `@string` macro (see the
[`[journal_macros]` configuration](config-journal-macros)), the title
is brace-protected, and the citation key is generated (e.g.
`MuellerPRA2014`, or `Goerz2205.15044` for a preprint). An entry
whose DOI or arXiv eprint is already in the library is rejected, so
re-adding the same paper is safe.

To also store the paper's abstract in the new entry, pass
`add_abstract=True` (`--add-abstract` on the command line); to also
search arXiv for a matching preprint and record it in the `eprint`
field, pass `add_preprint=True` (`--add-preprint`). See the next two
recipes for filling in abstracts and arXiv identifiers after the
fact. To make either behavior the default, set it once in the
[`[add]` configuration table](config-add):

```toml
[add]
add_abstract = true
add_preprint = true
```

## How to fill in missing abstracts

{py:meth}`Library.add_abstract <bibdeskparser.library.Library.add_abstract>`
fetches the abstract of an existing entry -- from Crossref (via the entry's
`doi`), the entry's attached PDF (requires the
[poppler](https://poppler.freedesktop.org) `pdftotext` tool), the
arXiv API (via `eprint`), or Semantic Scholar -- cleans it to
plain-unicode prose, and stores it in the entry's `abstract` field:

```python
result = bib.add_abstract("MuellerPRA2014")
bib.save()
```

Each result carries the source it came from and a *confidence* level;
only a `high`-confidence abstract (identified by the entry's
`doi`/`eprint`, or confirmed by two independent sources) is stored by
default. On the command line, list the entries that need an abstract,
fill them in bulk, and review what remains
({ref}`CLI reference <cli-add-abstract>`):

```console
$ bibdeskparser keys library.bib --type article --missing abstract
BaumgratzPRL2014
Koch2016
$ bibdeskparser add_abstract library.bib BaumgratzPRL2014 Koch2016
BaumgratzPRL2014: stored (crossref, high)
Koch2016: needs review (pdf, medium) [cr-miss; pdf-abstract-inline]
    We review different aspects of quantum control ...
```

A lower-confidence candidate is reported in full instead of stored;
after checking it (against the PDF or the publisher page), apply it
with `set_field`, or store whatever the sources found by lowering the
bar with `--min-confidence medium`:

```console
$ bibdeskparser set_field library.bib Koch2016 abstract \
    "We review different aspects of quantum control ..."
```

For an entry whose abstract genuinely cannot be found, store an
*empty* abstract as an "audited" marker -- either explicitly
(`set_field KEY abstract ""`) or with `add_abstract --mark-empty`.
The entry then no longer shows up in `keys --missing abstract` (it is
matched by `keys --empty abstract` instead), so repeated fill-in
passes stay fast and idempotent.

(howto-add-preprint)=

## How to fill in missing arXiv identifiers

{py:meth}`Library.add_preprint <bibdeskparser.library.Library.add_preprint>`
searches arXiv for the preprint of an existing entry and records its identifier in
the entry's `eprint` field (along with `archiveprefix = arXiv`):

```python
result = bib.add_preprint("MuellerPRA2014")
bib.save()
```

A search result is stored only on a confident match: an arXiv DOI
equal to the entry's `doi`, a near-exact title match, or a good title
match corroborated by the first author. On the command line, list the
entries whose preprint status is unknown and fill them in bulk
({ref}`CLI reference <cli-add-preprint>`):

```console
$ bibdeskparser keys library.bib --type article --missing eprint
BaumgratzPRL2014
Feynman1982
$ bibdeskparser add_preprint library.bib --mark-empty \
    BaumgratzPRL2014 Feynman1982
BaumgratzPRL2014: stored eprint 1311.0275 (match=doi, ratio=1.00)
Feynman1982: no preprint found (stored empty marker) [best-ratio=0.31]
```

With `--mark-empty` (or `mark_empty = true` in the
[`[add_preprint]` configuration table](config-add)), an entry for
which no preprint is found gets an *empty* `eprint` field. Like the
empty-abstract marker of the previous recipe, this records "searched,
nothing found": the entry moves from `keys --missing eprint` to
`keys --empty eprint`, so repeated fill-in passes do not re-query
arXiv for it. Since a non-match can also be a matching failure,
re-audit those markers occasionally:

```console
$ bibdeskparser add_preprint library.bib $(bibdeskparser keys \
    library.bib --empty eprint)
```

A match that the search rejects as `postdated-unverified` (an arXiv
submission years after the entry's publication, without a
corroborating journal reference) is only reported; if reviewing it
shows it really is the paper's preprint (authors do post old papers
late), record it explicitly, which needs no network access:

```console
$ bibdeskparser add_preprint library.bib Greiner2002 --eprint 2505.01234
```

The search respects the arXiv API's rate limit of one request every
three seconds, so filling in a large library takes time -- let it
run.

## How to import BibTeX entries from a publisher or another library

{py:meth}`~bibdeskparser.library.Library.import_bibtex` runs any
BibTeX snippet -- a publisher's "export citation" download, or
entries from another `.bib` file -- through the same sanitization and
adds the entries:

```python
bib.import_bibtex(text)   # text: BibTeX for one or more entries
bib.save()
```

On the command line, `import` reads from a file, stdin, or a URL
({ref}`CLI reference <cli-import>`):

```console
$ bibdeskparser import library.bib entries.bib
$ pbpaste | bibdeskparser import library.bib --stdin
$ bibdeskparser import library.bib --url https://example.com/refs.bib
```

Since [`export`](cli-export) writes exactly the kind of snippet that
`import` accepts (including the `@string` definitions), this also
moves entries between libraries:

```console
$ bibdeskparser export library.bib GoerzPRA2014 \
    | bibdeskparser import other.bib --stdin
GoerzPRA2014
```

If anything about a snippet is not acceptable (an undefined macro, an
entry whose DOI is already present, ...), the whole import is
rejected with a list of all problems and the library is left
untouched.

## How to edit an entry in your text editor

{py:meth}`~bibdeskparser.library.Library.edit` opens one or more
entries in `$EDITOR` as bibtex text and merges back whatever you save:

```python
bib.edit("Smith2020")                      # a single entry
bib.edit("Smith2020", "Doe2021", editor="vim")  # several at once
```

## How to render a bibliography in a specific citation format

{py:meth}`~bibdeskparser.library.Library.render` produces a formatted
citation string for one or more citation keys; pass `format="markdown"`
(default), `"tex"`, or `"html"`. When rendering several entries, `style`
controls their layout: `"default"`, `"paragraphs"`, `"numbered list"`,
or `"itemized list"`.

```python
>>> bib = Library()
>>> smith = Entry(
...     "article",
...     "Smith2020",
...     fields={
...         "title": "A Title",
...         "author": "Smith, John",
...         "journal": "J. Test",
...         "year": "2020",
...     },
... )
>>> doe = Entry(
...     "article",
...     "Doe2021",
...     fields={
...         "title": "Another Title",
...         "author": "Doe, Jane",
...         "journal": "J. Test",
...         "year": "2021",
...     },
... )
>>> bib["Smith2020"] = smith
>>> bib["Doe2021"] = doe
>>> print(bib.render("Smith2020", format="html"))
J. Smith. <i>A Title</i>. J. Test (2020).
>>> print(bib.render("Smith2020", "Doe2021", format="tex"))
J. Smith. \textit{A Title}. J. Test (2020).
<BLANKLINE>
J. Doe. \textit{Another Title}. J. Test (2021).
>>> print(bib.render("Smith2020", "Doe2021", style="numbered list"))
1. J. Smith. *A Title*. J. Test (2020).
2. J. Doe. *Another Title*. J. Test (2021).

```

(howto-ai)=

## How to give an AI coding agent access to your library

`bibdeskparser` ships no dedicated AI integration, because it does not
need one: the {ref}`command-line tool <cli>` *is* the integration
surface.
Any agent that can run shell commands, such as
[Claude Code](https://claude.com/claude-code), can inspect and edit
your BibDesk library by calling `bibdeskparser`. Each invocation is a
one-shot process that loads the `.bib` file, does its work, and exits,
so there is no server to run and nothing to keep alive.

**1. Put the tool on `PATH`.** Install the package into an environment
the agent can reach (see [Installation](readme)); the simplest way is
`uv tool install bibdeskparser`. Verify that `bibdeskparser` runs from
a plain shell:

```console
$ bibdeskparser --version
```

**2. Point it at your library.** Set `default_bib_file` in a
`bibdeskparser.toml` (see [Configuration](configuration)) so commands
need no path argument:

```toml
default_bib_file = "/Users/you/Documents/references.bib"
```

Otherwise the agent must pass the `.bib` path as the first argument to
every command.

**3. Tell the agent the tool exists.** In an environment file the agent
reads at startup (for Claude Code, a `CLAUDE.md`), describe the tool and
point it at the built-in help. The agent discovers the full command set
itself from `--help`; you only need a few lines:

```markdown
## Bibliography

My BibDesk reference database is managed with the `bibdeskparser` CLI
(`default_bib_file` is configured, so commands need no path argument).
Run `bibdeskparser --help` for the command list and
`bibdeskparser COMMAND --help` for a command's arguments. Use `--json`
on read-only commands (`show`, `search`, `keys`, ...) for reliable
parsing. To find entries, prefer `bibdeskparser search`. For free-form
edits, pipe modified `export` output back through `edit --stdin`.
```

**4. Reduce permission prompts (optional).** Agents that gate shell
access can be told to allow the tool without prompting. In Claude Code,
add `bibdeskparser` to the allowlist (`Bash(bibdeskparser:*)` in
`.claude/settings.json`).

A few properties make the CLI safe to hand to an agent:

- **Machine-readable output.** Every read-only command accepts `--json`,
  so the agent parses structured data instead of scraping text.
- **Concurrent-edit safety.** Mutating commands save in place and refuse
  to overwrite a `.bib` file that changed on disk since it was read
  (whether by BibDesk, by you, or by another agent), failing with a
  {exc}`~bibdeskparser.StaleFileError` and exit code 1 rather than
  clobbering the newer version. Nothing coordinates *between* agents up
  front, but no write silently loses another's changes.
- **Nothing blocks.** Every command is usable non-interactively.
  `edit` and `edit_strings` open `$EDITOR` only when run from a
  terminal; an agent passes `--stdin` instead and pipes in the edited
  text (see below). Invoked without a terminal and without
  `--stdin`/`--editor`, they fail fast with a usage error rather than
  hanging on `$EDITOR`.

For edits beyond the dedicated mutating commands (changing a title,
fixing an author list, adding an arbitrary field), the agent round-trips
an entry through `export` and `edit --stdin`: `export` prints exactly
the text that `edit` would show in an editor, so transforming that text
and piping it back applies the change, and piping it back unchanged is
a no-op.

```console
$ bibdeskparser export Preskill2018 \
    | sed 's/NISQ era/noisy intermediate-scale quantum era/' \
    | bibdeskparser edit Preskill2018 --stdin
```

The `@string` macro definitions round-trip the same way, from
`strings --bib` into `edit_strings --stdin`. Invalid edited text (an
unparseable block, a reference to an undefined macro) exits with code 1
and the list of problems on stderr, leaving the `.bib` file untouched.

## How to export a minimal BibTeX file for LaTeX

{py:meth}`~bibdeskparser.library.Library.export` writes selected
entries as plain bibtex text, stripped of BibDesk-only fields; use
`format="minimal"` to further restrict each entry to a small,
per-entry-type whitelist of citation-relevant fields (dropping things
like `abstract` and `annote`), and `outfile=` to write straight to a
file:

```python
>>> smith["abstract"] = "Some abstract text, dropped by minimal export."
>>> with tempfile.TemporaryDirectory() as outdir:
...     outfile = Path(outdir) / "paper.bib"
...     bib.export(
...         "Smith2020", "Doe2021", format="minimal", outfile=str(outfile)
...     )
...     print(outfile.read_text())
@article{Smith2020,
    Author = {Smith, John},
    Title = {A Title},
    Journal = {J. Test},
    Year = {2020},
}
<BLANKLINE>
@article{Doe2021,
    Author = {Doe, Jane},
    Title = {Another Title},
    Journal = {J. Test},
    Year = {2021},
}
<BLANKLINE>

```
