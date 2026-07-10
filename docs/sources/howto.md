# How-to Guides

These short, task-oriented recipes assume you are already familiar with the
basics of `bibdeskparser` (see the [introduction](readme)); for background on
*why* things work this way, see [BibDesk's `.bib` Format](bibdesk_format).

## How to manage file attachments

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
...     bib.add_file("Smith2020", libdir / "Smith2020.pdf")
...     bib.add_file("Smith2020", "notes.pdf")  # library-relative
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
updates *every* entry that links it, each with a fresh bookmark:

```python
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # no macOS bookmark support here
...     bib.rename_file("Smith2020", "notes.pdf", "Smith2020-notes.pdf")
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
