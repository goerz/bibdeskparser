"""Recognized entry types and field names, for validation.

This module holds the entry types and field names that `bibdeskparser`
recognizes. `DOCUMENTED_TYPES` mirrors the per-type required/optional
fields BibDesk defines in its `TypeInfo.plist`; `RECOGNIZED_ENTRY_TYPES`
additionally accepts the extended data-model types, and `KNOWN_FIELDS`
the extended field names. `normalize_entry_type` validates and
lowercases an entry type, and `field_is_appropriate` reports whether a
field name is appropriate for a given entry type (used to warn about
fields that do not belong on a type).
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
    "normalize_entry_type",
    "is_known_field",
    "field_is_appropriate",
    "set_active",
    "set_verify_types",
    "set_verify_fields",
    "reset_active",
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
        "optional": ("title", "howpublished", "author", "month", "year"),
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
        "optional": ("month", "year"),
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

#: Entry types accepted by `normalize_entry_type`: the types BibDesk
#: templates (`DOCUMENTED_ENTRY_TYPES`) plus the extended data-model
#: types. Any type outside this set raises `ValueError` on construction.
RECOGNIZED_ENTRY_TYPES = DOCUMENTED_ENTRY_TYPES | BIBLATEX_ENTRY_TYPES

# The constants above are the built-in *defaults*. The *active*
# configuration below starts as a copy of them, but the config-file
# machinery (`bibdeskparser.config`) may extend or replace it at runtime
# (see the "Configuration" reference page). The validation functions
# always consult the active configuration, never the defaults directly.


class _ActiveConfig:
    """The entry-type/field configuration currently in effect.

    Mutable, process-global state seeded from the built-in defaults and
    updated by `bibdeskparser.config` when a `bibdeskparser.toml` is
    loaded. `verify_types`/`verify_fields` toggle the two validation
    behaviors; the remaining attributes are the effective type/field
    tables. `_recompute` derives `type_fields` (the per-type union of
    required and optional fields) from `documented_types`.
    """

    # `reset` (not `__init__` directly) assigns all instance
    # attributes, so that `__init__` and a later `reset()` call share
    # the same logic.
    # pylint: disable=attribute-defined-outside-init

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all attributes to the built-in defaults."""
        self.verify_types = True
        self.verify_fields = True
        self.documented_types = {
            entry_type: {
                "required": tuple(spec["required"]),
                "optional": tuple(spec["optional"]),
            }
            for entry_type, spec in DOCUMENTED_TYPES.items()
        }
        self.recognized_entry_types = set(RECOGNIZED_ENTRY_TYPES)
        self.universal_fields = set(UNIVERSAL_FIELDS)
        self.known_fields = set(KNOWN_FIELDS)
        self._recompute()

    def _recompute(self):
        self.type_fields = {
            entry_type: frozenset(spec["required"])
            | frozenset(spec["optional"])
            for entry_type, spec in self.documented_types.items()
        }


_active = _ActiveConfig()


# The functions below assign attributes directly on the `_active`
# singleton from outside `_ActiveConfig`, by design (see its
# docstring).
# pylint: disable=attribute-defined-outside-init


def set_active(
    *,
    verify_types,
    verify_fields,
    documented_types,
    recognized_entry_types,
    universal_fields,
    known_fields,
):
    """Replace the active entry-type/field configuration.

    Called by `bibdeskparser.config` with the effective tables built
    from a `bibdeskparser.toml`. All arguments are keyword-only.
    """
    _active.verify_types = verify_types
    _active.verify_fields = verify_fields
    _active.documented_types = documented_types
    _active.recognized_entry_types = recognized_entry_types
    _active.universal_fields = universal_fields
    _active.known_fields = known_fields
    _active._recompute()


def set_verify_types(value):
    """Toggle entry-type validation on the active configuration."""
    _active.verify_types = bool(value)


def set_verify_fields(value):
    """Toggle field-appropriateness warnings on the active
    configuration."""
    _active.verify_fields = bool(value)


# pylint: enable=attribute-defined-outside-init


def reset_active():
    """Reset the active configuration to the built-in defaults."""
    _active.reset()


def normalize_entry_type(value):
    """Return the normalized (lowercased) form of an entry type.

    ```python
    normalize_entry_type(value)
    ```

    `value` (a `str`) is lowercased and validated against the
    recognized entry types (the types BibDesk templates plus the
    extended data-model types, as configured). It is returned lowercased
    *verbatim*. If entry-type validation is disabled (`verify_types`;
    see the [configuration](configuration)), any lowercased value is
    accepted.

    Raises {exc}`TypeError` if `value` is not a `str`, and
    {exc}`ValueError` if it is not a recognized entry type.

    ```python
    >>> from bibdeskparser.entrytypes import normalize_entry_type
    >>> normalize_entry_type("Article")
    'article'
    >>> normalize_entry_type("phdthesis")
    'phdthesis'
    >>> normalize_entry_type("bogus")
    Traceback (most recent call last):
        ...
    ValueError: invalid entry type: 'bogus'

    ```
    """
    if not isinstance(value, str):
        raise TypeError(f"entry type must be a str, not {type(value)!r}")
    lowered = value.lower()
    if not _active.verify_types:
        return lowered
    if lowered in _active.recognized_entry_types:
        return lowered
    raise ValueError(f"invalid entry type: {value!r}")


def is_known_field(key):
    """Return whether `key` is a recognized field name.

    ```python
    is_known_field(key)
    ```

    `key` is compared case-insensitively against the recognized field
    names (the classic BibTeX/BibDesk fields together with the extended
    data-model fields, plus any added through the
    [configuration](configuration)).

    ```python
    >>> from bibdeskparser.entrytypes import is_known_field
    >>> is_known_field("Title")
    True
    >>> is_known_field("journal")
    True
    >>> is_known_field("nonsense")
    False

    ```
    """
    return key.lower() in _active.known_fields


def field_is_appropriate(entry_type, key):
    """Return whether `key` is an appropriate field for `entry_type`.

    ```python
    field_is_appropriate(entry_type, key)
    ```

    Both arguments are compared case-insensitively. If field
    validation is disabled (`verify_fields`; see the
    [configuration](configuration)), every field is treated as
    appropriate. Otherwise a field is appropriate if it is a universal
    field (accepted on any type), or -- for a type BibDesk templates --
    one of that type's required/optional fields. For a recognized type
    that BibDesk does not template, any recognized field is appropriate.

    ```python
    >>> from bibdeskparser.entrytypes import field_is_appropriate
    >>> field_is_appropriate("article", "Journal")
    True
    >>> field_is_appropriate("article", "publisher")  # a book field
    False
    >>> field_is_appropriate("book", "keywords")  # universal
    True

    ```
    """
    if not _active.verify_fields:
        return True
    lkey = key.lower()
    if lkey in _active.universal_fields:
        return True
    allowed = _active.type_fields.get(entry_type.lower())
    if allowed is not None:
        return lkey in allowed
    return lkey in _active.known_fields
