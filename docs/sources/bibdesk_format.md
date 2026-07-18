# BibDesk's `.bib` Format

BibDesk stores its database as an ordinary BibTeX `.bib` file, but it leans on
a handful of BibDesk-specific conventions on top of plain BibTeX: a header
comment, extra bookkeeping fields, an encoding of linked files and URLs into
otherwise-plain-looking fields, and `@comment` blocks for user-defined
groups. The `bibdeskparser` library understands all of these and reproduces
them exactly, so that a file loaded and saved again -- without any changes --
comes back byte-for-byte identical. This page walks through each of these
features and the API that exposes it. For the full method and property
reference, see the {py:mod}`bibdeskparser` API documentation, in particular the
`Library` and `Entry` classes.

## The file header

Every `.bib` file BibDesk writes starts with a fixed comment block:

```
%% This BibTeX bibliography file was created using BibDesk.
%% http://bibdesk.sourceforge.net/


%% Created for Michael Goerz at 2026-07-11 13:35:00 -0400


%% Saved with string encoding Unicode (UTF-8)
```

The `Created for` line records who saved the file and when; BibDesk
updates the timestamp on that line in place every time it saves,
leaving everything else untouched.
{py:class}`~bibdeskparser.library.Library` exposes this timestamp as
{py:attr}`~bibdeskparser.library.Library.timestamp`, and
{py:meth}`~bibdeskparser.library.Library.save` advances it -- but only
when something in the library actually changed. Saving an unmodified
library leaves the header (and the rest of the file) untouched:

```python
>>> import shutil
>>> import tempfile
>>> import warnings
>>> from pathlib import Path
>>> from bibdeskparser import Library
>>> tmpdir = tempfile.TemporaryDirectory()
>>> copy_dir = Path(tmpdir.name) / "Refs"
>>> _ = shutil.copytree("tests/Refs", copy_dir)
>>> with warnings.catch_warnings():
...     warnings.simplefilter("ignore")  # the duplicate-key warning, see below
...     bib = Library(str(copy_dir / "refs.bib"))
>>> bib.timestamp
datetime.datetime(2026, 7, 11, 13, 35, tzinfo=datetime.timezone(datetime.timedelta(days=-1, seconds=72000)))
>>> bib.save()  # no changes made: the header timestamp is unchanged
>>> bib.timestamp
datetime.datetime(2026, 7, 11, 13, 35, tzinfo=datetime.timezone(datetime.timedelta(days=-1, seconds=72000)))
>>> tmpdir.cleanup()

```

A library created from scratch has no header until it is first saved,
at which point one is synthesized (using the current user's full name,
or an explicit `creator=` passed to the `Library` constructor).

## `date-added` and `date-modified`

BibDesk stamps every entry with a `date-added` and a `date-modified`
field the moment it is created, and updates `date-modified` on every
edit. These two fields are bookkeeping, not bibliographic data, so
they are not part of `Entry`'s dict-like interface; instead they are
exposed as read-only `datetime.datetime` objects:

```python
>>> entry = bib["GoerzNJP2014"]
>>> print(entry.date_added)
2026-07-04 09:04:26-04:00
>>> print(entry.date_modified)
2026-07-04 09:04:26-04:00

```

Any mutation of an `Entry` -- setting or deleting a field, changing
{attr}`~bibdeskparser.Entry.entry_type`, adding or removing a URL with
{meth}`~bibdeskparser.Entry.add_url` and friends, or a file-attachment
change made through the owning `Library` -- updates
`date-modified` to the current time and marks the entry as modified
since it was loaded. For ordinary fields and
the entry type this mirrors what BibDesk itself does when a record is
edited in its UI; for `bdsk-file-N`/`bdsk-url-N` changes BibDesk
leaves `date-modified` untouched, and `bibdeskparser` deliberately
updates it anyway, since the entry's stored fields do change. That
modified state is what
{meth}`~bibdeskparser.Library.save` uses to decide which
entries need to be rewritten (and reordered into BibDesk's field
order) rather than copied through verbatim.

## Linked files (`bdsk-file-N` fields)

When a PDF or other file is attached to an entry in BibDesk, it shows
up in the `.bib` file as a `bdsk-file-1`, `bdsk-file-2`, ... field
(numbered in attachment order). The value looks like an opaque base64
blob because it is one: a binary property list containing the file's
path relative to the `.bib` file and, on macOS, a *bookmark*.
BibDesk locates the file by its relative path first; when that fails
(the file was moved or renamed), it falls back to the bookmark, which
tracks the file by inode, and then repairs the stored path from it on
its next save.

`bibdeskparser` decodes all of this for you.
{py:attr}`~bibdeskparser.entry.Entry.files` presents the attachments
as a plain list of relative path strings:

```python
>>> entry.files
['GoerzNJP2014.pdf']

```

`.files` is read-only; attachments are modified through the owning
{py:class}`~bibdeskparser.library.Library`
({py:meth}`~bibdeskparser.library.Library.add_file`,
{py:meth}`~bibdeskparser.library.Library.replace_file`,
{py:meth}`~bibdeskparser.library.Library.unlink_file`,
{py:meth}`~bibdeskparser.library.Library.rename_file`). This is a
direct consequence of how the attachments are stored: the paths in a
`bdsk-file-N` field are relative to the `.bib` file, and only the
`Library` knows where that file lives -- an `Entry` on its own could
not tell what `Smith2020.pdf` is relative *to*. Operating at the
library level also lets these methods handle concerns that span
entries: the same file can be linked from several entries, so
deleting a file from disk must check all of them, and renaming a file
on disk must update every entry that links it (see the [How-To on
managing attachments](howto)).

An attachment whose path is unchanged keeps its original bookmark
data byte-for-byte (rather than dropping it or requiring you to
regenerate it); only genuinely new paths get a freshly created
bookmark (macOS only, requires the `bibdeskparser[macos]` extra).
`bibdeskparser` never resolves a bookmark itself -- it is opaque data
that BibDesk uses to re-locate a moved or renamed file, preserved so
BibDesk keeps working after `bibdeskparser` has touched the entry.
`entry.files` always reflects the *stored* relative path, not a live
lookup, so it does not change if the file is moved outside of
`bibdeskparser` (or by BibDesk itself, resolving a bookmark).

## Linked URLs (`bdsk-url-N` fields)

BibDesk also lets you link a URL to an entry, independently of the
`url` bibliographic field; these become `bdsk-url-1`, `bdsk-url-2`,
... fields, again numbered in order. Unlike linked files, there is no
bookmark or path resolution involved: each field is just the URL
string itself. `Entry` exposes them as
{attr}`~bibdeskparser.Entry.urls`, a read-only tuple of URL
strings:

```python
>>> entry.urls
('http://stacks.iop.org/1367-2630/16/i=5/a=055012',)

```

Because URLs are self-contained (no path resolution is needed), they
can be managed directly on the `Entry` with
{meth}`~bibdeskparser.Entry.add_url`,
{meth}`~bibdeskparser.Entry.replace_url`, and
{meth}`~bibdeskparser.Entry.remove_url` (or the equivalent
{meth}`~bibdeskparser.Library.add_url`,
{meth}`~bibdeskparser.Library.replace_url`, and
{meth}`~bibdeskparser.Library.remove_url`).

## `@string` macros and journal abbreviations

BibTeX lets a field reference a named string instead of spelling out
its value: `@string{njp = {New J. Phys.}}` defines the macro `njp`,
and any later `journal = njp` (no braces or quotes) expands to `New J.
Phys.` wherever the entry is used. BibDesk's own journal-abbreviation
lists work this way, and its UI shows the same expanded text whether a
field holds a macro reference or the literal string.

This creates one genuine ambiguity: a bare, unquoted field value that
happens to look like a valid macro name (say, `journal = prl`) could
be a macro reference, or it could be someone's literal (if unusual)
text that just happens to match a macro name. `bibdeskparser` resolves
it the same way BibDesk does: a bare value is always treated as a
macro reference, and its expansion (rather than the macro name itself)
is what BibDesk would display -- but through `Entry`'s dict interface,
you get the macro name back in its normalized (lowercase) form, since
that is the value you would need to write back:

```python
>>> entry = bib["GoerzNJP2014"]
>>> entry["journal"]  # 'njp' -- the normalized macro name
'njp'
>>> bib.strings["njp"]  # 'New J. Phys.' -- its expansion
'New J. Phys.'

```

{py:attr}`~bibdeskparser.library.Library.strings` is a read-write view
of the `@string` table: assign to it to define or redefine a macro,
delete a key to remove one (rejected with a `ValueError` if any entry
still references it), and use
{py:meth}`~bibdeskparser.library.Library.rename_string` to rename a
macro everywhere it is used in one step. Assigning an invalid name (one
that doesn't follow BibDesk's own naming rules -- a subset of ASCII, no
leading digit) raises a `ValueError` right away, with a message
explaining what's wrong.

Macro names are case-insensitive, matching BibDesk's macro table:
`bibdeskparser` stores them in their canonical lowercase form
(mixed-case names in a hand-edited file -- both `@string{JAN = ...}`
definitions and bare `month = JAN` references -- are lowercased on
load), and every operation ({py:attr}`~bibdeskparser.library.Library.strings`
lookups, deletion, and
{py:meth}`~bibdeskparser.library.Library.rename_string`) matches names
case-insensitively. A hand-edited `@string{JAN = ...}` therefore
overrides the built-in `jan` month macro, and a `month = JAN` field
resolves against it, exactly as in BibDesk.

When you *do* want to store literal text that happens to look like a
macro name -- so that it round-trips as a quoted/braced string rather
than a bare reference -- wrap it in
{class}`~bibdeskparser.ValueString`:

```python
>>> from bibdeskparser import ValueString
>>> entry["journal"] = ValueString("prl")  # stored as literal text {prl}
>>> entry["journal"]  # still just reads back as 'prl'
'prl'

```

A plain `str` assigned to a field that happens to match a defined (or
even undefined) macro name is instead stored as a bare reference, the
same way BibDesk would read it back. To make that intent explicit --
or to force bare-reference storage in code that cannot rely on the
value's shape -- wrap the value in
{class}`~bibdeskparser.MacroString` instead, the mirror image of
`ValueString`.

### Default macros

BibTeX itself has no built-in macros, but the standard `.bst` style
files (`plain.bst` etc.) all define the twelve month macros `jan`
... `dec` ("January" ... "December", or the abbreviated names in the
abbreviating styles), plus a couple of journal abbreviations such as
`acmcs` or `ieeetr`; biblatex's `biber` likewise treats `jan` ...
`dec` as predefined (mapping them to month numbers). Writing `month =
jan` without any `@string` definition is therefore standard, portable
BibTeX.

BibDesk builds in exactly the twelve month macros -- resolving to the
full (localized) month names -- and nothing else; the `.bst` journal
abbreviations are *not* built in. `bibdeskparser` does the same: `jan`
... `dec` are always defined, expanding to the full English month
names. They resolve at the lowest priority and are not part of
{py:attr}`~bibdeskparser.library.Library.strings` (nor ever written to
the `.bib` file), but in every other respect they behave as macro
references: `month = jan` does not count as an undefined macro, and a
`@string{jan = ...}` definition in the file is an ordinary macro that
overrides the built-in month name and round-trips like any other. A
bare reference to a `.bst` journal abbreviation, by contrast, is
undefined unless the `.bib` file defines it.

## BibDesk Static Groups

BibDesk lets you organize entries into user-curated "static" groups
(as opposed to smart groups, which are just saved searches). These are
recorded in a single `@comment` block at the end of the `.bib` file,
holding an Apple property list:

```
@comment{BibDesk Static Groups{
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" ...>
<plist version="1.0">
<array>
	<dict>
		<key>group name</key>
		<string>My Papers</string>
		<key>keys</key>
		<string>GoerzJPB2011,GoerzNJP2014,...</string>
	</dict>
	...
</array>
</plist>
}}
```

`bibdeskparser` decodes this into
{py:attr}`~bibdeskparser.library.Library.groups`, a read-write
`dict`-like mapping from each group name to the tuple of the group's
citation keys:

```python
>>> sorted(bib.groups)
['My Papers', 'OCT Software', 'Preprints', 'Superconducting Qubits']
>>> bib.groups["Superconducting Qubits"]
('GoerzEPJQT2015', 'GoerzNPJQI2017')

```

Whole groups are created, replaced, or deleted through the mapping
interface (`bib.groups[name] = (key, ...)`, with an empty tuple for a
new empty group, and `del bib.groups[name]`); individual keys are
added or removed with
{py:meth}`~bibdeskparser.library.Library.add_to_group` /
{py:meth}`~bibdeskparser.library.Library.remove_from_group`. The
values are always tuples, so a group's membership can never be edited
in place, behind the library's back. This matters because group
membership is visible from two sides -- the mapping above, and each
entry's read-only {py:attr}`~bibdeskparser.entry.Entry.groups` tuple
-- and `Library`, as the sole point through which membership can
change, keeps the two consistent at all times:

```python
>>> entry.groups  # already in one group
('My Papers',)
>>> bib.add_to_group("Preprints", "GoerzNJP2014")
>>> entry.groups
('My Papers', 'Preprints')
>>> bib.groups["Numerics"] = ("GoerzSPP2019", "GoerzQ2022")
>>> bib["GoerzSPP2019"].groups
('My Papers', 'OCT Software', 'Numerics')
>>> del bib.groups["Numerics"]
>>> bib["GoerzSPP2019"].groups
('My Papers', 'OCT Software')

```

The consistency extends to the entries themselves: deleting an entry
from the library removes its citation key from every group, and
renaming one with {py:meth}`~bibdeskparser.library.Library.rekey`
rewrites the key inside each group it belongs to, so the stored group
data never accumulates dangling keys. Conversely, keys assigned to a
group must belong to entries in the library (a `KeyError` otherwise);
only keys already present in a group loaded from a `.bib` file are
exempt, so a file with stale group data still loads and round-trips.

## BibDesk Smart Groups

Besides static groups, BibDesk supports *smart* groups: saved
searches that dynamically collect every entry matching a set of
conditions, e.g. "all `@article` entries whose author contains
'Goerz'". A smart group is recorded in an `@comment` block of the
same shape as the static groups, but its plist stores the group's
*query* -- an array of conditions plus the AND/OR `conjunction`
combining them -- rather than a list of citation keys:

```
@comment{BibDesk Smart Groups{
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" ...>
<plist version="1.0">
<array>
	<dict>
		<key>conditions</key>
		<array>
			<dict>
				<key>comparison</key>
				<integer>2</integer>
				<key>key</key>
				<string>Author</string>
				<key>value</key>
				<string>Goerz</string>
				<key>version</key>
				<string>1</string>
			</dict>
			...
		</array>
		<key>conjunction</key>
		<integer>0</integer>
		<key>group name</key>
		<string>Goerz Articles</string>
	</dict>
</array>
</plist>
}}
```

`bibdeskparser` preserves this block verbatim: it survives any
combination of modifications and
{py:meth}`~bibdeskparser.library.Library.save` byte-for-byte, exactly
as BibDesk wrote it. Beyond that, smart groups are deliberately *not*
supported: they do not appear in
{py:attr}`~bibdeskparser.library.Library.groups`, and there is no API
to evaluate one. A smart group is a live query against BibDesk's
search machinery, not a list of keys. Its conditions are typed --
string, date, attachment count, boolean, rating, and more, each type
with its own set of comparison operators (the `comparison` integer
above; strings alone have ten, from "contains" to "smaller than") --
and date conditions include relative ones like "in the last two
weeks", which BibDesk re-evaluates continuously as time passes.
Computing a smart group's membership faithfully would mean
reimplementing all of BibDesk's matching semantics, and any
divergence would silently disagree with what BibDesk displays for the
same group. For ad-hoc queries from Python or the command line, use
{py:meth}`~bibdeskparser.library.Library.search` instead.

BibDesk's *external file groups* and *script groups* are stored in
analogous `BibDesk URL Groups` / `BibDesk Script Groups` `@comment`
blocks, and are likewise preserved verbatim without being
interpreted.

## Keywords

BibTeX's conventional `keywords` field -- a comma-separated list of
tags inside each entry -- is how BibDesk populates its "Keywords"
sidebar. `bibdeskparser` treats it as structured data rather than as
an ordinary field: it is readable through the entry's `dict`
interface (`entry["keywords"]` returns the comma-joined string, and
`keywords` appears in iteration and `len`), but *not* writable that
way -- `entry["keywords"] = ...` and `del entry["keywords"]` raise
`KeyError`. Instead, each entry exposes
{attr}`~bibdeskparser.Entry.keywords`, a read-only tuple,
and the library exposes
{attr}`~bibdeskparser.Library.keywords`, a `dict`-like
mapping from each keyword to the tuple of citation keys of the
entries carrying it, mirroring `.groups`:

```python
>>> bib["GoerzJPB2011"].keywords
('Rydberg atoms', 'quantum computing', 'quantum information')
>>> bib.keywords["optimal control"]
('GoerzDiploma2010',)
>>> bib.add_to_keyword("optimal control", "GoerzJPB2011")
>>> bib.keywords["optimal control"]
('GoerzDiploma2010', 'GoerzJPB2011')

```

Hiding the raw field is what makes this mapping trustworthy: since
every keyword edit goes through the `Library`
({py:meth}`~bibdeskparser.library.Library.add_to_keyword`,
{py:meth}`~bibdeskparser.library.Library.remove_from_keyword`, or
assignment/deletion on `bib.keywords`), the mapping and each entry's
`.keywords` can never disagree.

The storage difference from groups shows up in three ways. First, a
keyword exists only inside entries' `keywords` fields, so an empty
keyword cannot be represented: `add_to_keyword` creates a keyword
implicitly with its first entry, and assigning `()` is equivalent to
deleting it. Second, keyword edits change the affected entries'
stored fields, so they bump each entry's `date-modified` and mark it
as modified since it was loaded, whereas group edits only
touch the groups `@comment` block. Third, keywords travel with an
entry -- {meth}`~bibdeskparser.Entry.copy` preserves them --
while group membership belongs to the library and does not.

The `keywords` field is also always literal text: a value that
happens to look like a macro name is never treated as a `@string`
reference, so a one-word keyword is always written braced, never
counts as a use of a macro of the same name, and is left alone when a
macro is renamed. This matches BibDesk, whose keyword handling works
on the plain field text.

## Unicode and TeX-escaped characters

BibDesk's UI always displays accented and special characters as plain
Unicode, but when it writes the `.bib` file, some of those characters
are TeX-escaped for compatibility with tools that expect ASCII BibTeX
-- e.g. `Universit{\"a}t` for `Universität` -- while others that have
no standard TeX equivalent (like `π` or `ℏ`) are written out as literal
Unicode either way. Which characters get escaped, and how, follows
BibDesk's own conversion tables exactly.

`bibdeskparser` hides this distinction completely: `Entry`'s dict
interface always shows and accepts plain Unicode, converting to and
from the on-disk TeX escaping transparently, so a field you set in
Python and one loaded from a BibDesk-written file behave identically:

```python
>>> bib["GoerzDiploma2010"]["school"]
'Freie Universität Berlin'

```

URL-like fields (`url`, and the `bdsk-url-N` fields) are the one
exception: BibDesk stores and displays these verbatim, without TeX
conversion, since escaping would corrupt the URL -- `bibdeskparser`
does the same.

## Duplicate citation keys

BibDesk itself does not enforce unique citation keys: if a `.bib` file
somehow ends up with two entries sharing the same key (for instance,
after a manual edit or a merge gone wrong), BibDesk loads the file
anyway, keeping only the first entry for each duplicated key. Rather
than raise on such a file, `bibdeskparser` does the same, and reports
the affected keys via
{py:attr}`~bibdeskparser.library.Library.duplicate_keys` (along with a
`UserWarning` at load time) so the situation is visible without
blocking you from working with the rest of the file:

```python
>>> bib.duplicate_keys
('GoerzJOSS2025',)

```

## Byte-exact round-tripping

Taken together, these behaviors add up to one guarantee: loading a
BibDesk-authored `.bib` file with
{py:class}`~bibdeskparser.library.Library` and saving it again without
touching anything reproduces the original file byte-for-byte,
including the header, comments, blank lines, and field ordering. The
one exception: hand-edited mixed-case macro names (a `@string{JAN =
...}` definition, or a bare `month = JAN` reference) are normalized to
their canonical lowercase form on load and written back that way. Once
you do make changes,
{py:meth}`~bibdeskparser.library.Library.save` rewrites only the
entries that were actually modified or newly added (in BibDesk's
canonical field order) and copies everything else through verbatim,
and it only advances the header timestamp when something in the
library actually changed. This is what lets `bibdeskparser` sit
alongside BibDesk itself, editing the same file, without producing
noisy diffs or clobbering data BibDesk would have preserved.
