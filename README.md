# BibDeskParser

[![Source code on Github](https://img.shields.io/badge/goerz-bibdeskparser-blue.svg?logo=github)][Github]
[![PyPI](https://img.shields.io/pypi/v/bibdeskparser.svg)](https://pypi.python.org/pypi/bibdeskparser)
[![Documentation](https://img.shields.io/badge/docs-gh--pages-blue.svg)][docs]
[![Docs](https://github.com/goerz/bibdeskparser/workflows/Docs/badge.svg?branch=master)](https://github.com/goerz/bibdeskparser/actions?query=workflow%3ADocs)
[![Tests](https://github.com/goerz/bibdeskparser/workflows/Tests/badge.svg?branch=master)](https://github.com/goerz/bibdeskparser/actions?query=workflow%3ATests)
[![Coverage](https://codecov.io/gh/goerz/bibdeskparser/branch/master/graph/badge.svg)](https://codecov.io/gh/goerz/bibdeskparser)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

Parser for Bibdesk database files

Development of BibDeskParser happens on [Github][].

You can read the full documentation [online][docs].

[docs]: https://goerz.github.io/bibdeskparser/


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

To use BibDeskParser in a Python project:

``` python
import bibdeskparser
```

## Development

The project uses [uv](https://docs.astral.sh/uv/) to manage the development environment and [`make`](https://www.gnu.org/software/make/) as a task runner. After cloning the repository, run

```
make develop
```

to create a virtual environment with all development dependencies. Run `make help` for an overview of available targets, and see [CONTRIBUTING.md][] for full contributing guidelines.

To set a debugger breakpoint, use Python's built-in `breakpoint()`. The development environment includes [ipdb](https://github.com/gotcha/ipdb); activate it by setting the environment variable:

```
export PYTHONBREAKPOINT=ipdb.set_trace
```

[Github]: https://github.com/goerz/bibdeskparser
[CONTRIBUTING.md]: https://github.com/goerz/bibdeskparser/blob/master/CONTRIBUTING.md
