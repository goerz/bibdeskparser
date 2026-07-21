# Test libraries for the `check` command

The `.bib` files in this folder back the tests for the `check` CLI
command in `tests/test_cli.py`. In `problems.bib`, one entry per
audit fails, named after its problem (`MissingDoi2026`,
`LiteralJournal2026`, `UndefinedMacro2026`, `BadNames2026`,
`Duplicate2026`), the `@string` macro `unusedjrnl` is never
referenced, and `EmptyDoi2026` and `Preprint2026` demonstrate the
passing exemptions; `broken_block.bib` contains a block that fails
to parse. Since `check` is read-only, the files can also be used
directly to get a feel for how the command behaves:

~~~console
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib --json
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib MissingDoi2026
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib EmptyDoi2026 Preprint2026
$ bibdeskparser check tests/test_cli_fail_checks/broken_block.bib Good2026
$ bibdeskparser check tests/Refs/refs.bib  # a clean library: PASS
~~~
