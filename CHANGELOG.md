# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

* Added: a `bibdeskparser` command-line tool that exposes the public `Library` API as subcommands (`keys`, `show`, `render`, `export`, `add_to_group`, `set_string`, `edit`, ...). Data-output commands accept `--json`; the `.bib` file argument may be omitted when `default_bib_file` is configured. [[#4]]
* Added: a `default_bib_file` option in `bibdeskparser.toml`, naming the `.bib` file the command-line tool operates on when none is given. [[#4]]
* Added: `MacroString`, mirroring `ValueString`, to force a field value to be stored as a bare `@string` macro reference. Both are subtypes of `str`.
* Added: `Entry.add_url`, `Entry.replace_url`, `Entry.remove_url` and the corresponding `Library.add_url`, `Library.replace_url`, `Library.remove_url` methods for managing an entry's linked URLs.
* Added: validation and normalization of `Entry` types: constructing or assigning an entry type now lowercases it and rejects unrecognized types with a `ValueError`. Loading a `.bib` file still never validates.
* Added: validation of the `author`/`editor` fields: assigning an unparseable value raises `ValueError`.
* Added: a `UserWarning` when assigning a field that is not appropriate for the entry type.
* Added: a "Bib Entry Types" reference page documenting the supported entry types and fields.
* Added: support for a `bibdeskparser.toml` configuration file (searched for next to the `.bib` file and in the XDG config location), with `verify_types` and `verify_fields` flags to disable entry-type validation and field-appropriateness warnings, and `types`/`fields` tables to define custom entry types and fields or extend the built-in ones. The flags are also exposed as the `Library.verify_types`, `Library.verify_fields`, and `Library.config_file` class attributes.
* Added: a "Configuration" reference page documenting the `bibdeskparser.toml` file.
* Changed: `Value` has been renamed to `ValueString` (**breaking**: rename `Value` to `ValueString` in your code). Values returned by the `Entry` dict interface are now `ValueString` (for literal/braced values) or `MacroString` (for bare `@string` macro references) instances; both are `str` subclasses and compare as plain strings.
* Changed: `Entry.urls` is now a read-only tuple (**breaking**: replace assignment to `entry.urls` with the new `add_url`/`replace_url`/`remove_url` methods).
* Changed: the `keywords` field is now readable through the `Entry` dict interface (indexing an entry by `keywords` returns the comma-joined string). It is still not writable that way, and the `Entry.keywords` property remains read-only; keywords are edited only through the owning `Library`.
* Removed: the public `Entry.dirty` property (**breaking**: there is no public replacement; it was an internal detail).

## [v0.1.0] - 2026-07-07

Initial release.

[Unreleased]: https://github.com/goerz/bibdeskparser/compare/v0.1.0..HEAD
[v0.1.0]: https://github.com/goerz/bibdeskparser/releases/tag/v0.1.0
[#4]: https://github.com/goerz/bibdeskparser/pull/4
