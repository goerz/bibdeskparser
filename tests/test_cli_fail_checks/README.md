# Test libraries for the `check` command

The `.bib` files in this folder back the tests for the `check` CLI
command in `tests/test_cli.py`. In `problems.bib`, one entry per
audit fails, named after its problem (`MissingDoi2026`,
`LiteralJournal2026`, `UndefinedMacro2026` (an undefined `journal`
macro), `UndefinedField2026` (`publisher = elsevir`, an undefined
macro in a field with no audit of its own), `BadNames2026`,
`MissingRequired2026` (an `@article` with no `year`),
`UnknownType2026` (a `@bogustype` entry), `BadYear2026` (a `year` of
`August, 2026`), `LiteralMonth2026` (`month = {June}` written out
instead of the macro), `BadMonthMacro2026` (`month = sept`, which is
neither one of the twelve month macros nor defined, so it fails both
the month and the undefined-macro audit), `UnencodedURL2026` (a `url`
field with raw non-ASCII characters, flagged by the url-encoding
audit), `Duplicate2026`), the
`@string` macro `unusedjrnl` is never referenced, and `EmptyDoi2026`
and `Preprint2026` demonstrate the passing exemptions;
`broken_block.bib` contains a block that fails
to parse. `deadfiles.bib` passes every audit *except* the opt-in
`--files` audit: `Dead2020` links a missing file, and `Case2020`
links `case2020.pdf` while the on-disk file (committed alongside) is
`Case2020.pdf`, differing only in case. `keyformat.bib` passes every
audit *except* the opt-in `--key-format` audit (against
`%p1%c{journal}0%Y%u0`): `Deviation2015` deviates from the format, as
does `Handpicked`, an entry with no `journal` whose key was chosen
by hand instead of being the shortened `Venueless2015` that the format
generates for it. `ConformingPRA2015`, the colliding pair
`CollidingPRA2015`/`CollidingPRA2015a`, the preprint
`Preprint2205.15044`, and `Shortened2015` (an entry with no
`journal`, keyed exactly as the format renders it without the venue)
conform; the two journal-less entries are `@misc`, the one type with
no required fields, so that the required-field audit leaves them
alone. Since `check` is read-only, the files can also be used
directly to get a feel for how the command behaves:

~~~console
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib --json
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib MissingDoi2026
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib EmptyDoi2026 Preprint2026
$ bibdeskparser check tests/test_cli_fail_checks/broken_block.bib Good2026
$ bibdeskparser check tests/test_cli_fail_checks/deadfiles.bib --files
$ bibdeskparser check tests/test_cli_fail_checks/keyformat.bib --format-spec "%p1%c{journal}0%Y%u0"
$ bibdeskparser check tests/Refs/refs.bib  # a clean library: PASS
~~~
