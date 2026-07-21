# Preprints

Preprint servers like [arXiv](https://arxiv.org),
[bioRxiv](https://www.biorxiv.org), [medRxiv](https://www.medrxiv.org),
[ChemRxiv](https://chemrxiv.org), [HAL](https://hal.science),
or [SSRN](https://www.ssrn.com) are a routine part of scholarly
publishing, but the original BibTeX had no notion of them: there is no
`@preprint` entry type, and no standard field for a preprint
identifier. Several competing conventions have grown up to fill the
gap, and none of them works everywhere. This page surveys those
conventions, explains the one `bibdeskparser` recommends and
implements, and spells out its tradeoffs.

## Encoding preprints in BibTeX

The choices for representing a preprint as an entry in a `.bib` file are
guided by pragmatism and the limitation of particular BibTeX `.bst` styles.
The first choice is which entry type to use for a preprint.
As far as [standard entry types](https://www.bibtex.com/e/entry-types/) go,
the potential candidates are `@unpublished`, `@misc`, or `@article`.
[BibLaTeX](https://ctan.org/pkg/biblatex) has
[additional types](https://tex.stackexchange.com/questions/639734/canonical-list-of-bib-entry-types),
like `@online`, but these are not supported by more traditional
tooling.

The second question is in which _fields_ to encode the preprint
information. Styles only take into account standard fields (fields
they _know_ about, that is), and silently ignore all other data. For
older styles, the list of fields is rather short.

### The structured `eprint` fields

The modern de-facto standard for machine-readable preprint
information is the `eprint` field family: `eprint` holds the
identifier, `archiveprefix` names the server (assumed to be arXiv
when absent), `primaryclass` gives the arXiv category (e.g.,
`quant-ph`), and a fourth, `archive`, gives the base URL of the
server's identifier pages (see [below](preprints-archive-field)).
The convention originated with the SLAC/SPIRES database (today's
[INSPIRE-HEP](https://inspirehep.net)) and the first three fields
are included in arXiv's own "Export BibTeX citation". It is fully
supported by many slightly more modern styles, and most importantly
by [REVTeX](https://journals.aps.org/revtex)'s
`apsrev4-x`/`aipnum4-x`, by Elsevier's `elsarticle` styles, by
[biblatex](https://ctan.org/pkg/biblatex) (which reads
`archiveprefix`/`primaryclass` as aliases for its native
`eprinttype`/`eprintclass` fields, on any entry type, and hyperlinks
`arXiv: 2205.15044 [quant-ph]` by default), and by classic styles
retrofitted with [urlbst](https://ctan.org/pkg/urlbst).

The catch is that under the plain classic styles the fields are
invisible: with `plain`, `unsrt`, `abbrv`, `alpha`, the natbib
variants, or `IEEEtran`, an entry whose identifier lives only in
`eprint` renders as just "Author. Title, year." -- the identifier is
dropped without a trace.

Thus, for use with older styles that do not support these fields, preprint
information must be additionally included in one of the standard fields.
For styles that _do_ support `eprint`, the way the information is rendered
still depends on which entry type is used.

As a concrete example,
{download}`preprints.pdf <preprint_rendering_tex/preprints.pdf>`
renders fourteen variants of the same references -- an arXiv
preprint-only paper, a HAL preprint-only paper, and a published
paper with a preprint -- in one REVTeX document (`revtex4-2` with
the default `apsrev4-2` style and `hyperref` loaded).

### Using `@unpublished` for preprints

A preprint-only work has, by definition, not been published, so
`@unpublished` is arguably a "semantically accurate" type. However,
unlike the other possible entry types, `@unpublished` _requires_ a
`note` field in every classic style. This represents both an
opportunity and a challenge. If the style does not support the
`eprint` fields, then putting the preprint information in the note
as plain text, `note = {arXiv:2205.15044}`, would be appropriate.
The drawback is that this is unstructured text: nothing hyperlinks
it, and reference managers cannot parse it back out. Moreover, a
`note` is usually positioned at the end of the citation instead of
as "venue" between title and year, which may be undesired (and
`@unpublished` ignores `howpublished`).

When the style does support the `eprint` field and renders it
independently, the "challenge" is what to put in the mandatory
`note` field. An attractive option is to use the `note` for the
publication *status*, e.g. "preprint" for preprints that have not
yet been submitted, "submitted" or "submitted to Phys. Rev. A" for
preprints that are known to have been submitted, and a more
descriptive note like "unpublished report" or "lecture notes" for
material that has been uploaded to arXiv without the intention of
publishing it as a peer-reviewed article.

REVTeX in particular (see
{download}`preprints.pdf <preprint_rendering_tex/preprints.pdf>`)
renders this combination best of any option: the hyperlinked,
category-tagged `eprint` moves into the venue position, before the
publication year, followed by the note ("arXiv:2003.10132 [quant-ph]
(2020), lecture notes"). This makes `@unpublished` by far the most
attractive and richly featured option, as long as one is okay with
defining a `note`.

### Using `@misc` for preprints

`@misc` with the `eprint` fields is what arXiv's own "Export BibTeX
citation" hands out. Its advantage over `@unpublished` is that
`@misc` has no mandatory fields, i.e., no required `note` field. If
a `note` field (and/or a `howpublished` field) is present, it is
rendered. However (at least in REVTeX), the _placement_ is different
from `@unpublished`: The `eprint` information is not in the "venue"
location, but instead after the `note`. Instead, `howpublished`
takes the "venue" location. This makes `@misc` acceptable for styles
that do not support `eprint`. The preprint information should be
stored in `howpublished`.

If the style does support `eprint`, it would render the information
redundantly with `howpublished`, so `howpublished` should be omitted
in that scenario. The result will be properly linked, but the
preprint information will not appear in the "venue" slot.

### Using `@article` for preprints

The last option abandons the eprint fields and instead puts the
preprint reference directly in the `journal` field of a regular
`@article`, e.g. `journal = {arXiv:2205.15044}` (Google Scholar's
BibTeX export popularized a variant of this). No style guide documents
the practice, but it buys the one thing the structured forms cannot
guarantee: *every* BibTeX style renders an article's `journal`, so the
identifier is never dropped. The citation comes out essentially as

> M. H. Goerz *et al.*, "Quantum optimal control via semi-automatic
> differentiation", arXiv:2205.15044 (2022)

under `plain`, `unsrt`, `IEEEtran`, and REVTeX alike -- the preprint
reference formatted exactly like a journal reference, which is how
readers actually treat it.

What it gives up is structure. Because the identifier is plain text
in `journal`, the rendering shows "arXiv:2205.15044 (2022)",
unlinked by default. Proper linking may be reproduced by having a
`url` field pointing to the URL of the preprint. Using a
"pseudo-journal" like this is a double-edged sword: In a tool like
BibDesk, we can potentially filter on the `arXiv` prefix, but any
tool that reads `journal` strictly as a venue name
(journal-abbreviation pipelines, reference-manager imports) may be
misled by it.

Like `@misc` with `howpublished`, any `eprint` field should be
omitted, or used exclusively with styles that do not support
`eprint`. Otherwise, the preprint information will be presented
redundantly in the resulting bibliography.

### Nonstandard BibLaTeX types

Under [BibLaTeX](https://ctan.org/pkg/biblatex), an `@online` entry with the
structured eprint fields renders and hyperlinks natively, in the right place,
with the category tag, and without a required `note` to leave empty.

The `bibdeskparser` library does not build around a non-standard
type like `@online` because BibDesk at its heart is a classic-BibTeX
program. Its preview pane runs real `bibtex`, not `biber`, and a
`.bib` database maintained for years across collaborations and
journal submission systems cannot assume that every document
downstream of it will use biblatex. An `@online` entry that renders
beautifully under biblatex degrades to "Author. Title, year." the
moment someone feeds the same file to `plain` or `IEEEtran`. The
stored form therefore stays within classic BibTeX; biblatex reads
the `eprint` fields it carries anyway.

(preprints-convention)=

## How `bibdeskparser` stores preprint-only entries

`bibdeskparser` stores a preprint-only work as an `@unpublished`
entry that carries the structured `eprint` fields, a pseudo-journal,
the DOI, and a publication-status note:

```bibtex
@unpublished{Wilhelm2003.10132,
    Author = {Wilhelm, Frank K. and others},
    Title = {An introduction into optimal control for quantum technologies},
    Journal = {arXiv:2003.10132},
    Eprint = {2003.10132},
    Archiveprefix = {arXiv},
    Primaryclass = {quant-ph},
    Doi = {10.48550/arxiv.2003.10132},
    Note = {preprint only},
    Year = {2020},
}
```

The `journal` value has the fixed shape `<Archive>:<identifier>` -- a
*pseudo-journal*. The recognized archives (arXiv, bioRxiv, medRxiv,
ChemRxiv, HAL, and SSRN by default) are configurable via the
[`[preprint_archives]` table](config-preprint-archives). Since arXiv
[assigns a DOI](https://info.arxiv.org/help/doi.html)
(`10.48550/arXiv.<identifier>`) to every preprint, and
bioRxiv/medRxiv/ChemRxiv/SSRN identifiers are DOI-based to begin
with, essentially every preprint-only entry can carry a `doi`; HAL
deposits carry a stable URL instead.

The stored form redundantly combines fields that are relevant to
different choices for exported entry types. The `@unpublished` type
with the eprint fields is both semantically accurate and the
best-rendering REVTeX form, so the stored entry can be copied
*verbatim* into an external `.bib` file (the extra `journal` field is
ignored on `@unpublished`), and BibDesk's preview pane, which runs
real BibTeX, shows the same clean rendering. The `note` records the
publication status -- "preprint only", "submitted to Phys. Rev. A",
"lecture notes" -- which renders in every BibTeX style and satisfies
`@unpublished`'s required-field check; `bibdeskparser` *never* fills
it in automatically in the database, so a missing note (which BibDesk
flags as an incomplete required field) is a deliberate signal to
record the status by hand. The pseudo-journal gives the entry a venue
inside the database: BibDesk's table view shows `arXiv:2003.10132`
in its journal column. The `doi`, last, is the canonical identifier
for duplicate detection and the preferred hyperlink target.

{py:meth}`~bibdeskparser.Library.import_bibtex` (and
{py:meth}`~bibdeskparser.Library.add`) normalize incoming
preprint-only entries into this form. Recognition does not depend on
any single marker: an entry is preprint-only if its `journal` is a
recognized pseudo-journal (any entry type -- including the earlier
`@article`-based form of this convention), or if it is a `@misc` or
`@unpublished` entry with an `eprint` from a recognized archive
(e.g. arXiv's own BibTeX export). Everything derivable is derived --
the pseudo-journal from the `eprint` or vice versa, the `doi` from a
`doi.org` resolver URL or (for arXiv) from the identifier itself --
and a `url` that merely restates the archive's page for the
identifier is dropped when the entry carries a `doi`. Only the
`note` is never derived.

## Exporting preprint-only entries

When {py:meth}`~bibdeskparser.Library.export` writes a preprint-only
entry (of any stored form) for use with LaTeX, one choice remains,
and it depends on the *bibliography style* the document will use --
does it render the `eprint` field, or silently drop it? That choice
is the `preprint` parameter of `export` (`--preprint` on the command
line), with the default set by the
[`preprint_export` setting](config-preprint-export):

* `preprint="unpublished"` (the built-in default): `@unpublished`
  with `eprint`/`archiveprefix`/`primaryclass` and the `doi`. Under
  REVTeX (`apsrev4-x`, `aipnum4-x`) this is the best-rendering form
  (venue-position identifier, category tag, status note); it is
  equally understood by `elsarticle` and biblatex. Minimal exports
  guarantee the required `note`: the stored one, or the synthesized
  text "preprint" for an entry without one (full exports never
  synthesize it, so that re-importing a full export cannot plant a
  note in a library).
* `preprint="misc"`: the same structured fields as a `@misc` entry
  -- the form arXiv itself exports. Equivalent information; the
  eprint renders after the year instead of in the venue position,
  and there is no required `note`.
* `preprint="article"`: the pseudo-journal form -- `@article` with
  `journal = {arXiv:2003.10132}` and the DOI written as its resolver
  address in `url`. Use this for classic styles (`plain`, `unsrt`,
  `abbrv`, `IEEEtran`, ...), where the structured forms would lose
  the identifier entirely.
* `preprint="stored"`: no transformation, for inspecting the entry
  as stored.

Every form derives whatever it needs (`eprint` from the
pseudo-journal or vice versa), so all stored forms export
identically; minimal exports reduce to the essential fields of the
chosen form -- always including `eprint`/`archiveprefix` for the
structured forms, and always keeping a stored `note`. The stored
entry itself never changes.

(preprints-archive-field)=

## The `archive` field

REVTeX's `apsrev4-x`/`aipnum4-x` styles construct the hyperlink of a
rendered eprint as `<archive>/<eprint>`, where `archive` is a
BibTeX field with the built-in default `https://arxiv.org/abs` --
the SPIRES-era companion of `eprint`/`archiveprefix` that modern
BibTeX exports no longer emit. For arXiv identifiers the default is
right; for any other archive it produces a broken link, and no other
field can compensate (`@unpublished` ignores `url` entirely).

`bibdeskparser` therefore emits the `archive` field automatically
wherever the structured eprint fields of a non-arXiv preprint are
exported: `Archive = {https://hal.science}` for a HAL identifier,
`Archive = {https://www.biorxiv.org/content/10.1101}` for bioRxiv,
and so on. The base URL is derived from the archive's URL template
in the [`[preprint_archives]` table](config-preprint-archives)
whenever the template has the form `<base>/{id}`; archives whose
page URLs embed the identifier differently (SSRN, ChemRxiv) get no
`archive` field -- for those, prefer the `article` export form,
whose link does not rely on the eprint machinery. A stored `archive`
field is always exported as-is; conversely, `import` drops an
`archive` field that matches the derivable base, since exports
regenerate it.

## Preprint information on *published* papers

Recording `eprint`/`archiveprefix` on a published paper is valuable:
The journal reference and DOI of a published article often lead to a
paywall, while the eprint link leads to a free copy, so a
bibliography that carries both serves every reader. High-energy
physics has done this for decades: INSPIRE-HEP retains the arXiv
identifier on every published record, and the SPIRES-era guidance
explicitly asked for identifiers "for both published and unpublished
papers". The styles cooperate, rendering both parts -- REVTeX's
`apsrev4-x` prints the journal reference *followed by* the
hyperlinked `arXiv:2205.15044 [quant-ph]`, biblatex does the
equivalent with `eprint=true` (its default), and `bibdeskparser`'s
own {py:meth}`~bibdeskparser.Library.render` does the same, with the
DOI-linked journal segment ahead of the eprint link. And it costs
almost nothing to keep up:
{py:meth}`~bibdeskparser.Library.add_preprint` searches arXiv for the
preprint matching a published entry and fills in the fields
automatically; see [](howto-add-preprint).

Minimal exports of published articles therefore include the
`eprint`/`archiveprefix`/`primaryclass` fields -- and, like full
exports, the `archive` link base when the preprint is on a
non-arXiv archive, so its link renders correctly.
