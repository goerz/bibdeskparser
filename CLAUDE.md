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

Before the 1.0 release, backwards compatibility is not a concern. The API should be optimized for simplicity and maintainability, and any breaking change that facilitates that should be encouraged.

## Conventions

- Line length 79.
- Docstrings are MyST Markdown (not reStructuredText), rendered on the auto-generated API page. Use fenced ` ```python ` blocks for doctests.
- In the documentation, don't over-format. Use bold only for rubrics (a standalone label on its own line, like the `**Options**` rubric on the CLI reference page), never as a paragraph lead-in, a list-item lead-in ("Bold term: explanation"), or anywhere inside a paragraph.
- Public-API minimality, the per-symbol `__all__`/`__private__` rule, and which symbols stay private are documented in CONTRIBUTING.md (Documentation); don't restate them here. One point not covered there: `render`/`export`/`edit` are `Library`-only methods (not on `Entry`), since they operate on citation keys and, for `export`/`edit`, need the library's `@string` macros to produce self-contained output.
- Docstrings are user-facing documentation (rendered by autodoc2); move internal implementation rationale a user doesn't need into a `#` code comment instead of the docstring. Never reference this project's own development history, prior prototypes, or reference implementations in docstrings or docs — describe current behavior directly and self-containedly.
- The public `Library` API is mirrored by the `bibdeskparser` command-line tool (`src/bibdeskparser/cli.py`): whenever a public `Library` method/property is added, removed, renamed, or changes its signature/behavior, update the corresponding CLI subcommand in the same change, along with its tests (`tests/test_cli.py`) and the CLI reference page (`docs/sources/cli.md`). Subcommands are named after the `Library` methods (snake_case); mapping-view operations are exposed as `set_group`/`delete_group`/`set_string`/`delete_string`/`show`/`keys`/`delete`; `Library.import_bibtex` (named around the `import` keyword) is exposed as `import`; data-output commands take `--json`.
- Making the bibliographic database accessible to AI coding agents via the CLI is a project goal. Keep the `--help` output (top-level and per-command) informative enough that an agent can use the tool from `--help` alone, without external documentation. Maintain the clear distinction between read-only commands and commands that modify the `.bib` file: the top-level help enumerates the read-only commands and states that all others write in place — keep that enumeration in sync when adding or changing subcommands, and phrase each command's own help so its read-only or read-write nature is apparent.
- Both CLI doc surfaces (`cli.py` `--help` docstrings and `docs/sources/cli.md`) use a terse reference style: a short description, then (for a command whose options do more than `--json`) an `**Options**` rubric with one `- \`--flag\` -- effect` bullet per option, then the examples. Render every enumeration (`check` audits, `search` match levels, JSON fields) as an itemized list, not prose. State current behavior concisely; don't spell out rationale or edge cases that a later change can break.
- `Entry` never holds a reference back to its owning `Library` (no `Entry._library`/`Entry._owner` backref), and `Entry.key` is read-only for this reason (renaming an attached entry is a `Library`-only operation, via `Library.rekey`). The `Library` → `Entry` relationship is one-way: `Library` pushes updates into an `Entry` when needed (e.g. `entry._groups = ...`), but `Entry` never calls back into `Library`. If a new feature seems to require such a backref, change which object owns the mutation (typically: add the method to `Library`) instead of adding the reference.

See @CONTRIBUTING.md, but do not make commits or pull requests until specifically asked to do so.

When a commit is requested, its message must describe the change in a self-contained way and must not reference the issue it addresses — no `#N` references and no `Closes #N` line. The issue reference and any discussion of how the change relates to the issue belong in a separate PR message instead; draft it in `./pr_message.md`, without hard-wrapping (GitHub-flavored markdown preserves line breaks, unlike the hard-wrapped commit message body). It should have a "Closes #N" in the last line. A PR that is not in response to an issue needs a separate PR message only if it has multiple commits; for a single commit, GitHub turns the commit message into the PR message automatically.

When creating issues, the issue text must be GitHub-flavored markdown without hard-wrapping.

When asked a design/architecture question (e.g. "wouldn't it make sense if...", "is this a bug?", "should X work differently?"), answer with a recommendation and the relevant tradeoffs — do not implement any change until explicitly told to proceed.
