# BibDeskParser

[![Source code on Github](https://img.shields.io/badge/goerz-bibdeskparser-blue.svg?logo=github)][Github]
[![PyPI](https://img.shields.io/pypi/v/bibdeskparser.svg)](https://pypi.python.org/pypi/bibdeskparser)
[![Documentation](https://img.shields.io/badge/docs-gh--pages-blue.svg)][docs]
[![Docs](https://github.com/goerz/bibdeskparser/actions/workflows/docs.yml/badge.svg?branch=master)](https://github.com/goerz/bibdeskparser/actions/workflows/docs.yml)
[![Tests](https://github.com/goerz/bibdeskparser/actions/workflows/test.yml/badge.svg?branch=master)](https://github.com/goerz/bibdeskparser/actions/workflows/test.yml)
[![Coverage](https://codecov.io/gh/goerz/bibdeskparser/branch/master/graph/badge.svg)](https://codecov.io/gh/goerz/bibdeskparser)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

BibDeskParser reads and writes [BibDesk][]
`.bib` files exactly as BibDesk itself produces them: the header
comment, linked files and URLs, `@string` macros, and static groups all
round-trip byte-for-byte. The API centers on two classes: `Library`, a
dict-like mapping of citation key to `Entry`, and `Entry`, a single
bibliography record.

Development of BibDeskParser happens on [Github][].

You can read the full documentation [online][docs]. See the
[page on BibDesk's `.bib` format][bibdesk-format] for details on how
BibDesk's special `.bib` features are handled, and the
[how-to guides][howto] for short recipes covering specific tasks.

[docs]: https://goerz.github.io/bibdeskparser/
[bibdesk-format]: https://goerz.github.io/bibdeskparser/bibdesk_format.html
[howto]: https://goerz.github.io/bibdeskparser/howto.html

## Introduction

[BibDesk][] is a bibliography manager for macOS that stores
its database library as a standard [BibTeX][] `.bib` file, but adds
its own conventions on top of plain BibTeX -- tracking linked
file attachments (macOS-specific), recording user-defined groups, custom
support for `@string` macros and keyword fields, and more.

These extended features are stored in custom fields of individual entries, and
in comments in the `.bib` file. A generic BibTeX library like [BibtexParser][]
is not aware of these BibDesk-specific features and thus provides no direct
access to the stored data, and may even corrupt it on a round trip.
BibDeskParser exists so you can read, script, and edit your BibDesk
library directly in Python -- for batch edits, automation, or
integration with other tools. It provides a simplified API on top
of the [BibtexParser][] library.


## Installation

To install the latest released version of BibDeskParser:

```
pip install bibdeskparser
```

or, if you use [uv](https://docs.astral.sh/uv/):

```
uv add bibdeskparser
```


To install the latest development version from [Github][]:

```
pip install git+https://github.com/goerz/bibdeskparser.git@master#egg=bibdeskparser
```


## Usage

```python
>>> import tempfile
>>> from pathlib import Path
>>> from bibdeskparser import Entry, Library
>>> tmpdir = tempfile.TemporaryDirectory()
>>> bib_path = Path(tmpdir.name) / "references.bib"
>>> bib = Library()
>>> bib["Smith2020"] = Entry(
...     "article",
...     "Smith2020",
...     fields={
...         "title": "A Title",
...         "author": "Smith, John and Doe, Jane",
...         "journal": "J. Test",
...         "year": "2020",
...     },
... )
>>> bib.save(bib_path)

>>> bib = Library(bib_path)
>>> entry = bib["Smith2020"]
>>> print(entry["title"])
A Title
>>> print(entry.author[0].last[0])  # 'Smith'
Smith

>>> entry["title"] = "A Better Title"
>>> bib.groups["Favorites"] = ("Smith2020",)  # BibDesk static group
>>> entry.groups
('Favorites',)
>>> bib.save()
>>> tmpdir.cleanup()

```


## Development

The project uses [uv](https://docs.astral.sh/uv/) to manage the development environment and [`make`](https://www.gnu.org/software/make/) as a task runner. After cloning the repository, run

```
make develop
```

to create a virtual environment with all development dependencies. Run `make help` for an overview of available targets, and see [CONTRIBUTING.md][] for full contributing guidelines.

[BibDesk]: https://bibdesk.sourceforge.io
[BibTeX]: https://en.wikipedia.org/wiki/BibTeX
[BibtexParser]: https://bibtexparser.readthedocs.io/en/main/
[Github]: https://github.com/goerz/bibdeskparser
[CONTRIBUTING.md]: https://github.com/goerz/bibdeskparser/blob/master/CONTRIBUTING.md
