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

Use markdown syntax (GitHub Flavored Markdown) in the commit message. In particular, use inline code (backticks) for any snippet of text that refers to code.

Testing
-------

BibDeskParser uses [pytest](https://docs.pytest.org/en/latest/); we aim for [test coverage](https://codecov.io/gh/goerz/bibdeskparser) above 90%.

~~~ console
make test          # run the full suite
make test-lowest   # run against the lowest supported Python and dependencies
~~~

`make test` runs on the highest installed Python compatible with the project (currently 3.14); override with e.g. `make PYTHON=3.11 test`. Supported versions are Python 3.10 through 3.14.

Tests live in the `tests` subfolder, in `test_*.py` files with `test_*` functions. In addition, [doctests](https://docs.python.org/3/library/doctest.html) are collected from every docstring and from documentation files (`*.rst` and `*.md`, including `README.md`). Write doctests inside fenced ` ```python ` blocks.

Two `conftest.py` files configure the suite via [pytest fixtures](https://docs.pytest.org/en/stable/how-to/doctest.html#the-doctest-namespace-fixture). The one at the repository root isolates every test from a developer's personal configuration, and `src/conftest.py` injects the `bibdeskparser` package into the [doctest namespace](https://docs.pytest.org/en/stable/how-to/doctest.html) so doctests can use it without an explicit import. Extend the latter's autouse fixture to make more names available to every doctest.

The command-line examples in the documentation are tested as well. The doctest collector only executes ` ```python ` blocks; the ` ```console ` blocks of the how-to page (`docs/sources/howto.md`) and the CLI-reference page (`docs/sources/cli.md`) are instead executed by `tests/test_doc_console.py`. That harness extracts every `$ bibdeskparser ...` command, replays it through click's `CliRunner` in a temporary directory holding a fresh copy of `tests/Refs` (and `tests/test_cli_fail_checks`), and compares the output shown in the documentation against the actual output with doctest semantics, so `...` in the shown output matches any text. A failure names the page and line of the offending command. A `console` example on these pages is therefore a doctest, and is written under the following contract:

- The example operates on the example database at the relative path `tests/Refs/refs.bib`, and no `bibdeskparser.toml` is in effect. An example that depends on configuration (e.g. `rekey` without an explicit `--format-spec`) cannot run and must be excluded (see below).
- On the how-to page, all blocks run in order, in one shared sandbox (like the Python doctests of a single file), so an example may rely on the effects of earlier blocks. On the CLI-reference page, every block runs in isolation, in a fresh sandbox, so each example must be self-contained; in particular, it cannot delete or rename something that only an example in another block created.
- The harness understands a small shell subset: `$ ` prompts, backslash continuations, trailing `#` comments, `<< 'EOF'` heredocs, one level of `$(...)` command substitution, and pipelines in which every stage is a `bibdeskparser` invocation. Any other shell syntax fails the test; extend the harness if a new example needs it.
- Commands that need network access (`add`, `add_abstract`, `add_preprint`, `import --url`), would open an interactive editor (`edit`/`edit_strings` without `--stdin`), or pipe through other programs (`pbpaste`, `sed`) are skipped automatically, and their shown output goes unverified, so double-check it by hand. Later blocks on the how-to page must not depend on the effects of a skipped command.
- A command with no output shown below it is only required to succeed; what it actually prints is not compared (in particular, it is *not* required to print nothing). The `check` command may exit with code 1, since reporting problems is its purpose.
- An HTML comment `<!-- notest -->` on the line directly above a fence excludes that block; the comment is invisible in the rendered documentation. Use it for purely illustrative examples, e.g. ones referencing files that do not exist outside the reader's setting.

The pages under test are listed in `PAGES` at the top of `tests/test_doc_console.py`; a new documentation page with `console` examples must be registered there.

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

Every public name (one not starting with `_`) in a module must be listed in either `__all__` or `__private__`; `autodoc2` only renders `__all__` members. Keep the public API surface minimal: expose only what a *user* of the library needs (currently just `Library`, `Entry`, `ValueString`, `MacroString`, and `StaleFileError`, all re-exported from the top-level `bibdeskparser` package). In particular:

- Don't add a standalone public function for something already reachable as an `Entry`/`Library` method (e.g. the citation-rendering, export, and `$EDITOR`-editing logic lives in private free functions in `render.py`/`exporting.py`/`editing.py`, used only internally by the corresponding methods).
- Don't make a validation/normalization helper public just because it's used internally (e.g. `is_valid_macro_name`/`normalize_macro_name` in `macros.py` stay private, since `Entry`/`Library` already apply them automatically and surface a clear `ValueError` on invalid input).
- Don't make a supporting data type or helper class public just because a public property's value is derived from it, if the property already presents that data in a simpler public form (e.g. `library.py`'s `GroupInfo` namedtuple and `bdskfile.py`'s `BibDeskFile` class stay private -- `Library.groups`/`Entry.files` are the public surface, and document the derived data/behavior directly in their own docstrings rather than relying on a separately-documented type).

The bar for a new public symbol is a concrete task a user cannot otherwise accomplish, not "this might be handy."

All submodules are excluded from documentation generation (`autodoc2_skip_module_regexes` in `docs/sources/conf.py`), so every public symbol — regardless of which module it's actually defined in — is documented exactly once, on the single top-level `bibdeskparser` API page; `autodoc2_hidden_objects` additionally hides single-underscore members of otherwise-public classes (e.g. `Entry._touch`). When adding a new public symbol, re-export it from `src/bibdeskparser/__init__.py`'s `__all__` — don't rely on its own module page, since none exists.

Build the docs locally with:

~~~ console
make docs
~~~


Changelog
---------

User-facing changes are tracked in [`CHANGELOG.md`](https://github.com/goerz/bibdeskparser/blob/master/CHANGELOG.md), which follows the [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format. Whenever you make a user-facing change — in a pull request or a direct commit, add a bullet under the `## [Unreleased]` heading at the top of the file, with an inline category prefix (`Added:`, `Changed:`, `Deprecated:`, `Removed:`, `Fixed:`, or `Security:`):

~~~ markdown
## [Unreleased]

* Added: `Entry.foo` method for frobnicating entries [[#12]]
* Fixed: crash when parsing an empty `@string` macro [[#15], [#16]]
~~~

Link the relevant issue and pull request with a reference-style label `[[#N]]` (listing the issue before the pull request that closes it). You only need to write the `[[#N]]` marker in the bullet; run `make changelog` to fill in the matching link definition at the bottom of the file (it queries the GitHub API to record whether `#N` is an issue or a pull request, so it needs network access). Skip changelog entries for changes that are not user-facing: CI, dependency bumps, formatting, typo fixes, and internal-only refactoring (a leading underscore, e.g. `_helper`, marks a name as internal).

Validate the file with:

~~~ console
make check-changelog   # verify every reference has a link definition (no network)
make changelog         # additionally add any missing [#N] link definitions
~~~

`make check-changelog` runs as part of `make lint` and in CI. It is purely textual and makes no network calls; it does not verify that the links actually resolve or that the issue-vs-pull-request category is correct, so double-check those manually.

You never edit the release headings or version links by hand: `make release` transforms the changelog automatically. For the release commit it renames `## [Unreleased]` to `## [vX.Y.Z] - YYYY-MM-DD` and updates the version links at the bottom (pointing `[Unreleased]` at `…/compare/vX.Y.Z..HEAD` and adding `[vX.Y.Z]: …/releases/tag/vX.Y.Z`), opening the file in your editor first so you can review and refine the release notes. The tagged release commit therefore contains no `## [Unreleased]` section; a fresh empty one is added back in the immediately following `+dev` version-bump commit that opens the next development cycle. The signed git tag and the GitHub release for the version reuse that section's notes verbatim, so the release notes never have to be retyped.


Versioning
----------

Releases follow [Semantic Versioning](https://semver.org) (`major.minor.patch`) and version numbers must be compatible with [PEP 440](https://peps.python.org/pep-0440/). Pre-releases use suffixes such as `-dev1` or `-rc1`; documentation-only fixes may use a `.postN` release.

Between releases, `__version__` on `master` carries a `+dev` local-version suffix (or a `-dev` pre-release suffix for the next planned release); the `+dev` suffix must never appear in a PyPI release. The current version is available as `bibdeskparser.__version__`.

Make a release with:

~~~ console
make release
~~~

This applies the versioning conventions automatically. Releases are tagged in git with a `v` prefix (e.g. `v1.0.0`), making them available at <https://github.com/goerz/bibdeskparser/releases>.
