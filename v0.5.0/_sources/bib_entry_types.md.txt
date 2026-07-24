(bib-entry-types)=

# Bib Entry Types

`bibdeskparser` recognizes the entry types that
[BibDesk](https://bibdesk.sourceforge.io) itself defines. These are the
types BibDesk templates in its editor, declared in its `TypeInfo.plist`
source file (the `FieldsForTypes` dictionary), which is the authority
for the per-type field lists reproduced below.

Every entry type is validated when an entry is *constructed or
modified* in Python -- {class}`~bibdeskparser.Entry` construction or an
`entry_type` assignment. An unrecognized entry type raises a
{exc}`ValueError`. **Loading a `.bib` file never validates**, so a file
using an unusual entry type still loads and round-trips unchanged.

Assigning a field that is not appropriate for the entry type emits a
{exc}`UserWarning` (the value is still stored). A field is appropriate
if it is one of the type's mandatory or optional fields listed below, or
one of the [fields common to all entry types](#common-fields).

The extended biblatex entry types and fields are also recognized
(accepted without error), though only the types below are given field
templates.

The recognized types and fields, and the two validation behaviors
described above, can be customized or disabled through a configuration
file; see [Configuration](configuration).

## Overview

| Type | Description |
|------|-------------|
| [`article`](#type-article) | An article in a journal or other periodical. |
| [`book`](#type-book) | A book with a named publisher. |
| [`booklet`](#type-booklet) | A printed work without a named publisher. |
| [`commented`](#type-commented) | A commented edition of a work. |
| [`conference`](#type-conference) | An article in conference proceedings (classic BibTeX). |
| [`electronic`](#type-electronic) | An electronic or online resource. |
| [`glossdef`](#type-glossdef) | A glossary definition. |
| [`inbook`](#type-inbook) | A part of a book with its own identity. |
| [`incollection`](#type-incollection) | A titled contribution to a book. |
| [`inproceedings`](#type-inproceedings) | An article in conference proceedings. |
| [`jurthesis`](#type-jurthesis) | A juridical thesis. |
| [`manual`](#type-manual) | Technical documentation. |
| [`mastersthesis`](#type-mastersthesis) | A master's thesis. |
| [`misc`](#type-misc) | A fallback type for anything that fits no other type. |
| [`periodical`](#type-periodical) | A whole issue or run of a periodical. |
| [`phdthesis`](#type-phdthesis) | A PhD thesis. |
| [`proceedings`](#type-proceedings) | The proceedings of a conference. |
| [`techreport`](#type-techreport) | A report issued by an institution. |
| [`unpublished`](#type-unpublished) | A work with an author and title, not formally published. |
| [`url`](#type-url) | A URL resource. |
| [`webpage`](#type-webpage) | A web page. |

(type-article)=

## article

An article in a journal, magazine, or other periodical.

**Mandatory:** `author`, `title`, `journal`, `year`

**Optional:** `volume`, `number`, `pages`, `month`

(type-book)=

## book

A book with a named publisher.

**Mandatory:** `title`, `publisher`, `year`

**Optional:** `author`, `editor`, `volume`, `number`, `series`,
`address`, `edition`, `month`

(type-booklet)=

## booklet

A printed work without a named publisher or sponsoring institution.

**Mandatory:** `title`

**Optional:** `author`, `howpublished`, `address`, `month`, `year`

(type-commented)=

## commented

A commented edition of a work.

**Mandatory:** `author`, `title`, `publisher`, `year`

**Optional:** `volumetitle`, `editor`

(type-conference)=

## conference

An article in conference proceedings (the classic BibTeX type;
equivalent to [`inproceedings`](#type-inproceedings)).

**Mandatory:** `author`, `title`, `booktitle`, `year`

**Optional:** `editor`, `volume`, `pages`, `number`, `organization`,
`series`, `publisher`, `address`, `month`

(type-electronic)=

## electronic

An electronic or online resource.

**Mandatory:** *(none)*

**Optional:** `urldate`, `author`, `title`

(type-glossdef)=

## glossdef

A glossary definition (a term and its meaning).

**Mandatory:** `word`, `definition`

**Optional:** `sort-word`, `short`, `group`

(type-inbook)=

## inbook

A part of a book (a chapter or a range of pages) with its own identity.

**Mandatory:** `title`, `publisher`, `year`

**Optional:** `editor`, `author`, `chapter`, `number`, `volume`, `type`,
`series`, `month`, `address`, `edition`, `pages`

(type-incollection)=

## incollection

A titled contribution to a book (a collection with its own editor).

**Mandatory:** `author`, `title`, `booktitle`, `publisher`, `year`

**Optional:** `editor`, `volume`, `number`, `series`, `type`, `chapter`,
`pages`, `address`, `edition`, `month`

(type-inproceedings)=

## inproceedings

An article in conference proceedings.

**Mandatory:** `author`, `title`, `booktitle`, `year`

**Optional:** `editor`, `volume`, `pages`, `number`, `organization`,
`series`, `publisher`, `address`, `month`

(type-jurthesis)=

## jurthesis

A juridical thesis.

**Mandatory:** `author`, `title`, `school`, `year`

**Optional:** `address`, `month`, `type`

(type-manual)=

## manual

Technical or other documentation, not necessarily in book form.

**Mandatory:** `title`

**Optional:** `author`, `organization`, `address`, `edition`, `month`,
`year`

(type-mastersthesis)=

## mastersthesis

A master's thesis.

**Mandatory:** `author`, `title`, `school`, `year`

**Optional:** `address`, `month`, `type`

(type-misc)=

## misc

A fallback type for anything that does not fit another type.

**Mandatory:** *(none)*

**Optional:** `title`, `howpublished`, `author`, `month`, `year`

(type-periodical)=

## periodical

A whole issue or run of a journal, magazine, or newspaper.

**Mandatory:** `author`, `title`, `journal`

**Optional:** `year`, `volume`, `pages`

(type-phdthesis)=

## phdthesis

A PhD thesis.

**Mandatory:** `author`, `title`, `school`, `year`

**Optional:** `address`, `month`, `type`

(type-proceedings)=

## proceedings

The published proceedings of a conference.

**Mandatory:** `title`, `year`

**Optional:** `editor`, `number`, `publisher`, `organization`,
`address`, `month`, `volume`

(type-techreport)=

## techreport

A report published by a school or other institution.

**Mandatory:** `author`, `title`, `institution`, `year`

**Optional:** `type`, `number`, `address`, `month`

(type-unpublished)=

## unpublished

A work with an author and title that has not been formally published.

**Mandatory:** `author`, `note`, `title`

**Optional:** `month`, `year`

(type-url)=

## url

A URL resource.

**Mandatory:** *(none)*

**Optional:** `urldate`, `author`, `title`, `lastchecked`

(type-webpage)=

## webpage

A web page.

**Mandatory:** `url`

**Optional:** `lastchecked`, `year`, `month`

(common-fields)=

## Fields common to all entry types

Beyond the per-type fields above, `bibdeskparser` accepts a set of
administrative and cross-type fields on *any* entry type, without a
warning. These are the fields BibDesk (and BibTeX in general) may attach
to an entry regardless of its type:

- `keywords` -- the comma-separated tag list, exposed as the
  {attr}`~bibdeskparser.Entry.keywords` tuple.
- `abstract`, `annote`, `annotation`, `note` -- free-form descriptive
  and note fields.
- `date`, `date-added`, `date-modified` -- timestamps; the latter two
  are exposed as the read-only {attr}`~bibdeskparser.Entry.date_added`
  and {attr}`~bibdeskparser.Entry.date_modified` properties.
- `doi`, `url`, `isbn`, `issn` -- stable identifiers and links.
- `eprint`, `eprinttype`, `eprintclass`, `archiveprefix`,
  `primaryclass` -- the arXiv/eprint fields.
- `crossref`, `ids` -- cross-referencing and alias keys.
- `language`, `rating`, `read`, `rss-description`, `local-url` --
  further BibDesk bookkeeping fields.

Some of these are surfaced through dedicated `bibdeskparser` API rather
than the plain `dict` interface:

- **File attachments** (`bdsk-file-N`) are managed through
  {meth}`~bibdeskparser.Library.add_file`,
  {meth}`~bibdeskparser.Library.replace_file`,
  {meth}`~bibdeskparser.Library.unlink_file`, and
  {meth}`~bibdeskparser.Library.rename_file`.
- **Linked URLs** (`bdsk-url-N`) are managed through
  {meth}`~bibdeskparser.Entry.add_url`,
  {meth}`~bibdeskparser.Entry.replace_url`, and
  {meth}`~bibdeskparser.Entry.remove_url`.
- **Timestamps** are read through
  {attr}`~bibdeskparser.Entry.date_added` and
  {attr}`~bibdeskparser.Entry.date_modified`.
- **Keywords** are read through
  {attr}`~bibdeskparser.Entry.keywords`.

For how these fields are encoded on disk, see the Explanation page
[BibDesk's `.bib` Format](bibdesk_format).

## Field glossary

A brief gloss of the field names used above:

`author`
: The author(s) of the work, an `and`-separated name list.

`editor`
: The editor(s) of the work, an `and`-separated name list.

`title`
: The title of the work.

`booktitle`
: The title of the book or proceedings a work appears in.

`journal`
: The name of the journal or periodical.

`publisher`
: The name of the publisher.

`school`
: The university or institution awarding a thesis.

`institution`
: The institution issuing a report.

`organization`
: The organization sponsoring a conference or manual.

`volume`
: The volume of a journal or a multi-volume book.

`number`
: The issue number of a journal, or the number in a series or report.

`pages`
: A page number or range of pages.

`series`
: The name of a series the work appears in.

`edition`
: The edition of a book.

`chapter`
: A chapter or section number.

`address`
: The address of the publisher or institution.

`month`
: The month of publication.

`year`
: The year of publication.

`type`
: An override for the type label of a thesis or report (e.g.
  `PhD diss.`).

`howpublished`
: How an unusual work was published.

`note`
: Free-form additional information.

`urldate`, `lastchecked`
: The date on which a URL was last accessed.

`word`, `definition`
: For [`glossdef`](#type-glossdef): the term and its meaning.

`sort-word`
: For [`glossdef`](#type-glossdef): the string the entry sorts under.

`short`
: For [`glossdef`](#type-glossdef): an abbreviated form of the term.

`group`
: For [`glossdef`](#type-glossdef): a grouping label.

`volumetitle`
: For [`commented`](#type-commented): the title of a specific volume.
</content>
</invoke>
