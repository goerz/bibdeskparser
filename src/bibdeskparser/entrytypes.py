"""The built-in entry-type and field-name data model (constants only).

This module holds the entry types and field names that `bibdeskparser`
recognizes by default. `DOCUMENTED_TYPES` mirrors the per-type
required/optional fields BibDesk defines in its `TypeInfo.plist`;
`RECOGNIZED_ENTRY_TYPES` additionally accepts the extended data-model
types, and `KNOWN_FIELDS` the extended field names. These constants
seed the *active* configuration (`bibdeskparser.config.active`), which
a `bibdeskparser.toml` may extend or replace at runtime and which the
validation methods (`Config.normalize_entry_type`,
`Config.field_is_appropriate`) consult.
"""

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "BIBLATEX_ENTRY_TYPES",
    "DOCUMENTED_TYPES",
    "DOCUMENTED_ENTRY_TYPES",
    "RECOGNIZED_ENTRY_TYPES",
    "UNIVERSAL_FIELDS",
    "KNOWN_FIELDS",
]

# The entry types and fields below are derived from the biblatex data
# model as declared in blx-dm.def (\DeclareDatamodelEntrytypes,
# \DeclareDatamodelFields, \DeclareDatamodelEntryfields, and the
# auto-generated date-part fields).

#: The biblatex data-model entry types (all lowercase).
BIBLATEX_ENTRY_TYPES = frozenset(
    (
        "article",
        "artwork",
        "audio",
        "bibnote",
        "book",
        "bookinbook",
        "booklet",
        "collection",
        "commentary",
        "customa",
        "customb",
        "customc",
        "customd",
        "custome",
        "customf",
        "dataset",
        "image",
        "inbook",
        "incollection",
        "inproceedings",
        "inreference",
        "jurisdiction",
        "legal",
        "legislation",
        "letter",
        "manual",
        "misc",
        "movie",
        "music",
        "mvbook",
        "mvcollection",
        "mvproceedings",
        "mvreference",
        "online",
        "patent",
        "performance",
        "periodical",
        "proceedings",
        "reference",
        "report",
        "review",
        "set",
        "software",
        "standard",
        "suppbook",
        "suppcollection",
        "suppperiodical",
        "thesis",
        "unpublished",
        "video",
        "xdata",
    )
)

# The entry types BibDesk itself templates, with the required and
# optional fields it shows in its editor for each. Taken verbatim from
# BibDesk's TypeInfo.plist (the `FieldsForTypes` dictionary), lowercased.
# These are the "documented" types (each has its own section on the
# entry-types reference page); other recognized types (see
# RECOGNIZED_ENTRY_TYPES) are accepted but not templated here.
#: Per-type required/optional fields, as defined by BibDesk.
DOCUMENTED_TYPES = {
    "article": {
        "required": ("author", "title", "journal", "year"),
        "optional": ("volume", "number", "pages", "month"),
    },
    "book": {
        "required": ("title", "publisher", "year"),
        "optional": (
            "author",
            "editor",
            "volume",
            "number",
            "series",
            "address",
            "edition",
            "month",
        ),
    },
    "booklet": {
        "required": ("title",),
        "optional": ("author", "howpublished", "address", "month", "year"),
    },
    "commented": {
        "required": ("author", "title", "publisher", "year"),
        "optional": ("volumetitle", "editor"),
    },
    "conference": {
        "required": ("author", "title", "booktitle", "year"),
        "optional": (
            "editor",
            "volume",
            "pages",
            "number",
            "organization",
            "series",
            "publisher",
            "address",
            "month",
        ),
    },
    "electronic": {
        "required": (),
        "optional": ("urldate", "author", "title"),
    },
    "glossdef": {
        "required": ("word", "definition"),
        "optional": ("sort-word", "short", "group"),
    },
    "inbook": {
        "required": ("title", "publisher", "year"),
        "optional": (
            "editor",
            "author",
            "chapter",
            "number",
            "volume",
            "type",
            "series",
            "month",
            "address",
            "edition",
            "pages",
        ),
    },
    "incollection": {
        "required": ("author", "title", "booktitle", "publisher", "year"),
        "optional": (
            "editor",
            "volume",
            "number",
            "series",
            "type",
            "chapter",
            "pages",
            "address",
            "edition",
            "month",
        ),
    },
    "inproceedings": {
        "required": ("author", "title", "booktitle", "year"),
        "optional": (
            "editor",
            "volume",
            "pages",
            "number",
            "organization",
            "series",
            "publisher",
            "address",
            "month",
        ),
    },
    "jurthesis": {
        "required": ("author", "title", "school", "year"),
        "optional": ("address", "month", "type"),
    },
    "manual": {
        "required": ("title",),
        "optional": (
            "author",
            "organization",
            "address",
            "edition",
            "month",
            "year",
        ),
    },
    "mastersthesis": {
        "required": ("author", "title", "school", "year"),
        "optional": ("address", "month", "type"),
    },
    "misc": {
        "required": (),
        # `journal` is not a classic BibTeX field for `misc` (every
        # style ignores it there), but the recommended storage form
        # for a preprint-only entry is `@misc` with a pseudo-journal
        # like `journal = {arXiv:2205.15044}`.
        "optional": (
            "title",
            "howpublished",
            "author",
            "month",
            "year",
            "journal",
        ),
    },
    "periodical": {
        "required": ("author", "title", "journal"),
        "optional": ("year", "volume", "pages"),
    },
    "phdthesis": {
        "required": ("author", "title", "school", "year"),
        "optional": ("address", "month", "type"),
    },
    "proceedings": {
        "required": ("title", "year"),
        "optional": (
            "editor",
            "number",
            "publisher",
            "organization",
            "address",
            "month",
            "volume",
        ),
    },
    "techreport": {
        "required": ("author", "title", "institution", "year"),
        "optional": ("type", "number", "address", "month"),
    },
    "unpublished": {
        "required": ("author", "note", "title"),
        # `journal` is not a classic BibTeX field for `unpublished`
        # (every style ignores it there), but the canonical storage
        # form for a preprint-only entry is `@unpublished` with a
        # pseudo-journal like `journal = {arXiv:2205.15044}`.
        "optional": ("month", "year", "journal"),
    },
    "url": {
        "required": (),
        "optional": ("urldate", "author", "title", "lastchecked"),
    },
    "webpage": {
        "required": ("url",),
        "optional": ("lastchecked", "year", "month"),
    },
}

#: The entry types documented (and templated) on the reference page.
DOCUMENTED_ENTRY_TYPES = frozenset(DOCUMENTED_TYPES)

# Administrative / cross-type fields that BibDesk (and BibTeX in
# general) may attach to an entry of any type; assigning one of these
# never counts as "inappropriate for the type".
#: Fields accepted on every entry type without a warning.
UNIVERSAL_FIELDS = frozenset(
    (
        "keywords",
        "abstract",
        "annote",
        "annotation",
        "note",
        "doi",
        "url",
        "isbn",
        "issn",
        "language",
        "date",
        "date-added",
        "date-modified",
        "local-url",
        "rating",
        "read",
        "rss-description",
        "crossref",
        "ids",
        "eprint",
        "eprinttype",
        "eprintclass",
        "archiveprefix",
        "primaryclass",
        "archive",
    )
)

# The biblatex data-model field names (global fields, per-entry-type
# fields, and auto-generated date-part fields), all lowercase.
_BIBLATEX_FIELDS = frozenset(
    (
        "abstract",
        "addendum",
        "afterword",
        "annotation",
        "annotator",
        "author",
        "authortype",
        "bookauthor",
        "bookpagination",
        "booksubtitle",
        "booktitle",
        "booktitleaddon",
        "chapter",
        "commentator",
        "crossref",
        "date",
        "day",
        "doi",
        "edition",
        "editor",
        "editora",
        "editoratype",
        "editorb",
        "editorbtype",
        "editorc",
        "editorctype",
        "editortype",
        "eid",
        "endday",
        "endhour",
        "endminute",
        "endmonth",
        "endsecond",
        "endtimezone",
        "endyear",
        "endyeardivision",
        "entryset",
        "entrysubtype",
        "eprint",
        "eprintclass",
        "eprinttype",
        "eventdate",
        "eventday",
        "eventendday",
        "eventendhour",
        "eventendminute",
        "eventendmonth",
        "eventendsecond",
        "eventendtimezone",
        "eventendyear",
        "eventendyeardivision",
        "eventhour",
        "eventminute",
        "eventmonth",
        "eventsecond",
        "eventtimezone",
        "eventtitle",
        "eventtitleaddon",
        "eventyear",
        "eventyeardivision",
        "execute",
        "file",
        "foreword",
        "gender",
        "holder",
        "hour",
        "howpublished",
        "ids",
        "indexsorttitle",
        "indextitle",
        "institution",
        "introduction",
        "isan",
        "isbn",
        "ismn",
        "isrn",
        "issn",
        "issue",
        "issuesubtitle",
        "issuetitle",
        "issuetitleaddon",
        "iswc",
        "journalsubtitle",
        "journaltitle",
        "journaltitleaddon",
        "keywords",
        "label",
        "langid",
        "langidopts",
        "language",
        "library",
        "lista",
        "listb",
        "listc",
        "listd",
        "liste",
        "listf",
        "location",
        "mainsubtitle",
        "maintitle",
        "maintitleaddon",
        "minute",
        "month",
        "namea",
        "nameaddon",
        "nameatype",
        "nameb",
        "namebtype",
        "namec",
        "namectype",
        "note",
        "number",
        "options",
        "organization",
        "origdate",
        "origday",
        "origendday",
        "origendhour",
        "origendminute",
        "origendmonth",
        "origendsecond",
        "origendtimezone",
        "origendyear",
        "origendyeardivision",
        "orighour",
        "origlanguage",
        "origlocation",
        "origminute",
        "origmonth",
        "origpublisher",
        "origsecond",
        "origtimezone",
        "origtitle",
        "origyear",
        "origyeardivision",
        "pages",
        "pagetotal",
        "pagination",
        "part",
        "presort",
        "publisher",
        "pubstate",
        "related",
        "relatedoptions",
        "relatedstring",
        "relatedtype",
        "reprinttitle",
        "second",
        "series",
        "shortauthor",
        "shorteditor",
        "shorthand",
        "shorthandintro",
        "shortjournal",
        "shortseries",
        "shorttitle",
        "sortkey",
        "sortname",
        "sortshorthand",
        "sorttitle",
        "sortyear",
        "subtitle",
        "timezone",
        "title",
        "titleaddon",
        "translator",
        "type",
        "url",
        "urldate",
        "urlday",
        "urlendday",
        "urlendhour",
        "urlendminute",
        "urlendmonth",
        "urlendsecond",
        "urlendtimezone",
        "urlendyear",
        "urlendyeardivision",
        "urlhour",
        "urlminute",
        "urlmonth",
        "urlsecond",
        "urltimezone",
        "urlyear",
        "urlyeardivision",
        "usera",
        "userb",
        "userc",
        "userd",
        "usere",
        "userf",
        "venue",
        "verba",
        "verbb",
        "verbc",
        "version",
        "volume",
        "volumes",
        "xdata",
        "xref",
        "year",
        "yeardivision",
    )
)

# Classic BibTeX field aliases (biblatex maps these onto data-model
# fields) plus BibDesk's own internal/default fields, from BibDesk's
# BDSKStringConstants.m. Most classic BibTeX field names are already in
# the biblatex data model; the ones added here are the aliases
# (address/journal/annote/school) and BibDesk-specific fields.
_BIBDESK_FIELDS = frozenset(
    (
        "address",
        "journal",
        "annote",
        "school",
        "local-url",
        "rss-description",
        "rating",
        "read",
        "date-added",
        "date-modified",
        "date",
        "url",
        "keywords",
        "abstract",
        "chapter",
        "edition",
        "howpublished",
        "institution",
        "month",
        "note",
        "number",
        "organization",
        "pages",
        "publisher",
        "series",
        "title",
        "type",
        "volume",
        "year",
        "author",
        "editor",
        "booktitle",
        "crossref",
        "doi",
        "isbn",
        "issn",
        # arXiv BibTeX fields (biblatex maps these onto eprinttype /
        # eprintclass); common enough that warning about them would be
        # noise.
        "archiveprefix",
        "primaryclass",
    )
)

#: All recognized field names (lowercase): the classic BibTeX/BibDesk
#: fields together with the extended data-model fields.
KNOWN_FIELDS = _BIBLATEX_FIELDS | _BIBDESK_FIELDS

#: Entry types accepted by `Config.normalize_entry_type`: the types
#: BibDesk templates (`DOCUMENTED_ENTRY_TYPES`) plus the extended
#: data-model types. Any type outside this set raises `ValueError` on
#: construction.
RECOGNIZED_ENTRY_TYPES = DOCUMENTED_ENTRY_TYPES | BIBLATEX_ENTRY_TYPES
