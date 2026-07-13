(format-specifiers)=

# Format Specifiers

BibDesk has a small *format-specifier language* -- `%`-templates like
`"%a1%c{journal}0%Y%u0"` that expand against an entry's fields. BibDesk
uses it in two places: to autogenerate **citation keys** (its
*Preferences → Cite Key* pane) and to autogenerate **attachment file
names** (its AutoFile feature). This page documents the language
itself. `bibdeskparser` applies it in the same two places: citation
keys ({meth}`Library.rekey <bibdeskparser.Library.rekey>`, configured
by the [`[auto_key]` table](config-auto-key)) and attachment file
names ({meth}`Library.add_file <bibdeskparser.Library.add_file>` and
{meth}`Library.rename_file <bibdeskparser.Library.rename_file>`,
configured by the [`[auto_file]` table](config-auto-file)). The two
uses share the specifiers described below; the
[file-name dialect](specifiers-files) differs only in the few points
covered in its own section.

The most common use is autogenerating a citation key from a *format
string*, via single-argument
{meth}`Library.rekey <bibdeskparser.Library.rekey>` (or the
[`rekey` CLI command](cli-rekey) without a `NEW_KEY`):

```python
>>> from bibdeskparser import Library, Entry
>>> bib = Library()
>>> bib["temp"] = Entry(
...     "article",
...     "temp",
...     {
...         "author": "Goerz, Michael H. and Koch, Christiane P.",
...         "title": "Robustness of high-fidelity {Rydberg} gates",
...         "journal": "Phys. Rev. A",
...         "volume": "90",
...         "pages": "032329",
...         "year": "2014",
...         "month": "aug",
...         "doi": "10.1103/PhysRevA.90.032329",
...     },
... )
>>> bib.rekey("temp", format_spec="%a1%c{journal}0%Y%u0")
'GoerzPRA2014'

```

The format string language is **BibDesk's own**: a format string that
works in BibDesk's *Preferences → Cite Key* pane works here identically
(with the few exceptions [noted below](specifiers-differences)).

For citation keys, the format is usually configured once, in the
`[auto_key]` table of `bibdeskparser.toml` (see the
[configuration](configuration)), where
it may also be given [per entry type](config-auto-key); the
`format_spec` argument used above overrides it ad hoc. The examples
below use {meth}`Library.eval_format_spec
<bibdeskparser.Library.eval_format_spec>` instead, which evaluates a
format for an entry and returns the resulting key *without renaming
anything*:

```python
>>> bib.eval_format_spec("GoerzPRA2014", "%a1%Y")
'Goerz2014'

```

## Specifiers

Any character other than `%` stands for itself (subject to
[sanitization](specifiers-sanitization)); a `%` introduces a specifier.

### Anatomy of a specifier

After the `%`, a specifier has up to four parts, always in this order.
Only the letter is required; the rest are added as needed. For example,
in the specifier `%f{journal}[/]5`:

* `%f` -- the **specifier**: `%` plus one letter that chooses *what* to
  insert (an author, the title, the year, ...).
* `{journal}` -- a **`{Field}` name**, the entry field to read. Only
  `%f`, `%w`, `%c`, and `%s` take one, written right after the letter.
  The name is case-insensitive.
* `[/]` -- one or more **arguments** in square brackets: separators,
  "et al." text, or per-character replacements. Arguments are
  *positional*, so to supply a later one you must supply the earlier
  ones too, giving an unused one as empty (`[]`).
* `5` -- the **trailing number**, which caps an amount. *What* it
  counts is specific to the specifier (names, words, keywords,
  characters, ...). A few specifiers take *two* numbers, written back
  to back with no separator: `%a22` means two names, two characters
  each.

A bare `@string` macro reference as a field value (e.g.
`journal = pra`) is expanded using the library's macro definitions
before any specifier is applied.

The subsections below are the complete reference for each group of
specifiers. The examples evaluate a format against the
`GoerzPRA2014` entry defined above (an `@article` by Goerz and Koch).

### Author names: `%a`, `%A`, `%p`, `%P`

The last names of the people in the `author` field. `%p` and `%P` use
the `editor` field instead when the entry has no author.

* `%a` / `%p` -- the last names, concatenated. *Arguments*
  `[separator][etal]`: text placed between names, and text appended
  when names are dropped. *Number* the count of names (a single digit,
  or a negative `-N` counting from the last author), optionally
  followed by a second digit giving the characters to keep per name.
* `%A` / `%P` -- the last names, each with the author's first initial.
  *Arguments* `[author separator][name separator][etal]`. *Number* the
  count of names.

```python
>>> key = "GoerzPRA2014"
>>> bib.eval_format_spec(key, "%a")     # all authors, full last names
'GoerzKoch'
>>> bib.eval_format_spec(key, "%a1")    # first author only
'Goerz'
>>> bib.eval_format_spec(key, "%a22")   # two authors, two chars each
'GoKo'
>>> bib.eval_format_spec(key, "%a-1")   # the *last* author
'Koch'
>>> bib.eval_format_spec(key, "%a[-][X]1")   # "X" marks dropped authors
'GoerzX'
>>> bib.eval_format_spec(key, "%A")     # last name + first initial
'Goerz.M;Koch.C'
>>> bib.eval_format_spec(key, "%A[-][][]1")  # empty in-name separator
'GoerzM'

```

As a BibDesk quirk, an unescaped trailing digit in the `[etal]`
argument further lowers the name count: for a five-author paper,
`%a[][X1]2` requests two names but the trailing `1` cuts that to one,
rendering the first author followed by `X` (`GoerzX`).

### Title: `%t`, `%T`

* `%t` -- the whole title. *Number* characters to keep.
* `%T` -- the title word by word, joined with `-`. *Number* words to
  keep, counting only words longer than the *small word length*
  (default 3). *Argument* `[small word length]` overrides that length
  **and** drops the short words entirely; without the argument, short
  words are kept (they simply do not count toward the number).

```python
>>> bib.eval_format_spec(key, "%t12")    # first 12 characters
'Robustness-o'
>>> bib.eval_format_spec(key, "%T[3]2")  # two words longer than 3 chars
'Robustness-high-fidelity'

```

### Date: `%y`, `%Y`, `%m`

* `%y` / `%Y` -- the year, two-digit / four-digit.
* `%m` -- the month as two digits, read from a number or an English
  month name (`aug`, `August`).

```python
>>> bib.eval_format_spec(key, "%Y-%y-%m")
'2014-14-08'

```

### Arbitrary fields: `%f`, `%w`

Both take a `{Field}` name. The special names `Cite Key` and
`BibTeX Type` yield the entry's current key and its type.

* `%f{Field}` -- the field's value. *Argument* `[slash]`, a
  replacement for any `/` in the value. *Number* characters to keep.
* `%w{Field}` -- the field's value split into words. *Arguments*
  `[separator characters][slash][separator]`. *Number* words to keep.

```python
>>> bib.eval_format_spec(key, "%f{volume}")
'90'
>>> bib.eval_format_spec(key, "%f{journal}5")  # first 5 characters
'Phys.'
>>> bib.eval_format_spec(key, "%f{doi}[_]")    # "/" replaced by "_"
'10.1103_PhysRevA.90.032329'
>>> bib.eval_format_spec(key, "%w{doi}[./][-][_]2")  # first 2 "words"
'10_1103'

```

### Conditional text: `%s`

* `%s{Field}` -- fixed text chosen by interpreting a field's value as
  boolean-ish (`yes`/`no`/`true`/`false`/`1`/`0`, plus a "mixed" state
  for `-1`). *Arguments* `[yes][no][mixed]`. *Number* characters to
  keep. Unlike the other field specifiers, `%s` emits its argument
  text, not the field value itself.

For example, `%s{Draft}[D][F]` renders `D` when the entry has
`Draft = {yes}` and `F` otherwise.

### Acronym: `%c`

* `%c{Field}` -- the acronym ("initials") of a field value: the
  uppercased first letter of each of its words. *Number* the small word
  length (default 3; use `0` to keep every word).

`%c` works on any field, but in practice it abbreviates a venue name
(e.g. `Phys. Rev. A` → `PRA`) — a journal, conference, or book series,
which lives in a different field per entry type (`journal` for an
`@article`, `booktitle` for an `@inproceedings`, `series` for a
`@book`). Its recommended pattern, the small-word-length rule, and the
`[initials]` exception table are covered in
[venue initials](specifiers-initials).

### Keywords and file name: `%k`, `%b`

* `%k` -- the entry's keywords, concatenated. *Arguments*
  `[slash][separator]` (a replacement for `/` inside a keyword, and
  text between keywords). *Number* keywords to keep.
* `%b` -- the library file's name, without the `.bib` extension.

For example, an entry with the keywords `quantum control` and
`rydberg` renders `%k[-][_]` as `quantum-control_rydberg` (spaces
become `-`, and the keywords are joined by `_`).

### Original file name: `%l`, `%L`, `%e`, `%E`

These four specifiers exist only in
[file-name formats](specifiers-files) (they are rejected in a
citation-key format, exactly as in BibDesk). They refer to the
attached file that is being renamed, under its *current* name -- the
name it has before the move; no separate "original" name is stored
anywhere:

* `%l` -- the file's name without its extension.
* `%L` -- the file's full name, including the extension.
* `%e` -- the extension, *with* its leading dot (`.pdf`), or nothing
  if the file has no extension.
* `%E` -- the extension *without* the dot. *Argument* `[default]`, a
  fallback used when the file has no extension.

BibDesk's default file-name format, `%l%n0%e`, keeps every file's
name and merely appends a number when a file of that name already
exists at the target location.

### Random and unique characters: `%r`, `%R`, `%d`, `%u`, `%U`, `%n`

* `%r` / `%R` / `%d` -- random lowercase letters / uppercase letters /
  digits. *Number* characters (default 1).
* `%u` / `%U` / `%n` -- **unique** lowercase letters / uppercase
  letters / digits, inserted to make the key unique in the library.
  *Number* characters (default 1; `0` inserts only as many as needed).
  At most one of these three may appear in a format. They have their
  own section: [unique specifiers](specifiers-unique).

### Literal characters: `%0`–`%9`, `%[`, `%]`, `%-`

A digit or bracket right after another specifier would be read as its
number or an argument, so these characters are escaped as `%<char>` to
insert them literally:

```python
>>> bib.eval_format_spec(key, "ref%-%Y%1%[x%]")  # literal - 1 [ ]
'ref-20141[x]'

```

(specifiers-initials)=

## Venue initials: `%c` and the `[initials]` mapping

`%c{Field}` builds an acronym from the uppercased first letters of the
words of a field value. The trailing number is the *small word length*:
words no longer than it are dropped, except words ending in a period
(like the `Phys.` and `Rev.` of a journal abbreviation), which always
count. The default is 3.

Because that default drops words of three or fewer letters, a value
like `Phys. Rev. A` would lose its trailing `A`. **The recommended
pattern is therefore `%c{journal}0`:** the trailing `0` sets the small
word length to zero, so no words are omitted and the acronym is built
from every word. `Phys. Rev. A` then abbreviates to `PRA` with no
manual configuration:

```python
>>> bib.eval_format_spec(key, "%c{journal}0")  # keep every word
'PRA'
>>> bib.eval_format_spec(key, "%c{journal}")   # default 3 drops the "A"
'PR'

```

The `0` is a plain example of the trailing *number*; it is not special
to `%c` beyond meaning "small word length zero". Use it (or a per-type
`%c{...}0` format) wherever you want the full venue acronym.

For venue names where the acronym is *not* the desired abbreviation,
the `[initials]` table in `bibdeskparser.toml` (see the
[configuration](configuration)) defines explicit exceptions per
field, keyed by the full field value or by the `@string` macro name:

```toml
[initials.journal]
"npj Quantum Inf" = "NPJQI"
"SIAM Rev." = "SR"
```

With this configuration, `%c{journal}0` renders `NPJQI` for an entry
published in npj Quantum Inf (instead of the plain acronym `NQI`).
The mapping applies whenever `%c` is rendered, including with an
explicit `format_spec` pattern.

The table works for any field, so a per-type format that uses
`%c{booktitle}` for conference papers or `%c{series}` for books draws
on `[initials.booktitle]` / `[initials.series]` the same way:

```toml
[initials.booktitle]
"Proc. SPIE 11700, Optical and Quantum Sensing" = "SPIE"
```

Conference `booktitle` values are awkward for a plain acronym — they
carry a volume number and a long subtitle that change from year to
year — so this mapping is the intended way to pin a stable
abbreviation (here `SPIE` rather than the raw acronym `PSOAQS`).
Because the mapping matches the *full* field value, and that value
differs for every proceedings volume, it is often cleaner to store the
`booktitle` as an `@string` macro and key the mapping by the macro
name: one macro (e.g. `spie_oqspm`) can then stand in for every volume
of the series, and `[initials.booktitle]` needs only the single entry
`spie_oqspm = "SPIE"`.

(specifiers-unique)=

## Unique specifiers

At most one `%u` (lowercase letters), `%U` (uppercase letters), or
`%n` (digits) may occur in a format. It inserts, at its position,
characters that make the key unique within the library (in a
[file-name format](specifiers-files), where it is required, unique
against the files at the target location). With a
trailing count of `0`, characters are only added when needed for
disambiguation; with a fixed count `N`, exactly `N` characters are
always added:

```python
>>> bib["Goerz2014"] = Entry(
...     "article",
...     "Goerz2014",
...     {
...         "author": "Goerz, Michael H.",
...         "title": "Another Paper",
...         "journal": "Phys. Rev. A",
...         "year": "2014",
...     },
... )
>>> bib.rekey("Goerz2014", format_spec="%a1%c{journal}0%Y%u0")
'GoerzPRA2014a'

```

Regenerating a key is **idempotent**: a key that already fits the
format (base text, any unique characters, ending) is kept unchanged,
so re-running key generation over a library does not churn the
disambiguation suffixes:

```python
>>> bib.eval_format_spec("GoerzPRA2014a", "%a1%c{journal}0%Y%u0")
'GoerzPRA2014a'

```

Conversely, `bib.eval_format_spec(key, fmt) != key` identifies the
entries whose key does *not* follow a given format (see the
[how-to guide](howto-auto-keys)).

A format *without* a unique specifier can generate a key that is
already taken; `rekey` then raises a `ValueError`, like an explicit
rename to a taken key. Should a format render an entirely empty
key, a plain number is used instead (`1`, `2`, ...).

### Deterministic unique characters

With a fixed count, an optional `[Field]` argument derives the added
characters from a hash of that field instead of by sequential search,
so the same reference gets the same key in any library:

```python
>>> bib.eval_format_spec("GoerzPRA2014", "%a1:%Y%u[Title]2")
'Goerz:2014vy'

```

(If the hashed candidate is taken, sequential search is the
fallback.) The exact format `%a1:%Y%u[Title]2` — or with `[Doi]` — is
BibDesk's "universal cite key", hash-compatible with the Papers 2/3
reference manager.

(specifiers-sanitization)=

## Sanitization

This section describes the citation-key context; file names are
sanitized differently (see [file-name formats](specifiers-files)).
Generated keys must be TeX-safe. Every field value is cleaned up
before it enters the key:

1. TeX markup is removed, per the `clean` option of the `[auto_key]`
   configuration table: `"tex"` (the default) removes commands like
   `\emph{...}` and all braces, `"braces"` removes only braces, and
   `"none"` disables this step.
2. Accents and ligatures are decomposed to plain ASCII letters
   (`ü` → `u`, `ø` → `o`, `æ` → `ae`, `ß` → `ss`, ...).
3. Whitespace becomes `-`, and any remaining character outside
   `a-z A-Z 0-9 - . / : ;` is dropped.

```python
>>> bib["Mueller"] = Entry(
...     "article",
...     "Mueller",
...     {
...         "author": "Müller, Jörg",
...         "title": "It's a {Schrödinger} World",
...         "journal": "New J. Phys.",
...         "year": "2020",
...     },
... )
>>> bib.eval_format_spec("Mueller", "%a1%c{journal}0%Y:%t")
'MullerNJP2020:Its-a-Schrodinger-World'

```

Note that BibDesk simply strips accented characters of their accent
(`Müller` → `Muller`); it does not apply German transliteration
(`Mueller`). If you want `Mueller`, hard-code the intended key with a
two-argument `rekey`. Literal text in the format itself is sanitized
similarly (whitespace becomes `-`; characters invalid in a hand-typed
key are dropped, which notably includes `(`, `)`, and `@`).

The `lowercase` option of the `[auto_key]` table lowercases the whole
generated key; a `%U` specifier then adds lowercase characters, like
`%u`.

(specifiers-files)=

## File-name formats

A format for attachment file names (BibDesk's *AutoFile* feature) is
the same language, with a few differences. It is configured in the
[`[auto_file]` table](config-auto-file) and used by
{meth}`Library.rename_file <bibdeskparser.Library.rename_file>`
without a `new_filename` and by
{meth}`Library.add_file <bibdeskparser.Library.add_file>` when
auto-filing (see the [how-to guide](howto-auto-file)); the generated
name is interpreted relative to the configured auto-file *location*.

* The original-file-name specifiers `%l`, `%L`, `%e`, and `%E`
  (documented above) are available.
* A **unique specifier** (`%u`/`%U`/`%n`) is **required**, so that
  generated names can never collide. Uniqueness is checked against
  the *files on disk* at the target location, not against the
  library: a candidate name is taken if a file already exists there.
* A literal `/` in the format is a **directory separator**: the file
  is filed into (newly created, as needed) subfolders of the
  location. A `/` inside a *field value* becomes `-` instead, so
  values can never introduce unintended subfolders.
* Sanitization is file-name oriented: after the TeX cleanup (the
  `clean` option of `[auto_file]`), only `:` -- the one character
  invalid in a file name -- is removed. In particular, spaces,
  parentheses, and non-ASCII text all survive, unlike in a citation
  key. The `lowercase` option of `[auto_file]` lowercases the whole
  generated name.

To preview the file name a format generates, use
{meth}`Library.eval_format_spec <bibdeskparser.Library.eval_format_spec>`
with a `filename`. This is a pure evaluation of the format: it never
touches the filesystem and moves nothing. The `filename` argument only
supplies the original-name specifiers `%l`/`%L`/`%e`/`%E` (above); it
need not exist or be one of the entry's attachments, and any
non-`None` value -- including the empty string `""` -- selects the
file-name dialect:

```python
>>> filebib = Library()
>>> filebib["GoerzPRA2014"] = Entry(
...     "article",
...     "GoerzPRA2014",
...     {
...         "author": "Goerz, Michael H. and Koch, Christiane P.",
...         "title": "Robustness of high-fidelity {Rydberg} gates",
...         "journal": "Phys. Rev. A",
...         "year": "2014",
...     },
... )
>>> filebib.eval_format_spec(
...     "GoerzPRA2014", "%f{Cite Key}%u0%e", filename="downloaded.pdf"
... )
'GoerzPRA2014.pdf'
>>> filebib.eval_format_spec(
...     "GoerzPRA2014", "%a1/%Y%u0%e", filename="downloaded.pdf"
... )
'Goerz/2014.pdf'
>>> filebib.eval_format_spec(  # spaces survive in a file name
...     "GoerzPRA2014", "%t%u0%e", filename="downloaded.pdf"
... )
'Robustness of high-fidelity Rydberg gates.pdf'
>>> filebib.eval_format_spec(  # "" still selects the file dialect
...     "GoerzPRA2014", "%f{Cite Key}%u0", filename=""
... )
'GoerzPRA2014'

```

A preview shows the *base* name, with the required unique specifier
contributing no disambiguation. On-disk collision avoidance happens
only during actual filing ({meth}`~bibdeskparser.Library.rename_file`
/ {meth}`~bibdeskparser.Library.add_file`), where the unique specifier
grows a suffix (e.g. `GoerzPRA2014a.pdf`) whenever another file already
occupies the target name.

If `filename` is an attachment's current library-relative path (as
listed by {attr}`~bibdeskparser.Entry.files`) and already matches the format, it
evaluates to itself -- the same idempotency as a regenerated citation
key. `bib.eval_format_spec(key, fmt, filename=name) != name` thus
identifies the attachments that do not yet follow the format:

```python
>>> filebib.eval_format_spec(  # "downloaded.pdf" matches %l%n0%e
...     "GoerzPRA2014", "%l%n0%e", filename="downloaded.pdf"
... )
'downloaded.pdf'

```

**The recommended format is `%f{Cite Key}%u0%e`:** it names each
attachment after its entry's citation key while preserving the file's
real extension. Prefer `%e` over hard-coding an extension like
`.pdf`, which would mislabel a `.ps` or `.epub` attachment; `%e`
renders identically for PDFs and stays correct for everything else.

(specifiers-differences)=

## Differences from BibDesk

- `%i{Key}` (BibDesk *document info*) is recognized but raises
  `NotImplementedError`: `bibdeskparser` does not currently model the
  `@bibdesk_info` block in which BibDesk stores document-level
  metadata.
- BibDesk applies its *Preferences → Cite Key* and *Preferences →
  AutoFile* options; the equivalents here are the `format_spec`,
  `lowercase`, and `clean` keys of the `[auto_key]` and `[auto_file]`
  configuration tables. BibDesk's two strictest file-name cleaning
  levels (Windows-safe characters, and lossy ASCII) have no
  equivalent; `clean` stops at `"tex"`.
- BibDesk files attachments into its global *Papers Folder*
  preference, falling back to the document's own directory when it is
  empty. The equivalent here is the `location` key of `[auto_file]`,
  whose default `"."` (the `.bib` file's directory) corresponds to
  the empty Papers Folder.
- BibDesk has a single, global cite-key format and a single file-name
  format. Here, `format_spec` may instead be a
  [per-type mapping](config-auto-key) that applies a different format
  to each entry type — a `bibdeskparser` extension.
- The `[initials]` exception mapping for `%c` is a `bibdeskparser`
  extension; BibDesk always uses the plain acronym.
