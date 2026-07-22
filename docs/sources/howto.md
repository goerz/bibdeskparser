# How-to Guides

These short, task-oriented recipes assume you are already familiar with the
basics of `bibdeskparser` (see the [introduction](readme)); for background on
*why* things work this way, see [BibDesk's `.bib` Format](bibdesk_format).
All examples operate on the example database shipped in the repository at
`tests/Refs/refs.bib`; substitute the path to your own library.

## How to manage file attachments

```{tip}
Rather than naming and placing every attachment by hand, you can have
`bibdeskparser` *auto-file* them -- moving each file into a configured
location and renaming it by a file-name format (BibDesk's AutoFile
feature). See [How to auto-file attachments](howto-auto-file) below.
```

Linked files are stored with paths relative to the library's `.bib`
file, so attaching, replacing, unlinking, and renaming them are
`Library` operations ({py:attr}`Entry.files <bibdeskparser.entry.Entry.files>`
itself is a read-only list of the stored relative paths; see
[BibDesk's `.bib` Format](bibdesk_format) for the background). This
also means the library must have a `.bib`
path: a from-scratch library must be saved before files can be
attached.

Attach a file with {py:meth}`Library.add_file <bibdeskparser.library.Library.add_file>`.
The filename may be absolute, or relative to the library's directory
or to the current working directory (a relative name that exists in
both places is rejected as ambiguous; pass an absolute path instead).
Here, a PDF that was saved next to the `.bib` file is attached to the
entry for the book it belongs to:

```python
>>> import warnings
>>> from pathlib import Path
>>> from bibdeskparser import Library
>>> bib = Library("tests/Refs/refs.bib")
>>> bib["Shapiro2012"].files  # no attachment yet
[]
>>> pdf = Path("tests/Refs/shapiro-brumer-2012.pdf")
>>> _ = pdf.write_bytes(b"%PDF-1.4 fake")
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     _ = bib.add_file("Shapiro2012", "shapiro-brumer-2012.pdf")
>>> bib["Shapiro2012"].files
['shapiro-brumer-2012.pdf']

```

For a file that exists, a macOS *bookmark* is created automatically
(with the `bibdeskparser[macos]` extra installed), so BibDesk can
still locate the file after it is moved or renamed outside of
`bibdeskparser`. To link a file that does not exist here -- say, one
that lives only on another machine -- pass
`check_that_file_exists=False`; the name is then stored as-is,
relative to the library directory, and BibDesk fills in the bookmark
on its next save, once the file appears.

{py:meth}`Library.rename_file <bibdeskparser.library.Library.rename_file>`
renames (or, given a path with a directory component, moves) the file
on disk and
updates *every* entry that links it, each with a fresh bookmark; it
returns the new stored path (relative to the library directory), as
does `add_file`:

```python
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     bib.rename_file(
...         "Shapiro2012", "shapiro-brumer-2012.pdf", "Shapiro2012.pdf"
...     )
'Shapiro2012.pdf'
>>> bib["Shapiro2012"].files
['Shapiro2012.pdf']
>>> Path("tests/Refs/Shapiro2012.pdf").exists()
True

```

{py:meth}`Library.unlink_file <bibdeskparser.library.Library.unlink_file>`
removes an attachment, and
{py:meth}`Library.replace_file <bibdeskparser.library.Library.replace_file>`
swaps one file for another in place. Both require an explicit
`remove` keyword argument: whether to also delete the (old) file from
the filesystem -- moved to the Trash on macOS (with the
`bibdeskparser[macos]` extra), deleted permanently elsewhere, and
never deleted while another entry still links it:

```python
>>> bib.unlink_file("Shapiro2012", "Shapiro2012.pdf", remove=False)
>>> bib["Shapiro2012"].files
[]
>>> Path("tests/Refs/Shapiro2012.pdf").exists()  # remove=False
True
>>> bib.save()

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
{py:meth}`Library.rename_file <bibdeskparser.library.Library.rename_file>`
*without* a new filename files an existing attachment, and
{py:meth}`Library.eval_format_spec <bibdeskparser.library.Library.eval_format_spec>`
with a `filename` previews the generated path without moving anything:

```python
>>> _ = Path("tests/Refs/2018_AAMOP_sola.pdf").write_bytes(
...     b"%PDF-1.4 fake"
... )
>>> bib.config.auto_file.format_spec = "%f{Cite Key}%u0%e"
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     rel = bib.add_file("SolaAAMOP2018", "2018_AAMOP_sola.pdf")
>>> rel  # attached under its original name
'2018_AAMOP_sola.pdf'
>>> bib.eval_format_spec("SolaAAMOP2018", filename=rel)  # preview only
'SolaAAMOP2018.pdf'
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     bib.rename_file("SolaAAMOP2018", rel)  # move and rename the file
'SolaAAMOP2018.pdf'
>>> bib["SolaAAMOP2018"].files
['SolaAAMOP2018.pdf']

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
>>> _ = Path("tests/Refs/simpson_chapter.pdf").write_bytes(
...     b"%PDF-1.4 fake"
... )
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     bib.add_file(
...         "JuhlARNMRS2020",
...         "simpson_chapter.pdf",
...         auto_file_location="Papers",
...     )
'Papers/JuhlARNMRS2020.pdf'
>>> bib.config.auto_file.format_spec = None  # restore the default
>>> bib.save()

```

(Conversely, `auto_file_location=""` forces a plain attach even with
`file_automatically = true`.)

(howto-string-macros)=

## How to define or rename a `@string` macro (journal abbreviation)

Define a macro through
{py:attr}`Library.strings <bibdeskparser.library.Library.strings>`,
then reference it in a field with a bare (unquoted) string; rename it
everywhere it is used with
{py:meth}`Library.rename_string <bibdeskparser.library.Library.rename_string>`.
Here, a long book series title is turned into a macro:

```python
>>> bib.strings["aamop"] = (
...     "Advances In Atomic, Molecular, and Optical Physics"
... )
>>> entry = bib["SolaAAMOP2018"]
>>> entry["booktitle"] = "aamop"  # macro-shaped str: a bare reference
>>> entry["booktitle"]
'aamop'
>>> bib.rename_string("aamop", "adv_amop")  # updates referencing entries
>>> entry["booktitle"]
'adv_amop'
>>> bib.strings["adv_amop"]
'Advances In Atomic, Molecular, and Optical Physics'

```

## How to organize entries into groups

{py:attr}`Library.groups <bibdeskparser.library.Library.groups>` is a
`dict`-like mapping of each group name to the tuple of its members'
citation keys. Create, replace, or delete whole groups through the
mapping interface; add or remove individual keys with
{py:meth}`Library.add_to_group <bibdeskparser.library.Library.add_to_group>` /
{py:meth}`Library.remove_from_group <bibdeskparser.library.Library.remove_from_group>`.
Every affected entry's
{py:attr}`Entry.groups <bibdeskparser.entry.Entry.groups>` (a
read-only tuple) updates immediately.

```python
>>> bib.groups["To Read"] = ()  # create an empty group
>>> bib.add_to_group("To Read", "BrifNJP2010", "KochEPJQT2022")
>>> bib.groups["To Read"]
('BrifNJP2010', 'KochEPJQT2022')
>>> bib["BrifNJP2010"].groups
('To Read',)
>>> bib.remove_from_group("To Read", "KochEPJQT2022")
>>> bib.groups["To Read"]
('BrifNJP2010',)

```

Assigning to a group name replaces its membership wholesale (creating
the group if needed), and `del` removes the group entirely, dropping it
from every member entry's `.groups`:

```python
>>> bib.groups["To Read"] = ("KochJPCM2016", "KochEPJQT2022")
>>> bib["KochJPCM2016"].groups
('To Read',)
>>> del bib.groups["To Read"]
>>> bib["KochJPCM2016"].groups
()

```

Group values are always tuples, so a group's membership can never be
mutated in place; the mapping and every entry's `.groups` therefore
stay consistent -- including when an entry is deleted from the library
or renamed with
{py:meth}`Library.rekey <bibdeskparser.library.Library.rekey>`, which
update the group data as well. `add_to_group` requires the group to
exist already (create it first, e.g. with an empty tuple), and all
assigned keys must belong to entries in the library.

Groups also back the *known-missing* bookkeeping of the
[abstract](howto-add-abstract) and [preprint](howto-add-preprint)
recipes: a group declared in the `[known_missing]` configuration
records which entries are verified not to have a given field (see
[Empty fields](bibdesk-empty-fields)).

## How to tag entries with keywords

{py:attr}`Library.keywords <bibdeskparser.library.Library.keywords>`
works just like `.groups`, mapping each keyword to the tuple of
citation keys of the entries carrying it, with
{py:meth}`Library.add_to_keyword <bibdeskparser.library.Library.add_to_keyword>` /
{py:meth}`Library.remove_from_keyword <bibdeskparser.library.Library.remove_from_keyword>`
for per-key changes and
{py:attr}`Entry.keywords <bibdeskparser.entry.Entry.keywords>` as
the read-only per-entry tuple:

```python
>>> bib.add_to_keyword("Review", "BrifNJP2010", "KochEPJQT2022")
>>> bib.keywords["Review"]
('BrifNJP2010', 'KochEPJQT2022')
>>> bib["BrifNJP2010"].keywords
('OCT', 'Coherent Control', 'Review')
>>> bib.remove_from_keyword("Review", "KochEPJQT2022")
>>> bib.keywords["Review"]
('BrifNJP2010',)
>>> del bib.keywords["Review"]
>>> bib["BrifNJP2010"].keywords
('OCT', 'Coherent Control')

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

{py:meth}`Library.search <bibdeskparser.library.Library.search>`
returns the entries matching a query, best match first:

```python
>>> bib = Library("tests/Refs/refs.bib")
>>> [e.key for e in bib.search("krotov monotonic convergence")]
['GoerzSPP2019']

```

Accented text is found by its accented, accent-stripped, and
transliterated spellings alike:

```python
>>> for query in ("Schrödinger", "Schrodinger", "Schroedinger"):
...     print([e.key for e in bib.search(query, fields=["title"])])
['WP_Schroedinger']
['WP_Schroedinger']
['WP_Schroedinger']

```

A bare `@string` macro reference is found both by the macro's name and
by its expansion (and `fields` limits the search, with the pseudo-field
`"key"` selecting the citation key):

```python
>>> [e.key for e in bib.search("epjd", fields=["journal"], match="exact")]
['Luc-KoenigEPJD2004']
>>> [e.key for e in bib.search("Eur. Phys. J. D", match="exact")]
['Luc-KoenigEPJD2004']
>>> [e.key for e in bib.search("tannor", fields=["key"])]
['Tannor2007', 'TannorBookChapter1991']

```

The `match` argument sets the match strictness, from `"exact"`
(verbatim substring, up to case) through `"folded"` (accent-insensitive)
and `"words"` (the default: most of the query's words occur, in any
order) to `"fuzzy"` (tolerates small typos); `match="regex"` instead
treats the query as a regular expression:

```python
>>> bib.search("Universitat Kassel", match="exact")
[]
>>> [e.key for e in bib.search("Universitat Kassel", match="folded")]
['GoerzPhd2015']
>>> bib.search("quantom speed limit", match="fuzzy")[0].key
'GoerzJPB2011'
>>> [
...     e.key
...     for e in bib.search(
...         r"^The quantum speed limit", fields=["title"], match="regex"
...     )
... ]
['GoerzJPB2011']

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
$ bibdeskparser render tests/Refs/refs.bib \
    $(bibdeskparser search tests/Refs/refs.bib "tractor atom")
```

## How to find and resolve duplicate citation keys

A `.bib` file with two entries sharing a key still loads; the
duplicated keys are reported via
{py:attr}`Library.duplicate_keys <bibdeskparser.library.Library.duplicate_keys>`
(and a `UserWarning` at load time). Give the offending entry a new key
directly in the `.bib` file, then reload:

```python
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # the duplicate-key warning itself
...     dup_bib = Library("tests/Refs/with_duplicates.bib")
>>> dup_bib.duplicate_keys
('GoerzSPP2019',)

```

(howto-auto-keys)=

## How to automatically generate citation keys

Configure an auto-key format (in BibDesk's
[format-specifier language](format-specifiers)) in your
`bibdeskparser.toml`, then call
{py:meth}`Library.rekey <bibdeskparser.library.Library.rekey>` with
just the old key:

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
>>> bib = Library("tests/Refs/refs.bib")
>>> bib.rekey("GoerzPRA2014")               # doctest: +SKIP
'GoerzPRA2014'
```

The `format_spec` argument overrides the configured format ad hoc; keys
that already match the format are kept unchanged, so regenerating is
idempotent and safe to re-run over many entries (here, one group;
entries lacking a field the format requires, such as `author`, are
reported with a `ValueError`):

```python
>>> bib.rekey("GoerzPRA2014", format_spec="%a1%c{journal}0%Y%u0")
'GoerzPRA2014'
>>> for key in bib.groups["My Papers"]:
...     _ = bib.rekey(key, format_spec="%a1:%Y%u0")
>>> bib.rekey("Goerz:2014", format_spec="%a1%c{journal}0%Y%u0")
'GoerzNJP2014'

```

{py:meth}`Library.eval_format_spec <bibdeskparser.library.Library.eval_format_spec>`
evaluates a format for an entry and returns the resulting key *without
renaming anything*. Since a key that already matches the format evaluates to
itself, this finds all citation keys that do not follow a given
format:

```python
>>> fmt = "%a1:%Y%u0"
>>> [
...     key
...     for key in bib.groups["My Papers"]
...     if bib.eval_format_spec(key, fmt) != key
... ]
['GoerzNJP2014']

```

On the command line, the same is available as `bibdeskparser rekey
BIBFILE OLD_KEY` (see the {ref}`CLI reference <cli-rekey>`), which
prints the generated key, and as the read-only `bibdeskparser
eval_format_spec BIBFILE KEY [FORMAT]`.

## How to add a reference from a DOI, arXiv ID, or search query

{py:meth}`Library.add <bibdeskparser.library.Library.add>` fetches the
metadata from the appropriate online source (Crossref for a DOI or free-text
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
$ bibdeskparser add tests/Refs/refs.bib 10.1103/PhysRevA.89.032334
MuellerPRA2014
$ bibdeskparser add tests/Refs/refs.bib --dry-run some paper title  # no write
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

(howto-add-abstract)=

## How to fill in missing abstracts

{py:meth}`Library.add_abstract <bibdeskparser.library.Library.add_abstract>`
fetches the abstract of an existing entry -- from Crossref (via the entry's
`doi`), the entry's attached PDF (requires the
[poppler](https://poppler.freedesktop.org) `pdftotext` tool), the
arXiv API (via `eprint`), or Semantic Scholar -- cleans it to
plain-unicode prose, and stores it in the entry's `abstract` field:

```python
result = bib.add_abstract("SauvagePRXQ2020")
bib.save()
```

Each result carries the source it came from and a *confidence* level;
only a `high`-confidence abstract (identified by the entry's
`doi`/`eprint`, or confirmed by two independent sources) is stored by
default. On the command line, list the entries that need an abstract,
fill them in bulk, and review what remains
({ref}`CLI reference <cli-add-abstract>`):

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing abstract
SauvagePRXQ2020
KatrukhaNC2017
$ bibdeskparser add_abstract tests/Refs/refs.bib \
    SauvagePRXQ2020 Vecheck2022.09.09.507322
SauvagePRXQ2020: stored (crossref, high)
Vecheck2022.09.09.507322: needs review (semanticscholar, medium) [cr-miss]
    Quantum biology examines quantum effects in living cells ...
```

A lower-confidence candidate is reported in full instead of stored;
after checking it (against the PDF or the publisher page), apply it
with `set_field`, or store whatever the sources found by lowering the
bar with `--min-confidence medium`:

```console
$ bibdeskparser set_field tests/Refs/refs.bib Vecheck2022.09.09.507322 \
    abstract "Quantum biology examines quantum effects in living cells ..."
```

For an entry whose abstract genuinely cannot be found, record the
verified absence as membership in a *known-missing group*: a regular
[BibDesk static group](bibdesk-static-groups), declared in the
`[known_missing]` table of `bibdeskparser.toml`
([configuration](config-known-missing)):

```toml
[known_missing]
abstract = "No Abstract"
```

With the group declared, `add_abstract` maintains it automatically: a
search that runs cleanly and finds nothing adds the entry to the
group (creating the group on first use), group members are skipped by
later runs (so repeated fill-in passes stay fast and idempotent), and
storing an abstract removes the entry from the group again. To
re-audit the group members on explicit demand (an abstract may have
become available since the last check), pass `--overwrite` and select
exactly them, as shown for preprints in the next recipe. An entry
can also be marked by hand, with `add_to_group` or by drag and drop
in BibDesk:

```console
$ bibdeskparser set_group tests/Refs/refs.bib "No Abstract"
$ bibdeskparser add_to_group tests/Refs/refs.bib "No Abstract" KatrukhaNC2017
$ bibdeskparser keys tests/Refs/refs.bib --group "No Abstract"
KatrukhaNC2017
```

An *empty* `abstract` field cannot serve as the marker: BibDesk
deletes empty fields whenever it saves the library, while a static
group survives (see [Empty fields](bibdesk-empty-fields)).

(howto-add-preprint)=

## How to fill in missing arXiv identifiers

{py:meth}`Library.add_preprint <bibdeskparser.library.Library.add_preprint>`
searches arXiv for the preprint of an existing entry and records its identifier in
the entry's `eprint` field (along with `archiveprefix = arXiv` and
the preprint's primary category in `primaryclass`):

```python
result = bib.add_preprint("WinckelIP2008")
bib.save()
```

A search result is stored only on a confident match: an arXiv DOI
equal to the entry's `doi`, a near-exact title match, or a good title
match corroborated by the first author. On the command line, list the
entries whose preprint status is unknown and fill them in bulk
({ref}`CLI reference <cli-add-preprint>`):

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing eprint
WinckelIP2008
$ bibdeskparser add_preprint tests/Refs/refs.bib \
    WinckelIP2008 Vecheck2022.09.09.507322
WinckelIP2008: no preprint found (marked known missing in group 'No Eprint') [best-ratio=0.42]
Vecheck2022.09.09.507322: no preprint found (marked known missing in group 'No Eprint') [best-ratio=0.31]
```

The report above assumes a known-missing group declared for `eprint`
in `bibdeskparser.toml`, like the one of the previous recipe
([configuration](config-known-missing)):

```toml
[known_missing]
eprint = "No Eprint"
```

An entry for which the search runs cleanly and finds nothing is then
added to the group, and group members are skipped by every later
run, so repeated fill-in passes ("find the preprint for everything
that is missing one") never re-query arXiv for them. Membership
records "searched, nothing found at the time", which is not the same
as "does not exist": the match may have failed, or the preprint may
have been posted since the last check. Re-auditing those entries
therefore happens only on explicit demand, by passing `--overwrite`
and selecting exactly the group members:

```console
$ bibdeskparser add_preprint tests/Refs/refs.bib --overwrite \
    $(bibdeskparser keys tests/Refs/refs.bib --group "No Eprint")
```

A re-audited entry with another clean no-match simply stays in the
group; a new match stores the identifier and removes the entry from
the group.

A match that the search rejects as `postdated-unverified` (an arXiv
submission years after the entry's publication, without a
corroborating journal reference) is only reported; if reviewing it
shows it really is the paper's preprint (authors do post old papers
late), record it explicitly, which needs no network access:

```console
$ bibdeskparser add_preprint tests/Refs/refs.bib WinckelIP2008 \
    --eprint 2505.01234
```

The search respects the arXiv API's rate limit of one request every
three seconds, so filling in a large library takes time -- let it
run.

(howto-preprints)=

## How to manage preprint-only publications

`bibdeskparser` stores a preprint-only work as an `@unpublished`
entry that carries the structured
`eprint`/`archiveprefix`/`primaryclass` fields, a *pseudo-journal*
like `arXiv:2205.15044`, `bioRxiv:2022.09.09.507322`, or
`HAL:hal-00640217`, a `doi`, and a publication-status `note` -- see
[](preprints) for this convention and the reasoning behind it.

To add a preprint from arXiv, pass its identifier (or its
`arxiv.org` URL) to [`add`](cli-add), which fetches the metadata and
creates the entry in this form:

```console
$ bibdeskparser add tests/Refs/refs.bib 2212.12602
Goerz2212.12602
```

For any preprint server, [`import`](cli-import) recognizes a
preprint-only entry in incoming BibTeX -- by its pseudo-journal, or
as a `misc`/`unpublished` entry with an `eprint` (e.g. arXiv's own
"Export BibTeX citation") -- and normalizes it into the same form
(`@unpublished` type, canonical archive spelling, derived
`eprint`/`archiveprefix`/`doi` fields):

```console
$ bibdeskparser import tests/Refs/refs.bib --stdin << 'EOF'
@article{naceur,
    Author = {Naceur, Younes and Balada Gaggioli, Llorenç},
    Title = {Reachability and optimal-time certificates for quantum control},
    Journal = {HAL:hal-05667276},
    Url = {https://hal.science/hal-05667276},
    Year = {2026},
}
EOF
Naceurhal-05667276
```

An archive that `bibdeskparser` does not recognize is rejected (the
journal must not be turned into an `@string` macro); add it to the
[`[preprint_archives]` configuration table](config-preprint-archives),
or use `--keep-journals` to keep every incoming `journal` (and entry
type) untouched.

Record the publication status in the `note` field -- "preprint
only", "submitted to Phys. Rev. A", "lecture notes". The note is
never filled in automatically; an entry without one shows up as
incomplete in BibDesk (`note` is a required field of
`@unpublished`), which is your signal to set it:

```console
$ bibdeskparser set_field tests/Refs/refs.bib Naceurhal-05667276 note \
    "preprint only"
```

To cite preprints from LaTeX, export them in the form that
matches the document's bibliography style (`--preprint`, defaulting
to the [`preprint_export` setting](config-preprint-export)): the
structured `unpublished` (default) or `misc` forms for styles that
render the `eprint` field (REVTeX, `elsarticle`, biblatex), or the
`article` form for classic styles (`plain`, `unsrt`, `IEEEtran`,
...) that would drop it:

```console
$ bibdeskparser export tests/Refs/refs.bib Wilhelm2003.10132 --minimal
@unpublished{Wilhelm2003.10132,
    Author = {Wilhelm, Frank K. and Kirchhoff, Susanna and Machnes, Shai and Wittler, Nicolas and Sugny, Dominique},
    Title = {An introduction into optimal control for quantum technologies},
    Eprint = {2003.10132},
    Archiveprefix = {arXiv},
    Primaryclass = {quant-ph},
    Doi = {10.48550/arxiv.2003.10132},
    Note = {preprint only},
    Year = {2020},
}
$ bibdeskparser export tests/Refs/refs.bib Wilhelm2003.10132 --minimal \
    --preprint article
@article{Wilhelm2003.10132,
    Author = {Wilhelm, Frank K. and Kirchhoff, Susanna and Machnes, Shai and Wittler, Nicolas and Sugny, Dominique},
    Title = {An introduction into optimal control for quantum technologies},
    Journal = {arXiv:2003.10132},
    Url = {https://doi.org/10.48550/arxiv.2003.10132},
    Note = {preprint only},
    Year = {2020},
}
```

For a preprint on a non-arXiv archive, the structured forms also
emit the `archive` field, so that REVTeX's eprint link points at the
right server (see [the `archive` field](preprints-archive-field)).
The [`render`](cli-render) command shows the preprint reference in
the journal position, hyperlinked, with the status note appended:

```console
$ bibdeskparser render tests/Refs/refs.bib TuriniciHAL00640217
G. Turinici. [*Quantum control*](https://hal.science/hal-00640217). [HAL:hal-00640217](https://hal.science/hal-00640217) (2012), lecture notes.
```

When a preprint gets published, update the entry in place: make
it an `@article`, replace the pseudo-journal with the real journal
(an `@string` macro, see [above](howto-string-macros)), add the
`volume`, `pages`, and published `doi`, and remove (or update) the
status `note`. The retained `eprint`/`archiveprefix` fields automatically
start rendering and exporting as the "published, with preprint"
link.

Then generate the key the published article should have
(`bibdeskparser rekey`).

Conversely, [`add_preprint`](howto-add-preprint) fills in the
`eprint` field for already-published entries, so that readers behind
a paywall get a link to the free copy.

## How to import BibTeX entries from a publisher or another library

{py:meth}`Library.import_bibtex <bibdeskparser.library.Library.import_bibtex>`
runs any BibTeX snippet -- a publisher's "export citation" download, or
entries from another `.bib` file -- through the same sanitization and
adds the entries:

```python
bib.import_bibtex(text)   # text: BibTeX for one or more entries
bib.save()
```

On the command line, `import` reads from a file, stdin, or a URL
({ref}`CLI reference <cli-import>`):

<!-- notest -->
```console
$ bibdeskparser import tests/Refs/refs.bib entries.bib
$ pbpaste | bibdeskparser import tests/Refs/refs.bib --stdin
$ bibdeskparser import tests/Refs/refs.bib --url https://example.com/refs.bib
```

Since [`export`](cli-export) writes exactly the kind of snippet that
`import` accepts (including the `@string` definitions), this also
moves entries between libraries:

```console
$ bibdeskparser create other.bib
$ bibdeskparser export tests/Refs/refs.bib Tannor2007 \
    | bibdeskparser import other.bib --stdin
Tannor2007
```

If anything about a snippet is not acceptable (an undefined macro, an
entry whose DOI is already present, ...), the whole import is
rejected with a list of all problems and the library is left
untouched.

## How to edit an entry in your text editor

{py:meth}`Library.edit <bibdeskparser.library.Library.edit>` opens one
or more entries in `$EDITOR` as bibtex text and merges back whatever you save:

```python
bib.edit("GoerzQ2022")                          # a single entry
bib.edit("GrondPRA2009a", "GrondPRA2009b", editor="vim")  # several
```

## How to render a bibliography in a specific citation format

{py:meth}`Library.render <bibdeskparser.library.Library.render>`
produces a formatted citation string for one or more citation keys; pass `format="markdown"`
(default), `"tex"`, or `"html"`. When rendering several entries, `style`
controls their layout: `"default"`, `"paragraphs"`, `"numbered list"`,
or `"itemized list"`.

```python
>>> bib = Library("tests/Refs/refs.bib")
>>> print(bib.render("Evans1983", format="html"))
L. C. Evans. <a href="https://math.berkeley.edu/~evans/control.course.pdf"><i>An Introduction to Mathematical Optimal Control Theory</i></a> (1983). Lecture Notes, University of California, Berkeley.
>>> print(bib.render("Tannor2007", format="tex"))
D. J. Tannor. \href{https://uscibooks.aip.org/books/introduction-to-quantum-mechanics-a-time-dependent-perspective/}{\textit{Introduction to Quantum Mechanics: A Time-Dependent Perspective}}. University Science Books, Sausalito, California (2007).
>>> print(
...     bib.render(
...         "GrondPRA2009a", "GrondPRA2009b", style="numbered list"
...     )
... )
1. J. Grond, J. Schmiedmayer and U. Hohenester. [*Optimizing number squeezing when splitting a mesoscopic condensate*](https://link.aps.org/doi/10.1103/PhysRevA.79.021603). [Phys. Rev. A **79**, p. 021603](https://doi.org/10.1103/physreva.79.021603) (2009), [arXiv:0806.3877](https://arxiv.org/abs/0806.3877).
2. J. Grond, G. von Winckel, J. Schmiedmayer and U. Hohenester. [*Optimal control of number squeezing in trapped Bose-Einstein condensates*](https://link.aps.org/doi/10.1103/PhysRevA.80.053625). [Phys. Rev. A **80**, p. 053625](https://doi.org/10.1103/physreva.80.053625) (2009), [arXiv:0908.1634](https://arxiv.org/abs/0908.1634).

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
$ bibdeskparser export GoerzQ2022 \
    | sed 's/Semi-Automatic/Semiautomatic/' \
    | bibdeskparser edit GoerzQ2022 --stdin
```

The `@string` macro definitions round-trip the same way, from
`strings --bib` into `edit_strings --stdin`. Invalid edited text (an
unparseable block, a reference to an undefined macro) exits with code 1
and the list of problems on stderr, leaving the `.bib` file untouched.

## How to export a minimal BibTeX file for LaTeX

{py:meth}`Library.export <bibdeskparser.library.Library.export>` writes
selected entries as plain bibtex text, stripped of BibDesk-only fields; use
`fields="minimal"` to further restrict each entry to a small,
per-entry-type whitelist of citation-relevant fields (dropping things
like `abstract` and `annote`), and `outfile=` to write straight to a
file. The `@string` definitions referenced by the exported entries
are included, so the file is self-contained (pass
`expand_strings=True` to instead replace each reference by the
macro's value and omit the definitions).

Note how the entries' `abstract` and `keywords`, and the `article`
entry's linked file, are all dropped (the `eprint` fields are kept:
they render as a "published, with preprint" link under styles like
REVTeX, and are ignored by classic styles; see [](preprints)):

```python
>>> bib.export(
...     "GrondPRA2009a", "Evans1983", fields="minimal", outfile="paper.bib"
... )
>>> print(Path("paper.bib").read_text())
@string{pra = {Phys. Rev. A}}
<BLANKLINE>
@article{GrondPRA2009a,
    Author = {Grond, Julian and Schmiedmayer, J\"org and Hohenester, Ulrich},
    Title = {Optimizing number squeezing when splitting a mesoscopic condensate},
    Journal = pra,
    Year = {2009},
    Doi = {10.1103/physreva.79.021603},
    Pages = {021603},
    Volume = {79},
    Eprint = {0806.3877},
    Archiveprefix = {arXiv},
}
<BLANKLINE>
@unpublished{Evans1983,
    Author = {Evans, Lawrence C.},
    Title = {An Introduction to Mathematical Optimal Control Theory},
    Year = {1983},
}
<BLANKLINE>

```
