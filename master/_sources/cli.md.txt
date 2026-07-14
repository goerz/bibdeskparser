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

```console
$ bibdeskparser <command> [BIBFILE] <args> <options>
```

Run `bibdeskparser --help` for the list of commands,
`bibdeskparser <command> --help` for the arguments and options of a
specific command, and `bibdeskparser --version` for the installed
version.

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
`import` is a Python keyword). Operations that
the Python API expresses through `dict`-like access map to commands as
follows: `set_group`/`delete_group` assign to and delete from
{py:attr}`~bibdeskparser.Library.groups`, `set_string`/`delete_string`
assign to and delete from {py:attr}`~bibdeskparser.Library.strings`,
`show`/`keys`/`delete` correspond to indexing, iterating over, and
`del` on the library itself, and
`fields`/`get_field`/`set_field`/`delete_field` correspond to
iterating over, indexing, assigning to, and `del` on a single
{class}`~bibdeskparser.Entry` (its fields). Commands that read one
entry's derived data -- `author`, `editor`, `groups KEY`,
`keywords KEY` -- correspond to the same-named
{class}`~bibdeskparser.Entry` properties, and `set_type` assigns
{py:attr}`~bibdeskparser.Entry.entry_type`.

Read-only commands print their result to stdout. Mutating commands
load the library, apply the change, save the file back in place, and
print nothing on success -- except [`rekey`](cli-rekey) without
`NEW_KEY` and [`rename_file`](cli-rename-file) without `NEW`, which
print the generated key or file path, as does
[`add_file`](cli-add-file) when it auto-files, and
[`import`](cli-import)/[`add`](cli-add), which print the citation
keys of the added entries (`add --dry-run` only prints the fetched
entry, without modifying the file).
[`add_abstract`](cli-add-abstract) prints a per-key report of the
fetched abstracts (with `--dry-run`, without modifying the file).

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
underlying library -- an unknown citation key or group name, an
invalid value, a missing file, or a
{exc}`~bibdeskparser.StaleFileError` when the `.bib` file changed on
disk while being edited -- prints a one-line `Error: <message>` on
stderr and exits with code 1, without a traceback.

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

```console
$ bibdeskparser create new.bib
$ bibdeskparser import new.bib entries.bib
```

With a `default_bib_file` configured in `bibdeskparser.toml` (see
[Configuration](configuration)), `bibdeskparser create` without an
argument creates that file, bootstrapping the configured library.

## Inspecting

### `keys`

List citation keys, one per line. See
{py:meth}`~bibdeskparser.Library.keys`. With `--json`: an array of
strings.

```console
$ bibdeskparser keys tests/Refs/refs.bib --type book
Shapiro2012
BrumerShapiro2003
Tannor2007
MATLAB:2014
```

Without options, every entry is listed. Filter options narrow the
list: an entry is listed if it matches one of the (repeatable)
`--type TYPE` values (if any are given) and satisfies every
`--has FIELD`, `--missing FIELD`, and `--empty FIELD` filter. For any
field, exactly one of the three field predicates holds: `--has`
requires the field to be defined with a non-empty value, `--missing`
requires it to not be defined at all, and `--empty` requires it to be
defined, but with an empty value -- a defined-but-empty field is
neither "missing" nor "has". Types and field names are matched
case-insensitively.

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing eprint
WinckelIP2008
TuriniciHAL00640217
Vecheck2022.09.09.507322
```

### `duplicate_keys`

List citation keys that occur more than once, one per line. See
{py:attr}`~bibdeskparser.Library.duplicate_keys`. With `--json`: an
array of strings.

```console
$ bibdeskparser duplicate_keys tests/Refs/with_duplicates.bib
GoerzSPP2019
```

(cli-show)=

### `show [KEY...]`

Show the data of one or more entries: a `KEY (entry_type)` heading,
the raw fields, and derived data (groups, keywords, files, URLs, and
dates). Corresponds to indexing the library, `lib[key]`. With
`--json`: an object mapping each key to an object with `entry_type`,
`key`, `fields`, `groups`, `keywords`, `files`, `urls`, `date_added`,
and `date_modified`.

`--field FIELD` narrows the output to the named fields (repeatable and
comma-separated, case-insensitive), dropping the derived data; a field
not defined on an entry is silently omitted. With `--json`, this
yields a flat `{key: {field: value}}` map -- convenient for
backfilling missing metadata.

Keys come from the `KEY` arguments and/or `--keys-from FILE` (one key
per line; `-` reads standard input), so the output of another command
can be piped straight in. By default an unknown key aborts the command
with an error and no output; `--skip-missing` instead reports each miss
on stderr and shows the remaining entries.

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
$ bibdeskparser keys --missing eprint \
    | bibdeskparser show --field doi,title --json --keys-from -
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
case-insensitive. A field whose value is a reference to an `@string`
macro prints as the bare macro name (see [`strings`](cli-strings) for
the definitions). Fails for a field not defined on the entry (see
[`fields`](cli-fields)). With `--json`: a string.

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

### `search QUERY`

List the keys of the entries matching `QUERY`, best match first, one
per line. See {py:meth}`~bibdeskparser.Library.search`. With `--json`:
an array of keys.

The query is matched against the stored field values (bare `@string`
macro names intact), the decoded Unicode values, and macro expansions.
`--field FIELD` (repeatable) limits the search to the given fields; the
special name `key` matches against the citation key. `--match` sets the
match strictness (the levels up to `fuzzy` match everything from the
previous level and are case-insensitive; `regex` follows standard
{mod}`re` semantics):

- `exact`: the query occurs verbatim as a substring.
- `folded`: additionally ignores accents (`Schrodinger` and
  `Schroedinger` both find `Schrödinger`).
- `words` (the default): additionally matches when most of the query's
  words occur in a field, in any order.
- `fuzzy`: additionally tolerates small typos in individual words.
- `regex`: the query is a regular expression (case-sensitive unless the
  pattern says `(?i)`).

```console
$ bibdeskparser search tests/Refs/refs.bib "Schroedinger" --field title
WP_Schroedinger
```

### `groups [KEY]`

Without `KEY`, list all static groups and the keys they contain. See
{py:attr}`~bibdeskparser.Library.groups`. With `--json`: an object
mapping each group name to an array of keys.

```console
$ bibdeskparser groups tests/Refs/refs.bib
Diploma: Tannor2007, NielsenChuangCh10QEC, Evans1983, LapertPRA09
My Papers: GoerzDiploma2010, GoerzJPB2011, GoerzNJP2014, GoerzPRA2014, GoerzPhd2015, GoerzPRA2015, GoerzEPJQT2015, GoerzNPJQI2017, GoerzQST2018, GoerzSPP2019, GoerzSPIEO2021, GoerzQ2022, GoerzA2023
```

With `KEY`, list the names of the groups that entry belongs to, one
per line ({py:attr}`~bibdeskparser.Entry.groups`; with `--json`: an
array of strings):

```console
$ bibdeskparser groups tests/Refs/refs.bib GoerzQ2022
My Papers
```

### `keywords [KEY]`

Without `KEY`, list all keywords and the keys of the entries using
them. See {py:attr}`~bibdeskparser.Library.keywords`. With `--json`:
an object mapping each keyword to an array of keys.

```console
$ bibdeskparser keywords tests/Refs/refs.bib
OCT: BrifNJP2010, KochJPCM2016, SolaAAMOP2018, MorzhinRMS2019, ...
Coherent Control: BrifNJP2010, Shapiro2012, SolaAAMOP2018, ...
...
```

With `KEY`, list the keywords of that entry, one per line
({py:attr}`~bibdeskparser.Entry.keywords`; with `--json`: an array of
strings):

```console
$ bibdeskparser keywords tests/Refs/refs.bib LapertPRA09
Filtering
OCT
```

(cli-strings)=

### `strings`

List all `@string` macro definitions. See
{py:attr}`~bibdeskparser.Library.strings`. With `--json`: an object
mapping each macro name to its value. With `--bib` (mutually exclusive
with `--json`): re-parseable `@string{name = {value}}` lines, sorted
by name -- exactly the text that [`edit_strings`](cli-edit-strings)
presents in the editor, and thus the baseline for a non-interactive
`edit_strings --stdin` round trip.

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

### `timestamp`

Print the save timestamp from the file header, in ISO 8601 format (or
nothing, if the header has no timestamp). See
{py:attr}`~bibdeskparser.Library.timestamp`. With `--json`: a string
or `null`.

```console
$ bibdeskparser timestamp tests/Refs/refs.bib
2026-07-18T16:02:00-04:00
```

(cli-eval-format-spec)=

### `eval_format_spec KEY [FORMAT]`

Print the citation key that a format in the
[format-specifier language](format-specifiers) yields for the entry
at `KEY`, via
{py:meth}`~bibdeskparser.Library.eval_format_spec` -- without
renaming anything (unlike [`rekey`](cli-rekey)). `FORMAT` defaults to
the `format_spec` configured in the `[auto_key]` table of
`bibdeskparser.toml` (which may map a format per entry type). With
`--json`: a string.

A key that already matches the format evaluates to itself, so any
output other than `KEY` itself flags a nonconforming key:

```console
$ bibdeskparser eval_format_spec tests/Refs/refs.bib LapertPRA09 \
    '%a1%c{journal}0%Y%u0'
LapertPRA2009
```

With `--filename FILE`, the format is evaluated as a *file name*
instead, in the [file-name dialect](specifiers-files); nothing is
renamed or moved. `FILE` only supplies the original-name specifiers
`%l`/`%L`/`%e`/`%E` (e.g. its extension); it need not exist or be
attached to `KEY`, and an empty string selects the dialect when
`FORMAT` uses none of those specifiers. `FORMAT` then defaults to the
`[auto_file]` format. A preview shows the base name; on-disk
collision suffixes are added only by actual filing (`rename_file` /
`add_file`). If `FILE` is an attachment's current path and already
matches the format, it prints unchanged:

```console
$ bibdeskparser eval_format_spec tests/Refs/refs.bib Shapiro2012 \
    '%f{Cite Key}%u0%e' --filename shapiro.pdf
Shapiro2012.pdf
```

## Rendering and exporting

### `render KEY...`

Render a formatted citation for one or more entries, via
{py:meth}`~bibdeskparser.Library.render`. The `--format` option
selects the output format (`markdown`, the default, `tex`, or `html`);
`--style` selects the layout of multiple citations relative to one
another (`default`, `paragraphs`, `numbered list`, or
`itemized list`).

```console
$ bibdeskparser render tests/Refs/refs.bib GoerzA2023 --format tex
```

(cli-export)=

### `export KEY...`

Export one or more entries as self-contained BibTeX text (including
any `@string` macros they reference), via
{py:meth}`~bibdeskparser.Library.export`. The `--format` option
selects the export format (`default`, `raw`, or `minimal`);
`--outfile PATH` writes to a file instead of printing to stdout.

```console
$ bibdeskparser export tests/Refs/refs.bib GoerzA2023 --format minimal \
    --outfile out.bib
```

## Entries

(cli-rekey)=

### `rekey OLD_KEY [NEW_KEY]`

Change the citation key of an entry, via
{py:meth}`~bibdeskparser.Library.rekey`.

```console
$ bibdeskparser rekey tests/Refs/refs.bib LapertPRA09 LapertPRA2009
```

Without `NEW_KEY`, the key is **generated** from an auto-key format in
the [format-specifier language](format-specifiers) -- the
`--format-spec PATTERN` option if given, or else the `format_spec`
configured in the `[auto_key]` table of `bibdeskparser.toml` (which may
map a format per entry type; see the [configuration](configuration)) --
and printed to stdout:

```console
$ bibdeskparser rekey tests/Refs/refs.bib LapertPRA09
LapertPRA2009
$ bibdeskparser rekey tests/Refs/refs.bib LapertPRA09 --format-spec '%a1:%Y%u0'
Lapert:2009
```

A key that already matches the format is kept unchanged, and a
`%u`/`%U`/`%n` specifier in the format resolves collisions with the
other entries in the library. To preview the generated key without
renaming, use [`eval_format_spec`](cli-eval-format-spec).

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
`lib[key][fieldname] = value`; field names are case-insensitive.

```console
$ bibdeskparser set_field tests/Refs/refs.bib TuriniciHAL00640217 note \
    "Lecture notes for a graduate course"
```

Like BibDesk, a `VALUE` that is a valid `@string` macro name is
stored as a bare macro reference rather than as literal text;
`--literal` forces literal text instead
({class}`~bibdeskparser.ValueString`), and `--macro` forces a macro
reference ({class}`~bibdeskparser.MacroString`), failing for a
`VALUE` that is not a valid macro name. The `keywords`, date, and
`bdsk-*` fields cannot be set this way (use
[`add_to_keyword`](cli-add-to-keyword), [`add_file`](cli-add-file),
`add_url`, etc.); an `author`/`editor` `VALUE` must be parseable as
names. A warning is printed on stderr for a field that is not
appropriate for the entry type.

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

### `import [FILE]`

Import the entries of a BibTeX snippet -- read from `FILE`, from
standard input (`--stdin`), or downloaded from a URL (`--url URL`);
exactly one of the three -- into the library, via
{py:meth}`~bibdeskparser.Library.import_bibtex`, and print their
citation keys. The snippet may be anything from a single
publisher-provided entry to a complete `.bib` file (including
`@string` definitions, e.g. the output of [`export`](cli-export)).

Every entry is sanitized and normalized on its way in (see
{py:meth}`~bibdeskparser.Library.import_bibtex` for the full list):
the journal becomes an `@string` macro reference -- resolved against
the library's macros and the
[`[journal_macros]` configuration](config-journal-macros), or newly
created, with a warning, from the journal's lowercased initials
(literal `arXiv:...` pseudo-journals excepted); proper nouns in
sentence-case titles and all configured `protected_words` are
brace-protected; DOIs are normalized; for articles, page ranges
collapse to the first page and non-essential fields are dropped.
Citation keys are regenerated from the
[`[auto_key]` format](config-auto-key) if configured, else as e.g.
`GoerzPRA2014` (articles) or `Goerz2205.15044` (arXiv preprints);
`--keep-keys` keeps the incoming keys instead. `--fix-uppercase`
repairs all-uppercase names/titles found in some publisher data.

An entry whose DOI or eprint is already in the library is rejected,
and any validation problem in the snippet rejects the whole import,
reporting all problems at once, with the `.bib` file untouched.

```console
$ bibdeskparser import tests/Refs/refs.bib entries.bib
BaumgratzPRL2014
$ pbpaste | bibdeskparser import tests/Refs/refs.bib --stdin
GrapeJMR2005
$ bibdeskparser import tests/Refs/refs.bib --url https://example.com/more.bib
MotzoiPRL2009
```

Note that the *first* argument ending in `.bib` names the library, so
importing from a `.bib` file requires naming the library explicitly
(`import tests/Refs/refs.bib entries.bib`), even with a configured
`default_bib_file`.

(cli-add)=

### `add QUERY...`

Fetch bibliographic data for `QUERY` from the appropriate online
source and add it to the library as a new, sanitized entry, via
{py:meth}`~bibdeskparser.Library.add`, printing its citation key. All
`QUERY` arguments are joined into a single query:

* an **arXiv identifier** (`2205.15044`, `quant-ph/0106057`), or any
  string containing one (e.g. an `arxiv.org` URL), is fetched from
  the arXiv API and added as an `@article` preprint with a literal
  `journal = {arXiv:...}`, `eprint`, and `archiveprefix`;
* a **DOI**, or a URL containing one (e.g. most publisher article
  pages), is fetched from [Crossref](https://www.crossref.org);
* anything else (free text with spaces) is a **Crossref
  bibliographic search**, adding the best match -- verify the
  result!

An arXiv identifier wins over a DOI when the query contains both.
The fetched data passes through exactly the same sanitization as
[`import`](cli-import) (journal macros, title protection, key
generation, duplicate rejection). Crossref works of a type with no
BibTeX equivalent (e.g. datasets) are retrieved as publisher BibTeX
via DOI content negotiation and imported as-is. Requires network
access; the arXiv API's rate limits are respected automatically.

```console
$ bibdeskparser add tests/Refs/refs.bib 10.1103/PhysRevA.89.032334
MuellerPRA2014
$ bibdeskparser add tests/Refs/refs.bib https://arxiv.org/abs/1801.00862
Preskill1801.00862
$ bibdeskparser add tests/Refs/refs.bib pulser open-source pulse sequences
SilverioQ2022
```

With `--dry-run`, the sanitized entry is printed (as re-parseable
BibTeX, like `export`) and the `.bib` file is not modified -- useful
to check what a free-text query matched. `--fix-uppercase` repairs
all-uppercase names/titles in the fetched metadata. With
`--add-abstract`, the abstract returned alongside the metadata (the
publisher's Crossref deposit, or the arXiv summary) is stored in the
new entry's `abstract` field, cleaned to plain-unicode prose; see
[`add_abstract`](cli-add-abstract) for filling the field afterwards,
with more sources. With `--add-preprint`, arXiv is searched for a
preprint matching the new entry, exactly as with
[`add_preprint`](cli-add-preprint), whose report goes to stderr here
(stdout stays the citation key); the search is skipped when the
entry already has an `eprint`, as one fetched from an arXiv query
does. All three options default to the
[`[add]` configuration table](config-add), and each has a negative
form (`--no-add-abstract`, ...) to override a configured `true`.

```console
$ bibdeskparser add tests/Refs/refs.bib --dry-run 10.22331/q-2022-01-24-629
@string{quant = {Quantum}}

@article{SilverioQ2022,
...
```

## Abstracts and preprints

(cli-add-abstract)=

### `add_abstract KEY...`

Fetch and store missing abstracts for the given entries, via
{py:meth}`~bibdeskparser.Library.add_abstract`. For each `KEY`,
candidate abstracts are gathered from Crossref (via the entry's
`doi`), from the text of the entry's first attached PDF (requires the
[poppler](https://poppler.freedesktop.org) `pdftotext` tool on
`PATH`; skipped otherwise), from the arXiv API (via the entry's
`eprint`), and from Semantic Scholar as a last resort. Each candidate
is cleaned to plain-unicode prose (math markup converted to unicode,
publisher copyright trailers stripped) and validated with heuristic
garble checks, and the best one is stored in the entry's `abstract`
field -- but only if its *confidence* reaches `--min-confidence`
(`high`, the default; `medium`; or `low`):

* `high`: an online abstract identified by the entry's `doi`/`eprint`
  (and agreeing with the PDF text, where both exist), or an
  unambiguous PDF extraction;
* `medium`: a single unconfirmed source;
* `low`: the PDF text and an online source *disagree* -- one of them
  probably grabbed the wrong text.

The command prints a per-key report. A candidate that was *not*
stored is reported in full, so it can be reviewed and applied
manually with [`set_field`](cli-set-field). Entries that already have
a non-empty abstract are skipped (`--overwrite` refetches and
replaces them); an entry whose abstract is present but *empty* does
not need `--overwrite`. With `--mark-empty`, an entry for which no
valid abstract is found anywhere gets an *empty* `abstract` field,
marking it as audited: such entries are matched by
`keys --empty abstract`, no longer by `keys --missing abstract`.
`--min-confidence` and `--mark-empty` default to the
[`[add_abstract]` configuration table](config-add). Requires network
access; `--dry-run` prints the report without modifying the `.bib`
file, and `--json` maps each key to
`{abstract, source, confidence, note, applied}`.

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing abstract
TuriniciHAL00640217
SauvagePRXQ2020
Vecheck2022.09.09.507322
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
first author, precise queries first) and, on a confident match, its
identifier is stored in the entry's `eprint` field, along with
`archiveprefix = arXiv`. A result is accepted only when

* its arXiv DOI equals the entry's `doi` field (the strongest
  signal), or
* its title is a near-exact match, or
* a good title match is corroborated by the first author's last name.

A title-based match whose arXiv submission postdates the entry's
`year` by more than a year is rejected unless its journal reference
names that year -- a guard against unrelated papers sharing a generic
title. Such a `postdated-unverified` candidate is only reported;
after reviewing it, apply it explicitly with `--eprint ID` (a single
`KEY` only, no network access; a leading `arXiv:` prefix and a
version suffix are stripped).

The `eprint` field encodes the entry's audit state: *absent* means
the preprint status is unknown (`keys --missing eprint`), *empty*
means a search ran cleanly and found no preprint
(`keys --empty eprint`), non-empty holds the identifier. With
`--mark-empty` (defaulting to the
[`[add_preprint]` configuration table](config-add)), a clean
no-match stores that empty marker, so repeated fill-in runs skip the
entry. Entries that already have a non-empty `eprint` are skipped
(`--overwrite` re-searches and replaces); the empty marker is
re-searched without `--overwrite`. On a failed search (network/API
error) the entry is never modified, so a re-run picks it up.

The command prints a per-key report; `--dry-run` prints it without
modifying the `.bib` file, and `--json` maps each key to
`{eprint, match, ratio, note, applied}`. Requires network access
(except with `--eprint`) and respects the arXiv API's rate limit of
one request every three seconds, so large runs take time.

```console
$ bibdeskparser keys tests/Refs/refs.bib --type article --missing eprint
WinckelIP2008
TuriniciHAL00640217
Vecheck2022.09.09.507322
$ bibdeskparser add_preprint tests/Refs/refs.bib --mark-empty \
    WinckelIP2008 Vecheck2022.09.09.507322
WinckelIP2008: no preprint found (stored empty marker) [best-ratio=0.42]
Vecheck2022.09.09.507322: no preprint found (stored empty marker) [best-ratio=0.31]
```

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
$ bibdeskparser delete_group tests/Refs/refs.bib "To Read"
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

```console
$ bibdeskparser delete_string tests/Refs/refs.bib prl
```

### `rename_string OLD NEW`

Rename the `@string` macro `OLD` to `NEW`, updating every entry that
references it, via {py:meth}`~bibdeskparser.Library.rename_string`.

```console
$ bibdeskparser rename_string tests/Refs/refs.bib quant quantum
```

## Files

(cli-add-file)=

### `add_file KEY FILENAME`

Attach the file `FILENAME` to the entry `KEY`, via
{py:meth}`~bibdeskparser.Library.add_file`. By default, `FILENAME`
must exist on disk; pass `--no-check-exists` to skip that check.

```console
$ bibdeskparser add_file tests/Refs/refs.bib Shapiro2012 papers/shapiro-brumer.pdf
```

When **auto-filing** is in effect, the file is not attached under its
original name: it is *moved* into the auto-file location, renamed
according to a file-name format in the
[format-specifier language](format-specifiers), and the stored path
(relative to the `.bib` file) is printed to stdout. Auto-filing is in
effect when `--location DIR` or `--format-spec PATTERN` is given
(each defaulting the other to the `[auto_file]` configuration; see
the [configuration](configuration)), or when the configuration sets
`file_automatically = true`; pass `--no-auto-file` to force a plain
attach regardless of the configuration:

```console
$ bibdeskparser add_file tests/Refs/refs.bib Shapiro2012 \
    ~/Downloads/9780471973461.pdf \
    --format-spec '%f{Cite Key}%u0%e' --location Papers
Papers/Shapiro2012.pdf
```

### `replace_file KEY OLD NEW`

Replace the entry's attached file `OLD` with `NEW`, via
{py:meth}`~bibdeskparser.Library.replace_file`. Pass `--remove` to
also delete the old file from the filesystem, and `--no-check-exists`
to not require `NEW` to exist on disk.

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
{py:meth}`~bibdeskparser.Library.rename_file`.

```console
$ bibdeskparser rename_file tests/Refs/refs.bib MorzhinRMS2019 \
    MorzhinRMS2019.pdf Reviews/MorzhinRMS2019.pdf
```

Without `NEW`, the target is generated by **auto-filing**: the file
is moved into the auto-file location and renamed according to a
file-name format in the
[format-specifier language](format-specifiers) -- the
`--format-spec PATTERN` and `--location DIR` options if given, or
else the `format_spec` and `location` keys of the `[auto_file]` table
of `bibdeskparser.toml` (see the [configuration](configuration)) --
and the new path (relative to the `.bib` file) is printed to stdout:

```console
$ bibdeskparser rename_file tests/Refs/refs.bib GraceJMO2007 grace_jmo_2007.pdf
GraceJMO2007.pdf
```

A file whose name already matches the format is left in place
(re-filing is idempotent), and the format's `%u`/`%U`/`%n` specifier
resolves collisions with existing files. To preview the generated
path without moving anything, use
[`eval_format_spec --filename`](cli-eval-format-spec).

## URLs

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
$ bibdeskparser remove_url tests/Refs/refs.bib WattsPRA2015 \
    https://arxiv.org/abs/1412.7347
```

## Free-form editing

The `edit` and `edit_strings` commands accept arbitrary edits as
BibTeX text -- interactively through `$EDITOR`, or non-interactively
by piping the edited text to `--stdin`. Neither command ever blocks
without a terminal: invoked with no TTY on stdin and with neither
`--stdin` nor an explicit `--editor`, they fail immediately with a
usage error rather than hanging on `$EDITOR`.

### `edit KEY...`

Edit one or more entries (as BibTeX text) and merge the changes back
into the library, via {py:meth}`~bibdeskparser.Library.edit`. The
`--format` option (`default`, `raw`, or `minimal`) controls how the
entries are presented; `--editor CMD` overrides the editor command
(which defaults to `$EDITOR`).

```console
$ bibdeskparser edit tests/Refs/refs.bib GoerzQ2022 --editor vim
```

With `--stdin` (mutually exclusive with `--editor`), the full edited
text is read from standard input instead of opening an editor. The
text to edit is exactly what [`export`](cli-export) prints for the
same keys, so any pipeline that transforms the exported text works;
piping it back unchanged is a no-op:

```console
$ bibdeskparser export tests/Refs/refs.bib GoerzQ2022 \
    | sed 's/Semi-Automatic/Semiautomatic/' \
    | bibdeskparser edit tests/Refs/refs.bib GoerzQ2022 --stdin
```

Empty input to `--stdin` is a usage error (so an accidental
`< /dev/null` cannot silently apply a no-op edit), and text that fails
validation -- an unparseable block, or a reference to an undefined
`@string` macro -- exits with code 1 and the list of problems on
stderr, leaving the `.bib` file untouched.

(cli-edit-strings)=

### `edit_strings`

Edit the `@string` macro definitions and merge the changes back into
the library, via {py:meth}`~bibdeskparser.Library.edit_strings`.

```console
$ bibdeskparser edit_strings tests/Refs/refs.bib
```

With `--stdin`, the edited definitions are read from standard input;
the baseline text comes from [`strings --bib`](cli-strings):

```console
$ bibdeskparser strings tests/Refs/refs.bib --bib \
    | sed 's/EPJ Quantum Technol./EPJ Quantum Technology/' \
    | bibdeskparser edit_strings tests/Refs/refs.bib --stdin
```
