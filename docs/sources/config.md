(configuration)=

# Configuration

`bibdeskparser` can be configured with a
[TOML](https://toml.io) file named `bibdeskparser.toml`. The file
replicates some of the preferences that the BibDesk application itself
offers -- most importantly, which entry types and fields are considered
valid (see [Bib Entry Types](bib-entry-types)).

## Where the file is found

When `bibdeskparser` is imported, and again whenever a
{class}`~bibdeskparser.Library` is constructed, it searches for a
`bibdeskparser.toml` in the following locations, in order of
precedence. **The first file found wins**; the others are ignored.

1. The path assigned to the {class}`~bibdeskparser.Library`
   `config_file` class attribute, if any (see below). An explicit
   `config_file` that does not exist raises a {exc}`FileNotFoundError`.
2. The directory containing the `.bib` file that is being loaded (or
   the current working directory, for a library not loaded from a file
   -- and at import time).
3. The XDG configuration directory:
   `$XDG_CONFIG_HOME/bibdeskparser/bibdeskparser.toml`, falling back to
   `~/.config/bibdeskparser/bibdeskparser.toml` when `$XDG_CONFIG_HOME`
   is unset.

The configuration is applied **process-wide**: it affects every
{class}`~bibdeskparser.Entry`, whether or not it belongs to a library.

## The `verify_types` and `verify_fields` flags

Two boolean options, both defaulting to `true`, control validation:

```toml
verify_types = true
verify_fields = true
```

* `verify_types`: when `true` (the default), constructing an entry with
  an unrecognized type, or assigning such a type, raises a
  {exc}`ValueError`. Set it to `false` to accept any entry type (still
  lowercased).
* `verify_fields`: when `true` (the default), assigning a field that is
  not appropriate for an entry's type emits a {exc}`UserWarning` (the
  value is stored regardless). Set it to `false` to suppress those
  warnings entirely.

Both are also exposed as writable class attributes of
{class}`~bibdeskparser.Library`, so they can be changed from Python
without a configuration file:

```python
>>> from bibdeskparser import Library
>>> Library.verify_types
True
>>> Library.verify_types = False   # accept any entry type
>>> Library.verify_types = True    # restore the default
>>> Library.verify_types
True

```

`Library.config_file` (default `None`) is the third class attribute; set
it to a path to force that file to be used, ahead of directory-based
discovery. Note that constructing a `Library` re-applies whichever
configuration file is discovered, which overrides changes made directly
to these attributes; set the attributes *after* constructing a library,
or point `config_file` at a file, to make a setting stick.

## The `default_bib_file` option

A string option, unset by default, naming the `.bib` file that the
{ref}`command-line interface <cli>` operates on when no `BIBFILE`
argument is given:

```toml
default_bib_file = "$HOME/Documents/library.bib"
```

Environment variables (`$VAR`) and a leading `~` in the value are
expanded. The option has no effect on the Python API.

## Custom and extended entry types

A `[types.NAME]` table defines the mandatory (`required`) and optional
(`optional`) fields of an entry type, exactly like BibDesk's
per-type field templates. This both makes `NAME` a recognized entry
type and, when `verify_fields` is on, determines which fields are
considered appropriate for it.

For an entry type that is **not** already built in, the table simply
defines it:

```toml
[types.dataset]
required = ["author", "title", "year"]
optional = ["note", "url"]
```

For a type that **is** built in, the fields you list are *added* to the
built-in template by default:

```toml
[types.article]
optional = ["eprint"]   # article keeps its built-in fields, plus eprint
```

To discard the built-in template and define the type from scratch, set
`replace = true`:

```toml
[types.report]
replace = true
required = ["author", "title", "year"]
optional = ["note"]
```

## Custom fields

A `[fields]` table adds recognized field names without tying them to a
particular type:

```toml
[fields]
# accepted on every entry type, like keywords or note
universal = ["mycustomtag"]
# recognized, but not treated as universal
known = ["someotherfield"]
```

A `universal` field never triggers the inappropriate-field warning,
whatever the entry type. A `known` field is recognized for entry types
that have no field template of their own, but is not automatically
appropriate for a templated type.

## A complete example

```toml
# bibdeskparser.toml
verify_types = true
verify_fields = true

[types.dataset]              # a new entry type
required = ["author", "title", "year"]
optional = ["note", "url"]

[types.article]              # extend a built-in type
optional = ["eprint", "eprinttype"]

[fields]
universal = ["mytag"]
```
