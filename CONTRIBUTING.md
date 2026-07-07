Contributing
============

Contributions are welcome and greatly appreciated! Every little bit helps, and credit is always given.

Everyone interacting in the BibDeskParser code base, issue tracker, and communication channels is expected to follow the [PyPA Code of Conduct](https://www.pypa.io/en/latest/code-of-conduct/).

Report Bugs and Submit Feedback
-------------------------------

Report bugs and request features at <https://github.com/goerz/bibdeskparser/issues>.

When reporting a bug, please include:

-   Your operating system name and version.
-   Any details about your local setup relevant to troubleshooting.
-   Detailed steps to reproduce the bug, ideally a minimal but complete script.
-   All error messages in full, as plain text (attach long output as a file).

When proposing a feature, explain how it would work and keep the scope as narrow as possible. Remember that this is a volunteer-driven project.

Development Setup
-----------------

The project uses [uv](https://docs.astral.sh/uv/) to manage the development environment and [`make`](https://www.gnu.org/software/make/) as a task runner. Install both; uv downloads and manages the required Python interpreters for you.

Clone the repository and run:

~~~ console
make help     # list available targets
make develop  # create the virtual environment with all dev dependencies
~~~

`make develop` sets up a virtual environment with all development dependencies and an editable install of the package. `uv run` (used by every `make` target) syncs the environment automatically, so you rarely need to call `make develop` directly.

To set a debugger breakpoint, use Python's built-in `breakpoint()`. The development environment includes [ipdb](https://github.com/gotcha/ipdb); activate it by setting the environment variable:

~~~ console
export PYTHONBREAKPOINT=ipdb.set_trace
~~~

Pull Request Guidelines
-----------------------

Before submitting a pull request:

1.  Add tests for any new functionality.
2.  Update the documentation for any changed behavior.
3.  Check <https://github.com/goerz/bibdeskparser/actions> and make sure the tests pass for all supported Python versions.

Follow [Aaron Meurer's Git Workflow Notes](https://www.asmeurer.com/git-workflow/): fork the repo, add your fork as a remote, create a topic branch, commit your changes, push to your fork, and open a pull request against the `master` branch.

Branching Model
---------------

Development happens directly on the `master` branch, and releases are tags on `master`. Every commit on `master` *should* pass all tests and be well-documented, so that `git bisect` stays effective. For any non-trivial change, work on a topic branch instead; topic-branch commits have no such restrictions.

~~~ shell
git checkout -b 1-title-of-issue   # branch named after issue #1
git push -u origin 1-title-of-issue # push to trigger CI
~~~

Commit early and often, and feel free to rewrite history on topic branches by force-pushing (`git commit --amend`, `git rebase -i`, `--fixup`/`--autosquash`). Clean up the commit history before merging. If a topic branch is long-lived, periodically rebase it on `master` rather than merging `master` into it. Coordinate with collaborators before rewriting shared history.

Merge a finished topic branch back with an explicit merge commit, then delete it:

~~~ shell
git checkout master
git merge --no-ff 1-title-of-issue
git push origin master
git push --delete origin 1-title-of-issue
git branch -D 1-title-of-issue
~~~

Commit Messages
---------------

Write a short imperative subject line (50 chars or less) that completes the sentence "If applied, this commit will …", followed by a blank line and an optional body wrapped at 72 characters. Reference issues as e.g. `#1`, and close them with a `Closes #1` line (see [closing issues using keywords](https://help.github.com/articles/closing-issues-using-keywords/)).

Testing
-------

BibDeskParser uses [pytest](https://docs.pytest.org/en/latest/); we aim for [test coverage](https://codecov.io/gh/goerz/bibdeskparser) above 90%.

~~~ console
make test          # run the full suite
make test-lowest   # run against the lowest supported Python and dependencies
~~~

`make test` runs on the highest installed Python compatible with the project (currently 3.14); override with e.g. `make PYTHON=3.11 test`. Supported versions are Python 3.10 through 3.14.

Tests live in the `tests` subfolder, in `test_*.py` files with `test_*` functions. In addition, [doctests](https://docs.python.org/3/library/doctest.html) are collected from every docstring and from documentation files (`*.rst` and `*.md`, including `README.md`). Write doctests inside fenced ` ```python ` blocks.

Code Style
----------

All code must comply with [PEP 8](https://www.python.org/dev/peps/pep-0008/) and the [Black code style](https://github.com/psf/black), with a line length of 79. Imports are sorted with [isort](https://pycqa.github.io/isort/) per the `pyproject.toml` configuration.

~~~ console
make black        # apply Black formatting (make black-check to only check)
make isort        # sort imports (make isort-check to only check)
make lint         # run black-check, isort-check, flake8, and pylint
~~~

Style is enforced by the test suite and by [pre-commit](https://pre-commit.com) git hooks; install them with `make pre-commit`. The [flake8](https://flake8.pycqa.org) and [pylint](https://pylint.pycqa.org) checks (`make flake8`, `make pylint`) are guidelines only and do not require a perfect score.

Documentation
-------------

The documentation is generated with [Sphinx](https://www.sphinx-doc.org/) and written in [MyST Markdown](https://myst-parser.readthedocs.io/). Docstrings are also MyST Markdown and are rendered on the auto-generated API page by [autodoc2](https://sphinx-autodoc2.readthedocs.io/); math may be written in LaTeX syntax using `$…$`. Structure content along the four [Diátaxis](https://diataxis.fr) categories: a **Tutorial** (a linear, learning-oriented walkthrough for a newcomer), **How-to guides** (short, task-oriented recipes that assume basic familiarity), **Explanation** (background/conceptual material — why the BibDesk `.bib` format works the way it does, and how `bibdeskparser` handles each feature), and **Reference** (the auto-generated API page). Don't mix categories within one page (e.g. don't bury conceptual background inside a how-to recipe).

Every public name (one not starting with `_`) in a module must be listed in either `__all__` or `__private__`; `autodoc2` only renders `__all__` members. Keep the public API surface minimal: expose only what a *user* of the library needs (currently just `Library`, `Entry`, `Value`, and `StaleFileError`, all re-exported from the top-level `bibdeskparser` package). In particular:

- Don't add a standalone public function for something already reachable as an `Entry`/`Library` method (e.g. the citation-rendering, export, and `$EDITOR`-editing logic lives in private free functions in `render.py`/`exporting.py`/`editing.py`, used only internally by the corresponding methods).
- Don't make a validation/normalization helper public just because it's used internally (e.g. `is_valid_macro_name`/`normalize_macro_name` in `macros.py` stay private, since `Entry`/`Library` already apply them automatically and surface a clear `ValueError` on invalid input).
- Don't make a supporting data type or helper class public just because a public property's value is derived from it, if the property already presents that data in a simpler public form (e.g. `library.py`'s `GroupInfo` namedtuple and `bdskfile.py`'s `BibDeskFile` class stay private -- `Library.groups`/`Entry.files` are the public surface, and document the derived data/behavior directly in their own docstrings rather than relying on a separately-documented type).

The bar for a new public symbol is a concrete task a user cannot otherwise accomplish, not "this might be handy."

All submodules are excluded from documentation generation (`autodoc2_skip_module_regexes` in `docs/sources/conf.py`), so every public symbol — regardless of which module it's actually defined in — is documented exactly once, on the single top-level `bibdeskparser` API page; `autodoc2_hidden_objects` additionally hides single-underscore members of otherwise-public classes (e.g. `Entry._touch`). When adding a new public symbol, re-export it from `src/bibdeskparser/__init__.py`'s `__all__` — don't rely on its own module page, since none exists.

Build the docs locally with:

~~~ console
make docs
~~~

Versioning
----------

Releases follow [Semantic Versioning](https://semver.org) (`major.minor.patch`) and version numbers must be compatible with [PEP 440](https://peps.python.org/pep-0440/). Pre-releases use suffixes such as `-dev1` or `-rc1`; documentation-only fixes may use a `.postN` release.

Between releases, `__version__` on `master` carries a `+dev` local-version suffix (or a `-dev` pre-release suffix for the next planned release); the `+dev` suffix must never appear in a PyPI release. The current version is available as `bibdeskparser.__version__`.

Make a release with:

~~~ console
make release
~~~

This applies the versioning conventions automatically. Releases are tagged in git with a `v` prefix (e.g. `v1.0.0`), making them available at <https://github.com/goerz/bibdeskparser/releases>.
