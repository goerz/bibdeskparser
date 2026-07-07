# CLAUDE.md

Parser for [BibDesk](https://bibdesk.sourceforge.io) database files. Python package `bibdeskparser` in `src/`.

Leverages [BibtexParser](https://github.com/sciunto-org/python-bibtexparser) ([docs](https://bibtexparser.readthedocs.io/en/main/)) via _composition_ (not inheritance).

## Development

The environment is managed by `uv`; the `Makefile` wraps common tasks (`make help`).

- `make test` — run the suite (pytest via `uv run`, includes doctests in modules, `*.rst`, and `*.md`; stops at first failure)
- `make test-lowest` — run against the lowest supported Python (3.10) and dependencies
- `make lint` — `black-check`, `isort-check`, `flake8`, `pylint`, `check-changelog`
- `make black` / `make isort` — auto-format
- `make check-changelog` — validate `CHANGELOG.md` links (textual, no network; also in CI)
- `make changelog` — validate and fill in missing `[#N]` link targets (uses the GitHub API)
- `make docs` — build Sphinx HTML docs

Run a single test with `uv run pytest tests/test_bibdeskparser.py::test_name`.

Keep `CHANGELOG.md` up to date with every user-facing change — see the "Changelog" section of @CONTRIBUTING.md for the conventions. Breaking changes must include user instructions on how to adapt to the change as part of the changelog.

## Conventions

- Line length 79.
- Docstrings are **MyST Markdown** (not reStructuredText), rendered on the auto-generated API page. Use fenced ` ```python ` blocks for doctests.
- Every public name (not starting with `_`) in a module must be listed in either `__all__` or `__private__`.
- The public API is deliberately minimal: only names re-exported from `src/bibdeskparser/__init__.py` (`Library`, `Entry`, `Value`, `StaleFileError`) are public; everything else — including internal modules (`texmap`, `macros`, `header`, `middleware`, `writer`, `groups`, `names`, `bdskfile`) and standalone functions whose functionality is already reachable via a `Library` method (e.g. `render_entry`/`export_entries`/`edit_entries`/`edit_strings`, which back `Library.render`/`.export`/`.edit`/`.edit_strings`) — is `__private__`. `render`/`export`/`edit` are `Library`-only methods (not on `Entry`), since they operate on one or more citation keys and, for `export`/`edit`, need the library's `@string` macros to produce self-contained output. This includes plain data-holding types with no behavior of their own (e.g. `library.py`'s `GroupInfo` namedtuple, returned by `library.groups[name]` but documented only inline in `Library.groups`' own docstring) and helper classes fully mediated by a public property (e.g. `bdskfile.py`'s `BibDeskFile`, used only internally by `Entry.files`). Validation helpers like `is_valid_macro_name`/`normalize_macro_name` stay private too: `Entry`/`Library` already apply them automatically and raise a clear error on invalid input, so a user is never *required* to call them directly. Before adding a new public symbol, or a standalone function/class alongside an equivalent `Entry`/`Library` method or property, check whether a user genuinely needs to call/construct it directly — not just whether it's convenient to expose.
- Docstrings are user-facing documentation (rendered by autodoc2); move internal implementation rationale a user doesn't need into a `#` code comment instead of the docstring. Never reference this project's own development history, prior prototypes, or reference implementations in docstrings or docs — describe current behavior directly and self-containedly.
- `Entry` never holds a reference back to its owning `Library` (no `Entry._library`/`Entry._owner` backref), and `Entry.key` is read-only for this reason (renaming an attached entry is a `Library`-only operation, via `Library.rekey`). The `Library` → `Entry` relationship is one-way: `Library` pushes updates into an `Entry` when needed (e.g. `entry._groups = ...`), but `Entry` never calls back into `Library`. If a new feature seems to require such a backref, change which object owns the mutation (typically: add the method to `Library`) instead of adding the reference.

See @CONTRIBUTING.md, but do not make commits or pull requests until specifically asked to do so.

When asked a design/architecture question (e.g. "wouldn't it make sense if...", "is this a bug?", "should X work differently?"), answer with a recommendation and the relevant tradeoffs — do not implement any change until explicitly told to proceed.
