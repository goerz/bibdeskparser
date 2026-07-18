# BibDeskParser

[![Source code on Github](https://img.shields.io/badge/goerz-bibdeskparser-blue.svg?logo=github)][Github]
[![PyPI](https://img.shields.io/pypi/v/bibdeskparser)](https://pypi.python.org/pypi/bibdeskparser)
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

Making the bibliographic database accessible to AI coding agents is an
explicit goal of the project: the [`bibdeskparser` command-line
tool][cli] mirrors the public Python API, so any agent that can run
shell commands can inspect and edit a BibDesk library, with no
dedicated integration and no server to keep running. See [How to give
an AI coding agent access to your library][howto-ai].

[cli]: https://goerz.github.io/bibdeskparser/cli.html
[howto-ai]: https://goerz.github.io/bibdeskparser/howto.html#how-to-give-an-ai-coding-agent-access-to-your-library


## Installation

To install the latest released version of BibDeskParser:

```
pip install bibdeskparser
```

If you use [uv](https://docs.astral.sh/uv/), add BibDeskParser as a
dependency of your project with

```
uv add bibdeskparser
```

or install the `bibdeskparser` [command-line tool][cli] on your `PATH`,
independently of any project, with

```
uv tool install bibdeskparser
```

> **Tip:** If you use the command-line tool frequently, consider creating a
> shorter symlink for `bibdeskparser`, e.g. `bib`, and set up a config file,
> with a `default_bib_file` so that you can write
> `bib import 10.22331/q-2022-12-07-871`.


To install the latest development version from [Github][]:

```
pip install git+https://github.com/goerz/bibdeskparser.git@master#egg=bibdeskparser
```


## Usage

`Library` loads an existing `.bib` file and behaves like a dict of
citation key to `Entry`. The examples below use the example database
shipped in this repository at `tests/Refs/refs.bib`; substitute the
path to your own library.

```python
>>> from bibdeskparser import Library
>>> bib = Library("tests/Refs/refs.bib")
>>> len(bib)
61
>>> entry = bib["GoerzQ2022"]
>>> print(entry["title"])
Quantum Optimal Control via Semi-Automatic Differentiation
>>> print(entry.author[0].last[0])
Goerz
>>> entry.files  # linked PDF attachment, relative to the .bib file
['GoerzQ2022.pdf']

```

Full-text search and rendering a formatted citation:

```python
>>> [e.key for e in bib.search("tractor atom interferometry")]
['RaithelQST2022']
>>> print(bib.render("RaithelQST2022"))
G. Raithel, A. Duspayev, B. Dash, *et al.* *Principles of tractor atom interferometry*. [Quantum Sci. Technol. **8**, p. 014001](https://doi.org/10.1088/2058-9565/ac9429) (2022), [arXiv:2207.09023](https://arxiv.org/abs/2207.09023).

```

Any change is written back with `save()`, preserving BibDesk's file
format byte-for-byte for everything that was not touched:

```python
>>> entry["note"] = "Implemented in the QuantumControl.jl framework."
>>> bib.groups["To Read"] = ("BrifNJP2010", "KochEPJQT2022")
>>> bib["KochEPJQT2022"].groups
('To Read',)
>>> bib.save()

```

A new `.bib` file can also be created from scratch, with `Library()`
in Python or `bibdeskparser create` on the command line.


## Development

The project uses [uv](https://docs.astral.sh/uv/) to manage the development environment and [`make`](https://www.gnu.org/software/make/) as a task runner. After cloning the repository, run

```
make develop
```

to create a virtual environment with all development dependencies. Run `make help` for an overview of available targets, and see [CONTRIBUTING.md][] for full contributing guidelines.

To put the `bibdeskparser` [command-line tool][cli] on your `PATH` as an *editable* install that links back to your working copy — so changes to the source take effect without reinstalling — run

```
make install
```

Use `make uninstall` to remove it again.

[BibDesk]: https://bibdesk.sourceforge.io
[BibTeX]: https://en.wikipedia.org/wiki/BibTeX
[BibtexParser]: https://bibtexparser.readthedocs.io/en/main/
[Github]: https://github.com/goerz/bibdeskparser
[CONTRIBUTING.md]: https://github.com/goerz/bibdeskparser/blob/master/CONTRIBUTING.md
