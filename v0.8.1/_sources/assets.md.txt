(external-assets)=

# External Assets

BibDesk databases natively support file attachments, which are typically used to store the PDF file of the published paper.

However, a user may have additional files associated with the bibliography as a whole, or with particular entries: an extracted full text, a written summary, a folder with the paper source (extracted from arXiv), or library-level documents such as a thematic survey. The pragmatic convention is to keep such files next to the `.bib` file, named after the citation key: `GoerzQ2022_summary.md` obviously belongs to `GoerzQ2022`.

BibDeskParser can be configured to recognize and manage such "asset" files that are not tracked through the `.bib` file directly, through an [`[assets]` section in the config file](config-assets). It declares the path conventions, once, as patterns in the [format-specifier language](format-specifiers). For example:

```toml
[assets]
summary = "%f{Cite Key}_summary.md"
fulltext = "%f{Cite Key}.ingest/fulltext.md"
source = "%f{Cite Key}.ingest/source/"   # trailing slash: a directory
topics = "%i{Topics-File}"               # library-level
```

Each pattern is either an entry asset or a library asset, depending on which specifiers it uses: A pattern referencing entry data (`%f{Cite Key}`, `%a1`, `%Y`) is per-entry. A pattern built only from document info (`%i{Key}`), the document name (`%b`), and literal text is library-level: it belongs to no entry, resolves once for the database, and entry operations leave it alone.

With the patterns declared, the package resolves where an asset lives ({py:meth}`~bibdeskparser.Library.asset`), reports whether it is there ({py:meth}`~bibdeskparser.Library.assets`). The package also gains the ability to keep assets _consistent_ with the `.bib` file through key-changing operations ({py:meth}`~bibdeskparser.Library.rekey`, {py:meth}`~bibdeskparser.Library.delete`), and audits for files whose entry is gone (the [`check` command](cli-check)). The package never creates or reads asset *content*: producing summaries and conversions stays with external scripts and agents.

## Example

Consider the entry `GoerzQ2022` in a database whose library file is `refs.bib`, and the asset configuration is as above. Next to the `.bib` file live:

- `GoerzQ2022.pdf` (~950 KB): the published paper. An ordinary attachment (a `bdsk-file` link), not an asset -- BibDesk manages it, and it appears in {py:attr}`~bibdeskparser.Entry.files`.
- `GoerzQ2022_summary.md`: ~480 words of prose meant to be read, the `summary` asset. User-facing and durable: it represents invested work. Such summaries might be written by an agent and/or extended by hand. It would include notes on how the reference fits into a research program or how it relates to other entries.
- `GoerzQ2022.ingest/`: a bundle produced by an ingestion script, holding the paper as ~110 KB of markdown in `fulltext.md` (front matter, KaTeX math, `[@Key]` citations), the `source/` directory of upstream LaTeX it was converted from, and a `figures/` directory. The `fulltext` and `source` assets point into this bundle.
- `topics.md`: a library-level document whose sections cite entries by key -- the `topics` asset, resolved through the document-info key `Topics-File` (`bibdeskparser set_info "Topics-File" topics.md`).

The `[assets]` configuration then enables the following capabilities with the `bibdeskparser` CLI tool:

- `bibdeskparser asset fulltext GoerzQ2022` for a file reader to open the full text, failing outright when it is not there, or `--no-check-exists` for a generator to learn where to write one;
- `bibdeskparser assets --json $(bibdeskparser keys)` for coverage across the library: which entries have a summary, which still need ingestion;
- a `rekey GoerzQ2022 GoerzQ2022SAD` that renames the summary, moves the `.ingest` bundle as a whole (so `source/` and `figures/` travel along untouched), and re-files the PDF -- with either feature configurable (see [`[rekey]`](config-rekey-delete));
- a `check` that notices a `SomeOldKey_summary.md` whose entry is gone, and, with `--assets`, lists the entries whose assets are missing.

## Best practices: Asset Folders

A rename moves the *deepest* path component of a pattern that depends on the entry, and moves it as one unit: for both `%f{Cite Key}.ingest/fulltext.md` and `%f{Cite Key}.ingest/source/`, that is the `%f{Cite Key}.ingest` directory. Everything below it is carried along without being inspected, which is why a bundle can hold arbitrary files -- including a generator's own bookkeeping -- and still survive a `rekey` intact.

Thus, when assets include arbitrary or unpredictable filenames, it is a good idea to collect them in the folder whose name depends on the citation key, located near the root of the file system relative to the `bib` file. Inside this folder, the files can be named generically (`fulltext.md`, not `GoerzQ2022_fulltext.md`). Then one move renames the entry's whole asset directory, including any undeclared auxiliary files.

## Semantics

The `[assets]` mechanism attaches no semantics to class names and no schema to content. What is durable against what is re-derivable, who generates the material, the format or layout of each asset, are properties of your workflow, not of the database; the layout in the example above is one arrangement, not the prescribed one. Likewise, validating an asset's content (a summary's headings, a conversion's format) belongs to the tool that writes it.
