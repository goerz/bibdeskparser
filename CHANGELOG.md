# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

* Added: CLI commands for working with the fields of a single entry: `fields KEY` lists the defined field names, `get_field KEY FIELDNAME` prints one field value, `set_field KEY FIELDNAME VALUE` sets a field (with `--literal`/`--macro` to force the value to be stored as literal text or as a bare `@string` macro reference), and `delete_field KEY FIELDNAME` removes a field. These correspond to the `dict` interface of `Entry` (iteration, indexing, assignment, and `del`). [[#13]]
* Added: an `author KEY` and an `editor KEY` CLI command, printing an entry's authors/editors as structured names (last-name-first; with `--json`, as objects with `first`/`von`/`last`/`jr` name parts), corresponding to the `Entry.author` and `Entry.editor` properties. [[#13]]
* Added: a `set_type KEY TYPE` CLI command, changing an entry's type (corresponding to assigning `Entry.entry_type`). [[#13]]
* Added: the `groups` and `keywords` CLI commands accept an optional entry `KEY`, listing the groups/keywords of that single entry (corresponding to the `Entry.groups` and `Entry.keywords` properties) instead of the library-wide mapping. [[#13]]
* Added: filter options on the `keys` CLI command: `--type TYPE` keeps only entries of the given type(s), and `--has FIELD`/`--missing FIELD`/`--empty FIELD` keep only entries where `FIELD` is defined with a non-empty value, not defined at all, or defined but empty, respectively (all repeatable). [[#13]]
* Fixed: the CLI's top-level `--help` now shows a complete, un-truncated one-line summary for every subcommand (previously long summaries were cut off with `...`). [[#11]]
* Fixed: `Library.render` (and the `render` CLI command) now expands `@string` macros in the rendered citation, so a field like `journal = pra` shows its defined value (e.g. `Phys. Rev. A`) rather than the bare macro name. [[#12]]
* Changed: bump the PyPI `Development Status` classifier from `2 - Pre-Alpha` to `3 - Alpha`.

## [v0.2.0] - 2026-07-13

* Added: automatic filing of file attachments, mirroring BibDesk's AutoFile feature. `Library.rename_file` without a `new_filename` moves an attachment into the configured auto-file location and renames it according to a file-name format in BibDesk's format-specifier language (the recommended format is `%f{Cite Key}%u0%e`, naming each file after its entry's citation key while keeping the real extension); `Library.add_file` files newly attached files the same way when auto-filing is in effect (`file_automatically = true` in the configuration, or explicit `format_spec`/`auto_file_location` arguments, with `auto_file_location=""` forcing a plain attach). A file whose name already matches the format is left in place (re-filing is idempotent), and the format's required `%u`/`%U`/`%n` specifier disambiguates against existing files on disk. The `rename_file` and `add_file` CLI commands gain the corresponding options. [[#10]]
* Added: an `auto_file` table in `bibdeskparser.toml`, with `format_spec` (a single format or a per-type table), `location` (the directory files are moved into, relative to the `.bib` file or absolute), `lowercase`, `clean`, and `file_automatically` keys, exposed as `Library.config.auto_file`. [[#10]]
* Added: the file-name context of the format-specifier language: the `%l`/`%L`/`%e`/`%E` original-file-name specifiers, `/` as a directory separator, and file-name oriented sanitization (only `:` is invalid; spaces and non-ASCII text survive). [[#10]]
* Changed: `Library.eval_format_spec` also evaluates file-name formats, via a new `filename` keyword argument that selects the file-name dialect (any non-`None` value, including `""`, does so) and supplies the original-name specifiers `%l`/`%L`/`%e`/`%E`. The `filename` need not exist or be one of the entry's attachments; the format is evaluated purely, without touching the filesystem. If `filename` is an attachment's current path that already matches the format, it evaluates to itself. The `eval_format_spec` CLI command gains a matching `--filename` option. [[#10]]
* Changed: `Library.add_file` and `Library.rename_file` now return the stored library-relative path of the attachment (previously `None`), `rename_file`'s `new_filename` argument is optional (omitting it triggers auto-filing), missing parent directories of a rename target are now created automatically, and a rename may move a file across filesystems. To adapt: existing code needs no changes unless it relied on `rename_file` failing for a target in a nonexistent directory; the return values can be ignored. [[#10]]
* Added: automatic citation-key generation. Calling `Library.rekey` without a `new_key` generates the key from an auto-key format in BibDesk's format-specifier language (e.g. `%a1%c{journal}0%Y%u0`), taken from the new `auto_key` table of `bibdeskparser.toml` or from the new `format_spec` keyword argument. A key that already matches the format is kept unchanged, and a `%u`/`%U`/`%n` specifier in the format disambiguates collisions, like in BibDesk. The `rekey` CLI command correspondingly makes `NEW_KEY` optional, adds a `--format-spec PATTERN` option, and prints the generated key. [[#9]]
* Added: `Library.eval_format_spec` and a matching read-only `eval_format_spec` CLI command, evaluating an auto-key format for an entry and returning the key it yields, without renaming anything. A key that already matches the format evaluates to itself, so this identifies the entries whose citation key does not follow a given format. [[#9]]
* Added: per-type auto-key formats. The `auto_key` table's `format_spec` may be a table mapping each entry type to its own format (with `""` as the fallback for unlisted types), so a mixed-type library can name `journal` for articles, `booktitle` for conference papers, and so on. The `auto_key` settings are also available and settable as `Library.config.auto_key` (with `format_spec`, `lowercase`, and `clean` attributes). [[#9]]
* Added: an `initials` table in `bibdeskparser.toml`, defining per-field exceptions (e.g. journal or conference-proceedings initials) to the acronym that the `%c` format specifier builds from a field value. [[#9]]
* Added: a "Format Specifiers" reference page documenting the format-specifier language. [[#9]]
* Changed: `Library.rekey` now returns the resulting citation key (previously `None`). [[#9]]
* Added: a "How to give an AI coding agent access to your library" how-to guide, describing the lightweight path for letting a shell-capable agent (such as Claude Code) drive the `bibdeskparser` CLI, and expanded the top-level `--help` text to orient such callers (read-only vs. mutating commands, `--json`, exit codes). [[#8]]
* Added: `Library.edit` and `Library.edit_strings` accept a function for `editor`, as an alternative to an editor command string. The function receives the path of the temporary file and must edit it in place; validation problems then raise a `ValueError` instead of prompting interactively. [[#8]]
* Added: a `--stdin` option on the `edit` and `edit_strings` CLI commands, reading the full edited text from standard input instead of opening an editor, and a `--bib` option on `strings`, printing the `@string` definitions as re-parseable `@string{name = {value}}` lines. Together with `export`, these allow non-interactive (e.g., scripted or AI-agent) editing via pipes: `export KEY... | ... | edit KEY... --stdin` and `strings --bib | ... | edit_strings --stdin`. [[#8]]
* Changed: the `edit` and `edit_strings` CLI commands now fail immediately with a usage error when invoked without a terminal on standard input and without `--stdin` or an explicit `--editor`, instead of blocking on `$EDITOR`. Non-interactive callers must pass `--stdin` (piping in the edited text) or `--editor` with a command that needs no terminal. [[#8]]
* Fixed: newly added entries, new `@string` macros, and a newly synthesized static-groups `@comment` block were appended at the very end of the `.bib` file, after BibDesk's group `@comment` blocks. They are now written at their canonical position: macros in the alphabetically sorted `@string` run before the first entry, entries before the group `@comment` blocks, and the static-groups block before the smart-groups block, matching the layout BibDesk itself writes.
* Added: `Library.search` and a corresponding `search` CLI subcommand: find entries matching a query, ranked best match first. Matching runs against the stored field values (bare `@string` macro names intact), the decoded Unicode values, and macro expansions, with accent-insensitive, word-overlap, fuzzy, and regex match levels, optionally limited to specific fields. [[#5]]
* Added: a `bibdeskparser` command-line tool that exposes the public `Library` API as subcommands (`keys`, `show`, `render`, `export`, `add_to_group`, `set_string`, `edit`, ...). Data-output commands accept `--json`; the `.bib` file argument may be omitted when `default_bib_file` is configured. [[#4]]
* Added: a `default_bib_file` option in `bibdeskparser.toml`, naming the `.bib` file the command-line tool operates on when none is given. [[#4]]
* Added: the `BIBDESKPARSER_CONFIG` environment variable, naming the user-level `bibdeskparser.toml` in place of the XDG location. Setting it to an empty value disables the user-level configuration entirely. [[#7]]
* Added: `MacroString`, mirroring `ValueString`, to force a field value to be stored as a bare `@string` macro reference. Both are subtypes of `str`.
* Added: `Entry.add_url`, `Entry.replace_url`, `Entry.remove_url` and the corresponding `Library.add_url`, `Library.replace_url`, `Library.remove_url` methods for managing an entry's linked URLs.
* Added: validation and normalization of `Entry` types: constructing or assigning an entry type now lowercases it and rejects unrecognized types with a `ValueError`. Loading a `.bib` file still never validates.
* Added: validation of the `author`/`editor` fields: assigning an unparseable value raises `ValueError`.
* Added: a `UserWarning` when assigning a field that is not appropriate for the entry type.
* Added: a "Bib Entry Types" reference page documenting the supported entry types and fields.
* Added: support for a `bibdeskparser.toml` configuration file (searched for next to the `.bib` file and in the XDG config location), with `verify_types` and `verify_fields` flags to disable entry-type validation and field-appropriateness warnings, and `types`/`fields` tables to define custom entry types and fields or extend the built-in ones. The active configuration is exposed as the `Library.config` class attribute (equally readable from a library instance as `bib.config`), whose attributes -- `verify_types`, `verify_fields`, `config_file`, `auto_key`, and others -- can be assigned for in-process overrides that never write back to the configuration file.
* Added: a "Configuration" reference page documenting the `bibdeskparser.toml` file.
* Changed: `Value` has been renamed to `ValueString` (**breaking**: rename `Value` to `ValueString` in your code). Values returned by the `Entry` dict interface are now `ValueString` (for literal/braced values) or `MacroString` (for bare `@string` macro references) instances; both are `str` subclasses and compare as plain strings.
* Changed: `Entry.urls` is now a read-only tuple (**breaking**: replace assignment to `entry.urls` with the new `add_url`/`replace_url`/`remove_url` methods).
* Changed: the `keywords` field is now readable through the `Entry` dict interface (indexing an entry by `keywords` returns the comma-joined string). It is still not writable that way, and the `Entry.keywords` property remains read-only; keywords are edited only through the owning `Library`.
* Removed: the public `Entry.dirty` property (**breaking**: there is no public replacement; it was an internal detail).

## [v0.1.0] - 2026-07-07

Initial release.

[Unreleased]: https://github.com/goerz/bibdeskparser/compare/v0.2.0..HEAD
[v0.2.0]: https://github.com/goerz/bibdeskparser/releases/tag/v0.2.0
[v0.1.0]: https://github.com/goerz/bibdeskparser/releases/tag/v0.1.0
[#4]: https://github.com/goerz/bibdeskparser/pull/4
[#5]: https://github.com/goerz/bibdeskparser/pull/5
[#7]: https://github.com/goerz/bibdeskparser/pull/7
[#8]: https://github.com/goerz/bibdeskparser/pull/8
[#9]: https://github.com/goerz/bibdeskparser/pull/9
[#10]: https://github.com/goerz/bibdeskparser/pull/10
[#11]: https://github.com/goerz/bibdeskparser/pull/11
[#12]: https://github.com/goerz/bibdeskparser/pull/12
[#13]: https://github.com/goerz/bibdeskparser/pull/13
