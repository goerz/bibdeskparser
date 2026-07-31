(cli)=

# Command Line Interface

The `bibdeskparser` command-line tool exposes the public
{class}`~bibdeskparser.Library` API as subcommands, so that a BibDesk
`.bib` database can be inspected and modified from the shell without
writing Python code. The `bibdeskparser` script is installed together
with the package (e.g. via `pip install bibdeskparser`); to install
just the command-line tool on your `PATH`, without adding the package
to a Python environment, use
[`uv tool install bibdeskparser`](https://docs.astral.sh/uv/guides/tools/).

The command-line tool is also the project's intended integration
surface for AI coding agents: an agent that can run shell commands can
work with a BibDesk library through one-shot `bibdeskparser`
invocations, guided by the `--help` output alone (see
{ref}`howto-ai`).

## Usage

<!-- notest -->
```console
$ bibdeskparser <command> [BIBFILE] <args> <options>
```

Run `bibdeskparser --help` for the full list of commands,
`bibdeskparser <command> --help` for the arguments and options of a
specific command, and `bibdeskparser --version` for the installed
version. `bibdeskparser --usage` (or `bibdeskparser` with no command)
prints a short usage summary listing just the command names, without
the full `--help` output.

Every command operates on a single `.bib` file, given as the first
argument after the command name. An argument counts as the `BIBFILE`
exactly if it does not start with `-` and ends in `.bib`
(case-insensitive). When the `BIBFILE` is omitted, the file named by
the `default_bib_file` option of a discovered `bibdeskparser.toml` is
used instead; the configuration file is discovered relative to the
current working directory, falling back to the XDG location (see
[Configuration](configuration)). With neither a `BIBFILE` argument nor
a configured `default_bib_file`, the command fails with a usage error.
The `.bib` file must already exist for every command except
[`create`](cli-create), which starts a new, empty library.

The commands are named after the corresponding
{class}`~bibdeskparser.Library` methods and properties (`import`
corresponds to {py:meth}`~bibdeskparser.Library.import_bibtex`, since
`import` is a Python keyword). The `dict`-like operations of the
Python API map to commands as follows: `set_group`/`delete_group`
assign to and delete from {py:attr}`~bibdeskparser.Library.groups`,
`set_string`/`delete_string` assign to and delete from
{py:attr}`~bibdeskparser.Library.strings`,
`set_info`/`delete_info` assign to and delete from
{py:attr}`~bibdeskparser.Library.info`, `show`/`keys`/`delete`
index, iterate over, and `del` on the library itself, and
`fields`/`get_field`/`set_field`/`delete_field` do the same on a
single {class}`~bibdeskparser.Entry`. The commands that read an
entry's derived data (`author`, `editor`, `files`, `urls`, `groups`,
`keywords`) correspond to the same-named
{class}`~bibdeskparser.Entry` properties (`groups --index` /
`keywords --index` read the inverse
{py:attr}`~bibdeskparser.Library.groups` /
{py:attr}`~bibdeskparser.Library.keywords` mappings), and `set_type`
assigns {py:attr}`~bibdeskparser.Entry.entry_type`. The one command
with no API counterpart is [`config_path`](cli-config-path), which
reports the discovered configuration file.

Read-only commands print their result to stdout; so does `export`,
which only writes a file when asked to, with `--outfile` or
`--update` (the latter rewrites a previously exported file, never the
library itself). Mutating commands
load the library, apply the change, save the file in place, and print
nothing on success. The exceptions that do print:
[`rekey`](cli-rekey) without `NEW_KEY` and
[`rename_file`](cli-rename-file) without `NEW` print the generated key
or file path, as does [`add_file`](cli-add-file) when it auto-files;
[`import`](cli-import) and [`add`](cli-add) print the citation keys of
the added entries (`add --dry-run` prints the fetched entry without
modifying the file); and [`add_abstract`](cli-add-abstract),
[`add_preprint`](cli-add-preprint), and [`add_doi`](cli-add-doi) print
a per-key report of the fetched abstracts, arXiv identifiers, and DOIs
(with `--dry-run`, without modifying the file).

## JSON output

Every command that prints structured data (all read-only commands
except `render` and `export`) accepts a `--json` flag to print the
data as JSON instead of human-readable text, for consumption by other
tools:

```console
$ bibdeskparser show tests/Refs/refs.bib GoerzA2023 --field doi,volume --json
{
  "GoerzA2023": {
    "doi": "10.3390/atoms11020036",
    "volume": "11"
  }
}
```

## Errors and exit codes

A successful command exits with code 0. Invalid command-line usage
(unknown command, missing argument, no `BIBFILE` and no
`default_bib_file`) exits with code 2. Any error reported by the
underlying library (an unknown citation key or group name, an invalid
value, a missing file, or a {exc}`~bibdeskparser.StaleFileError` when
the `.bib` file changed on disk while being edited) prints a one-line
`Error: <message>` on stderr and exits with code 1, without a
traceback. The [`check`](cli-check) command additionally exits with
code 1, after printing its report, when any audit finds a problem.

## Creating a library

(cli-create)=

### `create`

Create `BIBFILE` as a new, empty library: a `.bib` file containing
only the standard BibDesk header comment. Corresponds to saving a
from-scratch {class}`~bibdeskparser.Library`
(`Library().save(path)`). Unlike for every other command, the file
must *not* already exist; an existing file is never overwritten.

```console
$ bibdeskparser create new.bib
```

All other commands require the `.bib` file to exist, so a new library
is started with `create` and then filled with entries:

<!-- notest -->
```console
$ bibdeskparser create new.bib
$ bibdeskparser import new.bib --file entries.bib
```

With a `default_bib_file` configured in `bibdeskparser.toml` (see
[Configuration](configuration)), `bibdeskparser create` without an
argument creates that file, bootstrapping the configured library.

## Inspecting

(cli-keys)=

### `keys`

List citation keys, one per line. See
{py:meth}`~bibdeskparser.Library.keys`. Without options, every entry
is listed; otherwise an entry is listed when it matches one of the
`--type` values (if any) and satisfies every other filter. Types and
field names match case-insensitively, group names case-sensitively.

```console
$ bibdeskparser keys tests/Refs/refs.bib --type book
Shapiro2012
BrumerShapiro2003
Tannor2007
MATLAB:2014
```

**Options**

- `--type TYPE` -- keep only entries of this type (repeatable; an
  entry matches any listed type).
- `--has FIELD` -- keep only entries where FIELD has a non-empty value
  (repeatable).
- `--missing FIELD` -- keep only entries where FIELD is missing
  (repeatable). An empty field counts as missing, since BibDesk
  deletes empty fields on save (see [Empty fields](bibdesk-empty-fields)).
- `--group NAME`/`--not-group NAME` -- keep only entries that are, or
  are not, members of the [static group](bibdesk-static-groups) NAME
  (repeatable). An unknown group name is an error.
- `--with-files`/`--without-files` -- keep only entries that have at
  least one attachment, or none. Default: no attachment filter.
- `--json` -- print the keys as a JSON array of strings.

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing eprint
WinckelIP2008
```

```console
$ bibdeskparser keys tests/Refs/refs.bib --type book --group Diploma
Tannor2007
```

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --without-files
ImamogluPRE2015
Luc-KoenigEPJD2004
SauvagePRXQ2020
KatrukhaNC2017
```

### `duplicate_keys`

List citation keys that occur more than once, one per line. See
{py:attr}`~bibdeskparser.Library.duplicate_keys`. With `--json`: an
array of strings.

```console
$ bibdeskparser duplicate_keys tests/Refs/with_duplicates.bib
GoerzSPP2019
```

(cli-check)=

### `check [KEY...]`

Run the standing audits and report every problem found, one per line,
followed by a `PASS`/`FAIL` summary line; the exit code is 0 if all
audits pass and 1 otherwise. A read-only pass/fail gate for the
library, e.g. after a batch of edits.

```console
$ bibdeskparser check tests/Refs/refs.bib
PASS (61 entries checked)
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib
Duplicate2026: duplicate citation key
MissingDoi2026: missing doi
EmptyDoi2026: missing doi
EmptyDoi2026: empty field 'doi' (BibDesk deletes empty fields on save)
LiteralJournal2026: journal is the literal string 'Some Journal', not an @string macro reference
UndefinedMacro2026: journal references undefined @string macro 'nosuchjournal'
UndefinedField2026: publisher references undefined @string macro 'elsevir'
BadNames2026: author does not parse as names: Cannot split the following name `Doe, John, Jr, X, Y` into parts: Too many commas
MissingRequired2026: missing required field 'year' for entry type 'article'
UnknownType2026: unrecognized entry type 'bogustype'
BadYear2026: year 'August, 2026' does not read as a four-digit year (%Y gives '0')
LiteralMonth2026: month is the literal string 'June', not one of the twelve standard month macros (jan ... dec)
BadMonthMacro2026: month references the macro 'sept', not one of the twelve standard month macros (jan ... dec)
BadMonthMacro2026: month references undefined @string macro 'sept'
UnencodedURL2026: url contains non-ASCII characters: 'https://example.com/münchen' (use 'https://example.com/m%C3%BCnchen')
unused @string macro 'unusedjrnl'
FAIL (16 problems, 14 entries checked)
```

The audits:

- the file parses cleanly (no skipped blocks);
- no citation key occurs more than once;
- every entry has a recognized [entry type](bib-entry-types) and the
  fields that type requires;
- no field is defined but empty (BibDesk deletes empty fields on save;
  see [Empty fields](bibdesk-empty-fields));
- every `article` that is not a [preprint](preprints) has a `doi`, or
  is in the `doi` [known-missing group](config-known-missing);
- no entry is in a known-missing group for a field it has;
- every `journal` references an `@string` macro, not a literal (a
  preprint pseudo-journal like `arXiv:2205.15044` is allowed);
- no field references an undefined `@string` macro;
- every `year` reads as a four-digit year;
- every `month` is a bare reference to a standard month macro (`jan`
  ... `dec`);
- every `author` and `editor` parses as names;
- no URL-type value (a `url`-named field, or a `bdsk-url` link) holds
  raw non-ASCII characters;
- every `@string` macro is referenced by some entry.

**Options**

- `--files` -- also check that each linked attachment (`bdsk-file`
  path) resolves on disk, matching case exactly. Off by default, since
  attachments may live only on another machine.
- `--key-format` -- also check that each citation key matches its
  expected [auto-key format](config-auto-key): the arXiv format for a
  preprint-only entry, the configured `[auto_key]` format otherwise.
- `--format-spec PATTERN` -- check keys against PATTERN instead of the
  configured format. Implies `--key-format`.
- `--json` -- emit `{"passed", "entries_checked", "problems": [...]}`;
  each problem has `check` (the failing audit: `parse`,
  `duplicate_keys`, `entry_type`, `required_fields`, `doi`,
  `empty_fields`, `known_missing`, `journal`, `undefined_macro`,
  `year`, `month`, `names`, `url_encoding`, `unused_strings`, `files`,
  or `key_format`), `key` (or `null`), and `message`.

With `KEY...`, only the given entries are audited and the unused-macro
audit is skipped; an unknown key is an error.

```console
$ bibdeskparser check tests/test_cli_fail_checks/problems.bib Preprint2026
PASS (1 entry checked)
```

`--files` matches case exactly, so it also catches a link whose
spelling differs only in case from the file on disk (invisible on a
case-insensitive filesystem, broken on a case-sensitive one). It is
therefore stricter than the plain existence check behind the save-time
warning, and can FAIL a library that would be written without warning.

```console
$ bibdeskparser check tests/Refs/refs.bib --files
PASS (61 entries checked)
$ bibdeskparser check tests/test_cli_fail_checks/deadfiles.bib --files
Dead2020: linked file does not exist: 'Dead2020.pdf'
Case2020: linked file 'case2020.pdf' exists only as 'Case2020.pdf' (case mismatch)
FAIL (2 problems, 2 entries checked)
```

`--key-format` flags every key that [`rekey`](cli-rekey) without
`NEW_KEY` would regenerate differently. A key already matching the
format evaluates to itself, so a disambiguated sibling like
`CollidingPRA2015a` still conforms, and an entry lacking a field the
format references is audited against the shorter key it generates
(`Handpicked` below has no `journal`). With no usable format available,
a single message is reported rather than one failure per entry.

```console
$ bibdeskparser check tests/test_cli_fail_checks/keyformat.bib --format-spec "%p1%c{journal}0%Y%u0"
Deviation2015: does not match the citation-key format (would be 'DeviationPRA2015')
Handpicked: does not match the citation-key format (would be 'Venueless2015')
FAIL (2 problems, 7 entries checked)
```

(cli-show)=

### `show [KEY...]`

Show the data of one or more entries: a `KEY (entry_type)` heading,
the fields, and derived data (groups, keywords, files, URLs, and
dates). Corresponds to indexing the library, `lib[key]`, with field
values rendered for display. Keys come from the `KEY` arguments and/or
`--keys-from`; at least one is required.

**Options**

- `--field FIELD` -- show only these fields instead of the full record
  (repeatable and comma-separated, case-insensitive); the derived data
  is dropped, and a field not defined on an entry is omitted.
- `--no-unicode` -- show field values TeX-encoded, as stored, instead
  of as Unicode text.
- `--no-expand-strings` -- show a value that references an `@string`
  macro as the bare macro name (see [`strings`](cli-strings)) instead
  of the macro's value.
- `--keys-from FILE` -- read additional citation keys from FILE, one
  per line (`-` for standard input), so another command's output pipes
  straight in.
- `--skip-missing` -- report an unknown key on stderr and show the
  rest, instead of aborting on the first one.
- `--json` -- map each key to an object with `entry_type`, `key`,
  `fields`, `groups`, `keywords`, `files`, `urls`, `date_added`, and
  `date_modified`; with `--field`, a flat `{key: {field: value}}` map;
  and under `--no-expand-strings`, every field value becomes
  `{"macro": <name or null>, "value": <value or null>}`.

```console
$ bibdeskparser show tests/Refs/refs.bib GoerzDiploma2010
GoerzDiploma2010 (mastersthesis)
    author:   Goerz, Michael
    keywords: OCT, Quantum Gates, Ultracold Atoms
    school:   Freie Universität Berlin
    title:    Optimization of a Controlled Phasegate for Ultracold Calcium Atoms in an Optical Lattice
    type:     {Diplomarbeit}
    url:      https://michaelgoerz.net/research/diploma_thesis.pdf
    year:     2010
  groups:        My Papers
  keywords:      OCT, Quantum Gates, Ultracold Atoms
  urls:          https://michaelgoerz.net/research/diploma_thesis.pdf
  date added:    2026-07-18T07:49:28-04:00
  date modified: 2026-07-18T11:43:24-04:00
```

For example, to inspect the DOI and title of every entry that is
missing an `eprint` field, in one pipeline:

```console
$ bibdeskparser keys tests/Refs/refs.bib --missing eprint \
    | bibdeskparser show tests/Refs/refs.bib --field doi,title \
        --json --keys-from -
```

(cli-fields)=

### `fields KEY`

List the names of the fields defined on an entry, one per line.
Corresponds to iterating over an {class}`~bibdeskparser.Entry`. This
covers the normal BibTeX fields, including `keywords`, but not the
internal date and `bdsk-*` fields; use [`show`](cli-show) for a
complete view of an entry. With `--json`: an array of strings.

```console
$ bibdeskparser fields tests/Refs/refs.bib Evans1983
author
keywords
note
title
url
year
```

### `get_field KEY FIELDNAME`

Print the value of one field of an entry. Corresponds to indexing an
{class}`~bibdeskparser.Entry`, `lib[key][fieldname]`; field names are
case-insensitive. Fails for a field not defined on the entry (see
[`fields`](cli-fields)).

**Options**

- `--no-unicode` -- print the value TeX-encoded, as stored, instead of
  as Unicode text.
- `--no-expand-strings` -- print the bare `@string` macro name (see
  [`strings`](cli-strings)) instead of the macro's value.
- `--json` -- print a string; under `--no-expand-strings`, an object
  `{"macro": <name or null>, "value": <value or null>}`.

```console
$ bibdeskparser get_field tests/Refs/refs.bib GoerzJPB2011 title
The quantum speed limit of optimal controlled phasegates for trapped neutral atoms
```

### `author KEY`, `editor KEY`

Show the authors (editors) of an entry as structured names, one per
line, in last-name-first form (`von Last, Jr, First`). See
{py:attr}`~bibdeskparser.Entry.author` and
{py:attr}`~bibdeskparser.Entry.editor`. An entry without the
corresponding field prints nothing. With `--json`: an array of
objects with `first`, `von`, `last`, and `jr` keys, each an array of
name words.

```console
$ bibdeskparser author tests/Refs/refs.bib Shapiro2012
Shapiro, Moshe
Brumer, Paul
$ bibdeskparser author tests/Refs/refs.bib KochJPCM2016 --json
[
  {
    "first": [
      "Christiane",
      "P."
    ],
    "von": [],
    "last": [
      "Koch"
    ],
    "jr": []
  }
]
```

(cli-files)=

### `files [KEY...]`

List file attachments (the `bdsk-file-N` fields), in numeric order
within each entry; see {py:attr}`~bibdeskparser.Entry.files`. The
output maps each citation key to its attachments (`KEY: path, path`
per line): the given `KEY` entries (an entry with none maps to an
empty list), or every entry with at least one attachment when no `KEY`
is given.

**Options**

- `--relative` -- print each attachment as stored in the `.bib` file,
  relative to its directory, instead of as an absolute path.
- `--flat` -- print just the paths as one de-duplicated list, so
  `files --flat` is every file the library references (find the
  entries missing one with [`keys --without-files`](cli-keys)).
- `--json` -- print a `{key: [paths]}` object, or a JSON array with
  `--flat`.

```console
$ bibdeskparser files tests/Refs/refs.bib GoerzPRA2014 Shapiro2012 --relative
GoerzPRA2014: GoerzPRA2014.pdf
Shapiro2012: 
```

```console
$ bibdeskparser files tests/Refs/refs.bib --relative --json
{
  "BrifNJP2010": [
    "BrifNJP2010.pdf"
  ],
  ...
}
```

```console
$ bibdeskparser files tests/Refs/refs.bib GoerzJPB2011 --relative --flat
GoerzJPB2011.pdf
```

An unknown key is an error. Attachments are modified with
[`add_file`](cli-add-file), `replace_file`, `unlink_file`, and
[`rename_file`](cli-rename-file).

(cli-urls)=

### `urls [KEY...]`

List the URLs linked to entries (the `bdsk-url-N` fields), in numeric
order within each entry; see {py:attr}`~bibdeskparser.Entry.urls`. The
output shape matches [`files`](cli-files): each citation key maps to
its URLs (`KEY: url, url` per line), covering the given keys or every
entry with at least one linked URL when no key is given.

**Options**

- `--flat` -- print just the URLs as one de-duplicated list.
- `--json` -- print a `{key: [urls]}` object, or a JSON array with
  `--flat`.

Linked URLs are modified with `add_url`, `replace_url`, and
`remove_url`.

```console
$ bibdeskparser urls tests/Refs/refs.bib KochJPCM2016
KochJPCM2016: http://dx.doi.org/10.1088/0953-8984/28/21/213001
```

### `search QUERY`

List the keys of the entries matching `QUERY`, best match first, one
per line. See {py:meth}`~bibdeskparser.Library.search`. The query is
matched against the stored field values (bare `@string` macro names
intact), the decoded Unicode values, and macro expansions.

**Options**

- `--field FIELD` -- limit the search to this field (repeatable); the
  special name `key` matches the citation key.
- `--match LEVEL` -- set the match strictness (default `words`). The
  levels up to `fuzzy` are case-insensitive, each matching everything
  the previous one does:
  - `exact`: the query occurs verbatim as a substring.
  - `folded`: additionally ignores accents (`Schrodinger` and
    `Schroedinger` both find `Schrödinger`) and matches any letter by
    its plain ASCII spelling (`Molmer` finds `Mølmer`).
  - `words`: additionally matches when most of the query's words occur
    in a field, in any order.
  - `fuzzy`: additionally tolerates small typos; casts the widest net,
    so verify its results.
  - `regex`: the query is a regular expression ({mod}`re` semantics,
    case-sensitive unless it says `(?i)`).
- `--json` -- print the keys as a JSON array.

```console
$ bibdeskparser search tests/Refs/refs.bib "Schroedinger" --field title
WP_Schroedinger
```

(cli-groups)=

### `groups [KEY...]`

List the [static groups](bibdesk-static-groups) each entry belongs to.
The output shape matches [`files`](cli-files): each citation key maps
to its group names (see {py:attr}`~bibdeskparser.Entry.groups`),
covering the given keys or every entry in at least one group when no
key is given.

**Options**

- `--flat` -- print just the group names as one de-duplicated list.
- `--index` -- print the inverse map instead, from each static group
  to the keys it contains (see
  {py:attr}`~bibdeskparser.Library.groups`); takes no `KEY` and lists
  every group, including empty ones.
- `--json` -- print the mapping as a JSON object.

```console
$ bibdeskparser groups tests/Refs/refs.bib GoerzQ2022
GoerzQ2022: My Papers
```

```console
$ bibdeskparser groups tests/Refs/refs.bib --index
Diploma: Tannor2007, NielsenChuangCh10QEC, Evans1983, LapertPRA09
My Papers: GoerzDiploma2010, GoerzJPB2011, GoerzNJP2014, GoerzPRA2014, GoerzPhd2015, GoerzPRA2015, GoerzEPJQT2015, GoerzNPJQI2017, GoerzQST2018, GoerzSPP2019, GoerzSPIEO2021, GoerzQ2022, GoerzA2023
```

Group membership is modified with `add_to_group`, `remove_from_group`,
`set_group`, and `delete_group`.

(cli-keywords)=

### `keywords [KEY...]`

List the keywords each entry is tagged with. The output shape matches
[`files`](cli-files): each citation key maps to its keywords (see
{py:attr}`~bibdeskparser.Entry.keywords`), covering the given keys or
every tagged entry when no key is given.

**Options**

- `--flat` -- print just the keywords as one de-duplicated list.
- `--index` -- print the inverse map instead, from each keyword to the
  keys tagged with it (see
  {py:attr}`~bibdeskparser.Library.keywords`); takes no `KEY`.
- `--json` -- print the mapping as a JSON object.

```console
$ bibdeskparser keywords tests/Refs/refs.bib LapertPRA09
LapertPRA09: Filtering, OCT
```

```console
$ bibdeskparser keywords tests/Refs/refs.bib --index
OCT: BrifNJP2010, KochJPCM2016, SolaAAMOP2018, MorzhinRMS2019, ...
Coherent Control: BrifNJP2010, Shapiro2012, SolaAAMOP2018, ...
...
```

Keywords are modified with `add_to_keyword` and `remove_from_keyword`.

(cli-strings)=

### `strings`

List all `@string` macro definitions. See
{py:attr}`~bibdeskparser.Library.strings`.

**Options**

- `--bib` -- print re-parseable `@string{name = {value}}` lines,
  sorted by name: the baseline for [`edit_strings`](cli-edit-strings)
  `--stdin`. Mutually exclusive with `--json`.
- `--json` -- print an object mapping each macro name to its value.

```console
$ bibdeskparser strings tests/Refs/refs.bib
atoms = Atoms
epjd = Eur. Phys. J. D
epjqt = EPJ Quantum Technol.
...
$ bibdeskparser strings tests/Refs/refs.bib --bib
@string{atoms = {Atoms}}
@string{epjd = {Eur. Phys. J. D}}
...
```

(cli-info)=

### `info [KEY]`

Print the document info: the key/value metadata that BibDesk's
"Document Info" panel attaches to the database as a whole (see
{py:attr}`~bibdeskparser.Library.info` and the
[](bibdesk-document-info) documentation). Without `KEY`, print all
pairs, one `key = value` per line; with `KEY` (matched
case-insensitively), print just its value.

**Options**

- `--json` -- print an object mapping each key to its value (with
  `KEY`, the value as a JSON string).

```console
$ bibdeskparser info tests/Refs/refs.bib
primary_topics = Coherent Control, Numerics, OCT, Quantum Gates, Ultracold Atoms
$ bibdeskparser info tests/Refs/refs.bib primary_topics
Coherent Control, Numerics, OCT, Quantum Gates, Ultracold Atoms
```

### `timestamp`

Print the save timestamp from the file header, in ISO 8601 format (or
nothing, if the header has no timestamp). See
{py:attr}`~bibdeskparser.Library.timestamp`. With `--json`: a string
or `null`.

```console
$ bibdeskparser timestamp tests/Refs/refs.bib
2026-07-18T16:02:00-04:00
```

### `path`

Print the absolute path of the `.bib` file being operated on: the
given `BIBFILE`, or the configured `default_bib_file` when `BIBFILE`
is omitted. See {py:attr}`~bibdeskparser.Library.path`. With
`--json`: a string.

<!-- notest -->
```console
$ bibdeskparser path
/Users/mg/Refs/refs.bib
```

(cli-config)=

### `config`

Print the resolved configuration: the built-in defaults merged with
whatever a discovered `bibdeskparser.toml` sets. Where
[`config_path`](cli-config-path) reports only the file in effect,
`config` shows the effective value of every setting, including the
ones the file omits. A `BIBFILE` only fixes the config-discovery
directory (else the current directory; see
[Configuration](configuration)); `config` needs no `.bib` file and
never fails for a missing configuration file.

**Options**

- `--no-types` -- restrict the dump to the user-tunable settings,
  omitting the resolved entry-type/field data model
  (`documented_types`, `recognized_entry_types`, `universal_fields`,
  `known_fields`).
- `--json` -- print the complete state as a JSON object, unset values
  as `null`. The default output is TOML-shaped instead.

```console
$ bibdeskparser config --no-types
verify_types = true
verify_fields = true
preprint_export = "unpublished"
protected_words = []
...
[preprint_archives]
arXiv = "https://arxiv.org/abs/{id}"
...
```

(cli-config-path)=

### `config_path`

Print the absolute path of the `bibdeskparser.toml` configuration
file in effect for the `.bib` file being operated on. Discovery
checks the directory of the `.bib` file, then the file named by
`$BIBDESKPARSER_CONFIG`, then the XDG location; first found wins (see
[Configuration](configuration)). If no configuration file is found,
the command fails with an error (the built-in defaults are then in
effect). With `--json`: a string.

<!-- notest -->
```console
$ bibdeskparser config_path
/Users/mg/.config/bibdeskparser/bibdeskparser.toml
```

(cli-eval-format-spec)=

### `eval_format_spec KEY [FORMAT]`

Print the citation key (or, with `--filename`, the file name) that a
[format-specifier](format-specifiers) pattern yields for the entry at
`KEY`, via {py:meth}`~bibdeskparser.Library.eval_format_spec`. Read
only: nothing is renamed or moved. `FORMAT` defaults to the configured
`[auto_key]` format (`[auto_file]` with `--filename`). A value already
matching the format evaluates to itself, so any other output flags a
nonconforming key or name.

**Options**

- `--filename FILE` -- evaluate `FORMAT` as a file name instead, in
  the [file-name dialect](specifiers-files). `FILE` only supplies the
  original-name specifiers `%l`/`%L`/`%e`/`%E` (e.g. its extension);
  it need not exist or be attached to `KEY`. Pass an empty string to
  select the dialect when `FORMAT` uses none of those.
- `--json` -- print the result as a JSON string.

```console
$ bibdeskparser eval_format_spec tests/Refs/refs.bib LapertPRA09 \
    '%a1%c{journal}0%Y%u0'
LapertPRA2009
```

```console
$ bibdeskparser eval_format_spec tests/Refs/refs.bib Shapiro2012 \
    '%f{Cite Key}%u0%e' --filename shapiro.pdf
Shapiro2012.pdf
```

## Rendering and exporting

(cli-render)=

### `render KEY...`

Render a formatted citation for one or more entries, via
{py:meth}`~bibdeskparser.Library.render`. A
[preprint-only entry](preprints) renders its preprint reference in the
journal position, linked; any other entry's `eprint` renders as a
separate link after the journal reference.

**Options**

- `--format FORMAT` -- output format: `markdown` (default), `tex`, or
  `html`.
- `--style STYLE` -- layout of multiple citations: `default`,
  `paragraphs`, `numbered list`, or `itemized list`.

```console
$ bibdeskparser render tests/Refs/refs.bib GoerzA2023 --format tex
```

(cli-export)=

### `export [KEY...]`

Export one or more entries as self-contained BibTeX text (including
the definitions of any `@string` macros they reference), via
{py:meth}`~bibdeskparser.Library.export`. Each entry is reduced to
the fields needed to typeset a bibliography, written as Unicode text,
with `@string` references left bare. The output begins with a marker
line recording the export options (see [](bibdesk-plain-format)).
Without `--update`, the command is read-only; with `--update FILE`,
it rewrites the exported FILE in place.

**Options**

- `--no-unicode` -- export field values TeX-encoded, as written to the
  `.bib` file, instead of as Unicode text.
- `--expand-strings` -- replace `@string` references by the macro's
  value and emit no `@string` definitions (by default they are
  prepended).
- `--full` -- export every field except the date bookkeeping fields,
  with attachments and URLs as plain paths/URLs, instead of the
  minimal selection (`--minimal`, the default).
- `--field FIELD` -- export only the named fields (repeatable and
  comma-separated). Mutually exclusive with `--minimal`/`--full`, and
  always exports the stored fields.
- `--preprint FORM` -- the form a [preprint-only entry](preprints) is
  exported as, whatever its stored form: `unpublished` (structured
  `eprint` fields, with the required `note` guaranteed in minimal
  exports; the default, via the
  [`preprint_export` setting](config-preprint-export)), `misc` (the
  same structured form), `article` (the pseudo-journal form,
  hyperlinked via `url`), or `stored` (no transformation).
- `--outfile PATH` -- write to a file instead of stdout. Mutually
  exclusive with `--update`.
- `--update FILE` -- rewrite the exported FILE (which must exist and
  be plain BibTeX, not a BibDesk database), refreshing it from the
  library: the given KEYs (without KEYs: every key in FILE that the
  library knows) are freshly exported in place, KEYs not yet in FILE
  are appended, and everything else -- unknown entries, comments,
  `@string` definitions -- is kept; nothing is ever removed. The
  `--unicode`/`--expand-strings`/`--preprint` options default to the
  FILE's own recorded or detected options.
- `--no-marker` -- do not begin the output with the marker line; with
  `--update`, leave the FILE's marker state untouched.

```console
$ bibdeskparser export tests/Refs/refs.bib GoerzA2023 \
    --expand-strings --outfile out.bib
$ bibdeskparser export tests/Refs/refs.bib --update out.bib GoerzQ2022
```

## Entries

(cli-rekey)=

### `rekey OLD_KEY [NEW_KEY]`

Change the citation key of an entry from `OLD_KEY` to `NEW_KEY`, via
{py:meth}`~bibdeskparser.Library.rekey`. Without `NEW_KEY`, the key is
generated from the configured [auto-key format](config-auto-key) and
printed; a key already matching the format is kept, and a
`%u`/`%U`/`%n` specifier resolves collisions with other entries. To
preview without renaming, use
[`eval_format_spec`](cli-eval-format-spec).

**Options**

- `--format-spec PATTERN` -- generate the new key from this
  [format-specifier](format-specifiers) pattern instead of the
  configured one. Only valid without `NEW_KEY`.

```console
$ bibdeskparser rekey tests/Refs/refs.bib LapertPRA09 LapertPRA2009
```

<!-- notest -->
```console
$ bibdeskparser rekey tests/Refs/refs.bib LapertPRA09
LapertPRA2009
$ bibdeskparser rekey tests/Refs/refs.bib LapertPRA09 --format-spec '%a1:%Y%u0'
Lapert:2009
```

### `delete KEY...`

Delete one or more entries from the library. Corresponds to
`del lib[key]`.

```console
$ bibdeskparser delete tests/Refs/refs.bib WP_Schroedinger
```

### `set_type KEY TYPE`

Change the entry type of an entry, e.g. to `article`
(case-insensitive). Corresponds to assigning
{py:attr}`~bibdeskparser.Entry.entry_type`. An unrecognized `TYPE` is
rejected; custom entry types can be defined in the `types` table of
`bibdeskparser.toml` (see the [configuration](configuration)).

```console
$ bibdeskparser set_type tests/Refs/refs.bib Wilhelm2003.10132 unpublished
```

(cli-set-field)=

### `set_field KEY FIELDNAME VALUE`

Set one field of an entry, adding the field if it does not exist.
Corresponds to assigning to an {class}`~bibdeskparser.Entry`,
`lib[key][fieldname] = value`; field names are case-insensitive. Like
BibDesk, a `VALUE` that is a valid `@string` macro name is stored as a
bare macro reference. The `keywords`, date, and `bdsk-*` fields cannot
be set this way (use [`add_to_keyword`](cli-add-to-keyword),
[`add_file`](cli-add-file), `add_url`); an `author`/`editor` `VALUE`
must parse as names.

**Options**

- `--literal` -- store `VALUE` as literal text
  ({class}`~bibdeskparser.ValueString`), even if it is a valid macro
  name.
- `--macro` -- store `VALUE` as a bare macro reference
  ({class}`~bibdeskparser.MacroString`), failing if it is not a valid
  macro name.

```console
$ bibdeskparser set_field tests/Refs/refs.bib TuriniciHAL00640217 note \
    "Lecture notes for a graduate course"
```

An empty `VALUE` is an error, since BibDesk deletes empty fields on
save (see [Empty fields](bibdesk-empty-fields)): use
[`delete_field`](cli-set-field) to remove a field, or add the entry to
a [known-missing group](config-known-missing) to record a verified
absence.

### `delete_field KEY FIELDNAME`

Delete one field from an entry. Corresponds to
`del lib[key][fieldname]`; field names are case-insensitive. Fails
for a field not defined on the entry (see [`fields`](cli-fields)),
and for the `keywords`, date, and `bdsk-*` fields (use
`remove_from_keyword`, `unlink_file`, `remove_url`, etc. instead).

```console
$ bibdeskparser delete_field tests/Refs/refs.bib GoerzJPB2011 note
```

## Adding entries

(cli-import)=

### `import`

Import the entries of a BibTeX snippet into the library and print
their citation keys, via
{py:meth}`~bibdeskparser.Library.import_bibtex`. The snippet may be
anything from a single publisher-provided entry to a complete `.bib`
file (including `@string` definitions). Every entry is sanitized on
the way in (see the method for the full list): the journal becomes an
`@string` macro reference, title proper nouns are brace-protected, the
DOI is normalized, and, for articles, a page range collapses to its
first page and non-essential fields are dropped. A
[preprint-only entry](preprints) (a pseudo-journal like
`arXiv:2205.15044`, or a `misc`/`unpublished` entry with an `eprint`)
is normalized to an `@unpublished` entry with the canonical
pseudo-journal and derived `eprint`/`archiveprefix`/`doi` fields; an
unrecognized archive prefix is an error unless `--keep-journals` is
given. Citation keys are regenerated. An entry whose DOI or eprint is
already in the library is rejected, and any problem rejects the whole
import, reporting everything at once with the `.bib` file untouched.

**Options**

- `--file FILE` -- read the snippet from FILE.
- `--stdin` -- read the snippet from standard input.
- `--url URL` -- download the snippet from URL. Give exactly one of
  `--file`, `--stdin`, or `--url`.
- `--keep-keys` -- keep the incoming citation keys instead of
  regenerating them.
- `--keep-journals` -- preserve each journal as-is instead of
  converting it to an `@string` macro reference.
- `--fix-uppercase` -- repair all-uppercase names and titles found in
  some publisher data.

<!-- notest -->
```console
$ bibdeskparser import tests/Refs/refs.bib --file entries.bib
BaumgratzPRL2014
$ pbpaste | bibdeskparser import tests/Refs/refs.bib --stdin
GrapeJMR2005
$ bibdeskparser import tests/Refs/refs.bib --url https://example.com/more.bib
MotzoiPRL2009
```

A positional argument ending in `.bib` always names the library, like
every other command; give the import source with `--file` (so
`--file` is required even with a configured `default_bib_file`).

(cli-add)=

### `add QUERY...`

Fetch bibliographic data for `QUERY` from the appropriate online
source and add it as a new, sanitized entry (the same sanitization as
[`import`](cli-import)), via {py:meth}`~bibdeskparser.Library.add`,
printing its citation key. All `QUERY` arguments join into one query:

- an arXiv identifier (`2205.15044`, `quant-ph/0106057`), or any
  string containing one (e.g. an `arxiv.org` URL), is fetched from the
  arXiv API and added as a [preprint-only](preprints) `@unpublished`
  entry;
- a DOI, or a URL containing one (e.g. most publisher article pages),
  is fetched from [Crossref](https://www.crossref.org);
- anything else (free text with spaces) is a Crossref bibliographic
  search, adding the best match, so verify the result.

Requires network access; the arXiv API's rate limits are respected
automatically.

**Options**

- `--dry-run` -- print the fetched entry (as re-parseable BibTeX)
  without modifying the `.bib` file.
- `--fix-uppercase` -- repair all-uppercase names and titles in the
  fetched metadata.
- `--add-abstract` -- also store the abstract returned alongside the
  metadata (see [`add_abstract`](cli-add-abstract)).
- `--add-preprint` -- also search arXiv for a matching preprint (see
  [`add_preprint`](cli-add-preprint)), reporting to stderr; skipped
  when the entry already has an `eprint`.

The `--fix-uppercase` and `--add-*` options default to the
[`[add]` configuration](config-add), each with a negative form
(`--no-add-abstract`, ...) to override a configured `true`.

```console
$ bibdeskparser add tests/Refs/refs.bib 10.1103/PhysRevA.89.032334
MuellerPRA2014
$ bibdeskparser add tests/Refs/refs.bib https://arxiv.org/abs/1801.00862
Preskill1801.00862
$ bibdeskparser add tests/Refs/refs.bib pulser open-source pulse sequences
SilverioQ2022
```

```console
$ bibdeskparser add tests/Refs/refs.bib --dry-run 10.22331/q-2022-01-24-629
@string{quant = {Quantum}}

@article{SilverioQ2022,
...
```

## Abstracts, preprints, and DOIs

(cli-add-abstract)=

### `add_abstract KEY...`

Fetch and store missing abstracts for the given entries, via
{py:meth}`~bibdeskparser.Library.add_abstract`. For each `KEY`,
candidate abstracts are gathered from Crossref (via `doi`), the first
attached PDF's text (needs [poppler](https://poppler.freedesktop.org)'s
`pdftotext` on `PATH`), the arXiv API (via `eprint`), and Semantic
Scholar; each is cleaned to plain-unicode prose, and the best is
stored in the `abstract` field if its confidence reaches
`--min-confidence`:

- `high`: an online abstract identified by `doi`/`eprint`, or an
  unambiguous PDF extraction;
- `medium`: a single unconfirmed source;
- `low`: the PDF text and an online source disagree.

An entry that already has an abstract is skipped (see `--overwrite`).
A candidate that was not stored is reported in full, to review and
apply with [`set_field`](cli-set-field). With a
[known-missing group](config-known-missing) configured for `abstract`,
a clean search that finds nothing adds the entry to the group and
later runs skip it, while storing an abstract removes it; a search in
which any source failed never marks the entry. Requires network
access.

**Options**

- `--min-confidence LEVEL` -- lowest confidence stored automatically:
  `high` (default), `medium`, or `low`. Defaults to the
  [`[add_abstract]` configuration](config-add).
- `--overwrite` -- refetch and replace an existing abstract, and
  re-search the known-missing group members.
- `--dry-run` -- print the report without modifying the `.bib` file
  (it then says `would store`).
- `--json` -- map each key to
  `{abstract, source, confidence, note, applied}`.

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing abstract
SauvagePRXQ2020
KatrukhaNC2017
$ bibdeskparser add_abstract tests/Refs/refs.bib \
    SauvagePRXQ2020 Vecheck2022.09.09.507322
SauvagePRXQ2020: stored (crossref, high)
Vecheck2022.09.09.507322: needs review (semanticscholar, medium) [cr-miss]
    Quantum biology examines quantum effects in living cells ...
$ bibdeskparser set_field tests/Refs/refs.bib Vecheck2022.09.09.507322 \
    abstract "Quantum biology examines quantum effects in living cells ..."
```

(cli-add-preprint)=

### `add_preprint KEY...`

Find and store the matching arXiv preprint for the given entries, via
{py:meth}`~bibdeskparser.Library.add_preprint`. For each `KEY`, the
arXiv API is searched for a preprint matching the entry (by title and
first author), and, on a confident match, its identifier is stored in
the `eprint` field, along with `archiveprefix` and the primary
category (e.g. `quant-ph`) as `primaryclass`. A result is accepted
only when

- its arXiv DOI equals the entry's `doi`, or
- its title is a near-exact match, or
- a good title match is corroborated by the first author's last name.

A match postdating the entry's `year` by more than a year is only
reported unless its journal reference names that year; apply such a
candidate with `--eprint`. An entry that already has an `eprint` is
skipped (see `--overwrite`). With a
[known-missing group](config-known-missing) configured for `eprint`,
a clean search that finds no preprint adds the entry to the group and
later runs skip it, while storing an identifier removes it; a failed
search never marks the entry. Membership means "searched, none found
at the time", so re-audit the group members periodically with
`--overwrite`. Requires network access (except with `--eprint`) and
respects the arXiv API's rate limit of one request every three
seconds, so large runs take time.

**Options**

- `--eprint ID` -- store this arXiv identifier explicitly instead of
  searching (a single `KEY` only, no network access; a leading
  `arXiv:` prefix and a version suffix are stripped).
- `--overwrite` -- replace an existing `eprint`, and re-search the
  known-missing group members.
- `--dry-run` -- print the report without modifying the `.bib` file
  (it then says `would store`).
- `--json` -- map each key to
  `{eprint, match, ratio, note, applied, primaryclass}`.

Re-audit the known-missing group members like this:

```console
$ bibdeskparser add_preprint tests/Refs/refs.bib --overwrite \
    $(bibdeskparser keys tests/Refs/refs.bib --group "No Eprint")
```

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing eprint
WinckelIP2008
$ bibdeskparser add_preprint tests/Refs/refs.bib \
    WinckelIP2008 Vecheck2022.09.09.507322
WinckelIP2008: no preprint found (marked known missing in group 'No Eprint') [best-ratio=0.42]
Vecheck2022.09.09.507322: no preprint found (marked known missing in group 'No Eprint') [best-ratio=0.31]
```

The report above assumes a known-missing group declared for `eprint`
in `bibdeskparser.toml`; without one, the two lines end at the
`[best-ratio=...]` note and nothing is recorded.

(cli-add-doi)=

### `add_doi KEY...`

Find and store the DOI for the given entries, via
{py:meth}`~bibdeskparser.Library.add_doi`. For each `KEY`, the DOI is
looked up online: via the arXiv API if the entry has an `eprint` (the
recorded DOI names the published version of this paper), else via a
Crossref search by title and first author, accepted only when

- its title is a near-exact match, or
- a good title match is corroborated by the first author's last name.

A match whose year differs from the entry's `year` by more than one is
only reported; apply it with `--doi`. An amendment (erratum,
corrigendum, retraction, comment, reply) never matches a non-amendment
entry. The DOI is stored in bare lowercase form. An entry that already
has a `doi` is skipped (see `--overwrite`), as is a
[preprint-only](preprints) entry (its published version's DOI does not
belong on a preprint reference; store it with `--doi`). With a
[known-missing group](config-known-missing) configured for `doi`, a
clean lookup that finds nothing adds the entry to the group and later
runs skip it, while storing a DOI removes it; a failed lookup never
marks the entry, and membership also lets [`check`](cli-check) accept
an `article` without a `doi`. Requires network access (except with
`--doi`); an `eprint` lookup respects arXiv's rate limit of one
request every three seconds.

**Options**

- `--doi DOI` -- store this DOI explicitly instead of searching (a
  single `KEY` only, no network access; a leading `doi:` prefix or
  `https://doi.org/` resolver address is stripped).
- `--overwrite` -- replace an existing `doi`, and re-search the
  known-missing group members.
- `--dry-run` -- print the report without modifying the `.bib` file
  (it then says `would store`).
- `--json` -- map each key to `{doi, match, ratio, note, applied}`.

Re-audit the known-missing group members like this:

```console
$ bibdeskparser add_doi tests/Refs/refs.bib --overwrite \
    $(bibdeskparser keys tests/Refs/refs.bib --group "No DOI")
```

```console
$ bibdeskparser add_doi tests/Refs/refs.bib GoerzPhd2015 GoerzDiploma2010
GoerzPhd2015: no doi found (marked known missing in group 'No DOI') [best-ratio=0.55]
GoerzDiploma2010: no doi found (marked known missing in group 'No DOI') [best-ratio=0.47]
```

The report above assumes a known-missing group declared for `doi` in
`bibdeskparser.toml`; without one, the two lines end at the
`[best-ratio=...]` note and nothing is recorded.

## Groups

### `add_to_group NAME KEY...`

Add entries to the static group `NAME`, via
{py:meth}`~bibdeskparser.Library.add_to_group`.

```console
$ bibdeskparser add_to_group tests/Refs/refs.bib Diploma GoerzDiploma2010
```

### `remove_from_group NAME KEY...`

Remove entries from the group `NAME`, via
{py:meth}`~bibdeskparser.Library.remove_from_group`.

```console
$ bibdeskparser remove_from_group tests/Refs/refs.bib Diploma GoerzDiploma2010
```

### `set_group NAME [KEY...]`

Create the static group `NAME` with exactly the given entries, or
replace its membership if it already exists. With zero keys, the group
is created (or emptied) with no members. Corresponds to
`lib.groups[name] = keys` (see
{py:attr}`~bibdeskparser.Library.groups`).

```console
$ bibdeskparser set_group tests/Refs/refs.bib "To Read" \
    BrifNJP2010 KochEPJQT2022
```

### `delete_group NAME`

Delete the static group `NAME`; the entries themselves are not
affected. Corresponds to `del lib.groups[name]`.

```console
$ bibdeskparser delete_group tests/Refs/refs.bib Diploma
```

## Keywords

(cli-add-to-keyword)=

### `add_to_keyword KEYWORD KEY...`

Add `KEYWORD` to the given entries, via
{py:meth}`~bibdeskparser.Library.add_to_keyword`.

```console
$ bibdeskparser add_to_keyword tests/Refs/refs.bib Review BrifNJP2010
```

### `remove_from_keyword KEYWORD KEY...`

Remove `KEYWORD` from the given entries, via
{py:meth}`~bibdeskparser.Library.remove_from_keyword`.

```console
$ bibdeskparser remove_from_keyword tests/Refs/refs.bib Review BrifNJP2010
```

## Strings (macros)

### `set_string NAME VALUE`

Define or redefine the `@string` macro `NAME`. Corresponds to
`lib.strings[name] = value` (see
{py:attr}`~bibdeskparser.Library.strings`).

```console
$ bibdeskparser set_string tests/Refs/refs.bib prl "Phys. Rev. Lett."
```

### `delete_string NAME`

Delete the `@string` macro `NAME` (which must not be referenced by any
entry). Corresponds to `del lib.strings[name]`.

<!-- notest -->
```console
$ bibdeskparser delete_string tests/Refs/refs.bib prl
```

### `rename_string OLD NEW`

Rename the `@string` macro `OLD` to `NEW`, updating every entry that
references it, via {py:meth}`~bibdeskparser.Library.rename_string`.

```console
$ bibdeskparser rename_string tests/Refs/refs.bib quant quantum
```

## Document info

### `set_info KEY VALUE`

Create or update the document-info key `KEY` (see [`info`](cli-info))
as `VALUE`. `KEY` is matched case-insensitively against the existing
keys; a new key must be a valid BibTeX field name. Corresponds to
`lib.info[key] = value` (see {py:attr}`~bibdeskparser.Library.info`).

```console
$ bibdeskparser set_info tests/Refs/refs.bib project qdyn
```

### `delete_info KEY`

Remove the document-info key `KEY` (matched case-insensitively).
Removing the last key removes the `@bibdesk_info` block from the
`.bib` file. Corresponds to `del lib.info[key]`.

```console
$ bibdeskparser delete_info tests/Refs/refs.bib primary_topics
```

## Files

The commands in this section modify an entry's file attachments; the
read-only [`files`](cli-files) command lists them.

(cli-add-file)=

### `add_file KEY FILENAME`

Attach the file `FILENAME` to the entry `KEY`, via
{py:meth}`~bibdeskparser.Library.add_file`. When auto-filing is in
effect, the file is moved into the auto-file location, renamed by a
[file-name format](format-specifiers), and its stored path (relative
to the `.bib` file) is printed. Auto-filing is in effect when
`--location` or `--format-spec` is given, or when the configuration
sets `file_automatically = true`.

**Options**

- `--no-check-exists` -- do not require `FILENAME` to exist on disk
  (incompatible with auto-filing).
- `--location DIR` -- auto-file into DIR (relative to the `.bib` file,
  or absolute) instead of the configured location.
- `--format-spec PATTERN` -- auto-file using this
  [file-name format](format-specifiers) instead of the configured one.
- `--no-auto-file` -- attach under the original name even when the
  configuration enables auto-filing.

<!-- notest -->
```console
$ bibdeskparser add_file tests/Refs/refs.bib Shapiro2012 papers/shapiro-brumer.pdf
```

<!-- notest -->
```console
$ bibdeskparser add_file tests/Refs/refs.bib Shapiro2012 \
    ~/Downloads/9780471973461.pdf \
    --format-spec '%f{Cite Key}%u0%e' --location Papers
Papers/Shapiro2012.pdf
```

### `replace_file KEY OLD NEW`

Replace the entry's attached file `OLD` with `NEW`, via
{py:meth}`~bibdeskparser.Library.replace_file`.

**Options**

- `--remove` -- also delete the old file from the filesystem.
- `--no-check-exists` -- do not require `NEW` to exist on disk.

<!-- notest -->
```console
$ bibdeskparser replace_file tests/Refs/refs.bib GoerzJPB2011 \
    GoerzJPB2011.pdf corrected.pdf --remove
```

### `unlink_file KEY FILENAME`

Remove `FILENAME` from the entry's attachments, via
{py:meth}`~bibdeskparser.Library.unlink_file`. Pass `--remove` to also
delete the file from the filesystem.

```console
$ bibdeskparser unlink_file tests/Refs/refs.bib GoerzQ2022 GoerzQ2022.pdf
```

(cli-rename-file)=

### `rename_file KEY OLD [NEW]`

Rename (or move) the entry's attached file `OLD` to `NEW` on the
filesystem, updating every entry that links it, via
{py:meth}`~bibdeskparser.Library.rename_file`. Without `NEW`, the
target is generated by auto-filing: the file is moved into the
auto-file location and renamed by the configured
[file-name format](format-specifiers), and the new path (relative to
the `.bib` file) is printed. A file already matching the format is
left in place, and a `%u`/`%U`/`%n` specifier resolves collisions with
existing files. To preview without moving anything, use
[`eval_format_spec --filename`](cli-eval-format-spec).

**Options**

- `--format-spec PATTERN` -- generate the new name from this
  [file-name format](format-specifiers) instead of the configured one.
  Only valid without `NEW`.
- `--location DIR` -- move the file into DIR (relative to the `.bib`
  file, or absolute) instead of the configured auto-file location.
  Only valid without `NEW`.

```console
$ bibdeskparser rename_file tests/Refs/refs.bib MorzhinRMS2019 \
    MorzhinRMS2019.pdf Reviews/MorzhinRMS2019.pdf
```

<!-- notest -->
```console
$ bibdeskparser rename_file tests/Refs/refs.bib GraceJMO2007 grace_jmo_2007.pdf
GraceJMO2007.pdf
```

## URLs

The commands in this section modify an entry's linked URLs; the
read-only [`urls`](cli-urls) command lists them.

### `add_url KEY URL`

Add `URL` to the entry `KEY`, via
{py:meth}`~bibdeskparser.Library.add_url`.

```console
$ bibdeskparser add_url tests/Refs/refs.bib WattsPRA2015 \
    https://arxiv.org/abs/1412.7347
```

### `replace_url KEY OLD NEW`

Replace the entry's URL `OLD` with `NEW`, via
{py:meth}`~bibdeskparser.Library.replace_url`.

```console
$ bibdeskparser replace_url tests/Refs/refs.bib GoerzDiploma2010 \
    https://michaelgoerz.net/research/diploma_thesis.pdf \
    https://michaelgoerz.net/diploma_thesis.pdf
```

### `remove_url KEY URL`

Remove `URL` from the entry `KEY`, via
{py:meth}`~bibdeskparser.Library.remove_url`.

```console
$ bibdeskparser remove_url tests/Refs/refs.bib TomzaPRA2012 \
    http://dx.doi.org/10.1103/PhysRevA.86.043424
```

## Free-form editing

The `edit` and `edit_strings` commands accept arbitrary edits as
BibTeX text, interactively through `$EDITOR` or non-interactively by
piping the edited text to `--stdin`. Neither ever blocks without a
terminal: with no TTY on stdin and neither `--stdin` nor `--editor`,
they fail immediately with a usage error rather than hanging on
`$EDITOR`.

(cli-edit)=

### `edit KEY...`

Edit one or more entries (as BibTeX text) and merge the changes back
into the library, via {py:meth}`~bibdeskparser.Library.edit`. The text
to edit is exactly what [`export`](cli-export) prints for the same
keys.

**Options**

- `--editor CMD` -- editor command to use (default: `$EDITOR`).
- `--stdin` -- read the full edited text from standard input instead
  of opening an editor (mutually exclusive with `--editor`). Empty
  input is a usage error; input that fails validation exits 1 with the
  `.bib` file untouched.

```console
$ bibdeskparser edit tests/Refs/refs.bib GoerzQ2022 --editor vim
```

```console
$ bibdeskparser export tests/Refs/refs.bib GoerzQ2022 \
    | sed 's/Semi-Automatic/Semiautomatic/' \
    | bibdeskparser edit tests/Refs/refs.bib GoerzQ2022 --stdin
```

(cli-edit-strings)=

### `edit_strings`

Edit the `@string` macro definitions and merge the changes back into
the library, via {py:meth}`~bibdeskparser.Library.edit_strings`. The
baseline text comes from [`strings --bib`](cli-strings).

**Options**

- `--editor CMD` -- editor command to use (default: `$EDITOR`).
- `--stdin` -- read the full edited definitions from standard input
  instead of opening an editor (mutually exclusive with `--editor`).

```console
$ bibdeskparser edit_strings tests/Refs/refs.bib
```

```console
$ bibdeskparser strings tests/Refs/refs.bib --bib \
    | sed 's/EPJ Quantum Technol./EPJ Quantum Technology/' \
    | bibdeskparser edit_strings tests/Refs/refs.bib --stdin
```
