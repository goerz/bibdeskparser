"""Handling of the header comment in BibDesk `.bib` files.

Every `.bib` file saved by BibDesk starts with this header (`NAME` is
the macOS user's full name, and there is a single trailing space after
the date and after `(UTF-8)`):

```
%% This BibTeX bibliography file was created using BibDesk.
%% http://bibdesk.sourceforge.net/


%% Created for NAME at YYYY-MM-DD HH:MM:SS ±ZZZZ


%% Saved with string encoding Unicode (UTF-8)
```

The date on the `Created for` line is the time of the last save;
BibDesk updates it in place on every save. `bibtexparser` parses the
whole header as a single `ImplicitComment` block (internal blank lines
and trailing spaces are preserved verbatim, but the trailing space of
the *last* line is rstripped away; see `restore_trailing_space`).

This module extracts data from that header (`parse_header`,
`peek_timestamp`), updates it in place (`update_header`), and
synthesizes it for new files (`make_header`).
"""

import datetime
import re

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "parse_header",
    "make_header",
    "peek_timestamp",
    "update_header",
    "restore_trailing_space",
]


#: `strptime`/`strftime` format of the date in the `Created for` line.
_TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S %z"

#: Regex matching the `Created for` line of a BibDesk header.
_CREATED_RE = re.compile(
    r"^%% Created for (?P<creator>.+?) at "
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})",
    flags=re.MULTILINE,
)

#: First line of the last section of a BibDesk header.
_SAVED_WITH_PREFIX = "%% Saved with string encoding "

#: Template for `make_header` (mind the trailing spaces).
_HEADER_TEMPLATE = (
    "%% This BibTeX bibliography file was created using BibDesk.\n"
    "%% http://bibdesk.sourceforge.net/\n"
    "\n"
    "\n"
    "%% Created for {creator} at {timestamp} \n"
    "\n"
    "\n"
    "%% Saved with string encoding Unicode (UTF-8) "
)


def parse_header(comment_text):
    """Extract the creator and save time from a BibDesk header.

    ```python
    parse_header(comment_text)
    ```

    Returns a tuple `(creator, timestamp)` with the creator name (str)
    and the last-save time (a timezone-aware
    {any}`datetime.datetime`), extracted from the
    `%% Created for NAME at YYYY-MM-DD HH:MM:SS ±ZZZZ` line of
    `comment_text` (the body of the comment block at the top of the
    `.bib` file). Returns `(None, None)` if no such line is found,
    indicating that the file was not written by BibDesk.

    ```python
    >>> from bibdeskparser.header import parse_header
    >>> header = (
    ...     "%% This BibTeX bibliography file was created using "
    ...     "BibDesk.\\n"
    ...     "%% http://bibdesk.sourceforge.net/\\n\\n\\n"
    ...     "%% Created for Michael Goerz at 2026-07-04 13:45:42 -0400 "
    ... )
    >>> creator, timestamp = parse_header(header)
    >>> creator
    'Michael Goerz'
    >>> print(timestamp)
    2026-07-04 13:45:42-04:00
    >>> parse_header("% not a BibDesk header")
    (None, None)

    ```
    """
    match = _CREATED_RE.search(comment_text)
    if match is None:
        return (None, None)
    timestamp = datetime.datetime.strptime(
        match.group("timestamp"), _TIMESTAMP_FMT
    )
    return (match.group("creator"), timestamp)


def update_header(comment_text, timestamp):
    """Replace the save time in a BibDesk header.

    ```python
    update_header(comment_text, timestamp)
    ```

    Returns a copy of `comment_text` in which only the
    `YYYY-MM-DD HH:MM:SS ±ZZZZ` substring of the `Created for` line is
    replaced with `timestamp` (a timezone-aware
    {any}`datetime.datetime`). Everything else, including trailing
    spaces, is preserved byte-for-byte, mirroring how BibDesk updates
    the date in place on every save.

    Raises {any}`ValueError` if `comment_text` contains no
    `Created for` line (see `parse_header`).
    """
    match = _CREATED_RE.search(comment_text)
    if match is None:
        raise ValueError(
            "Cannot update header: no BibDesk 'Created for' line in "
            f"{comment_text!r}"
        )
    start, end = match.span("timestamp")
    return (
        comment_text[:start]
        + timestamp.strftime(_TIMESTAMP_FMT)
        + comment_text[end:]
    )


def make_header(creator, timestamp):
    """Synthesize the header comment for a new BibDesk `.bib` file.

    ```python
    make_header(creator, timestamp)
    ```

    Returns the canonical BibDesk header exactly as BibDesk writes it
    (including the single trailing space after the date and after
    `(UTF-8)`, and the two blank lines between sections), without a
    trailing newline.

    * `creator`: the name to put on the `Created for` line.
    * `timestamp`: the save time, as a timezone-aware
      {any}`datetime.datetime`.

    ```python
    >>> import datetime
    >>> from bibdeskparser.header import make_header, parse_header
    >>> timestamp = datetime.datetime(
    ...     2026, 7, 4, 13, 45, 42,
    ...     tzinfo=datetime.timezone(datetime.timedelta(hours=-4)),
    ... )
    >>> header = make_header("Michael Goerz", timestamp)
    >>> for line in header.split("\\n"):
    ...     print(repr(line))
    '%% This BibTeX bibliography file was created using BibDesk.'
    '%% http://bibdesk.sourceforge.net/'
    ''
    ''
    '%% Created for Michael Goerz at 2026-07-04 13:45:42 -0400 '
    ''
    ''
    '%% Saved with string encoding Unicode (UTF-8) '
    >>> parse_header(header) == ("Michael Goerz", timestamp)
    True

    ```
    """
    return _HEADER_TEMPLATE.format(
        creator=creator, timestamp=timestamp.strftime(_TIMESTAMP_FMT)
    )


def peek_timestamp(path):
    """Cheaply extract the save time from a `.bib` file on disk.

    ```python
    peek_timestamp(path)
    ```

    Reads only the first 20 lines of the file at `path` (without
    parsing it as BibTeX) and returns the timezone-aware
    {any}`datetime.datetime` from the header's `Created for` line, or
    `None` if the file has no BibDesk header. This is intended for
    detecting whether a file changed on disk (e.g., was re-saved by
    BibDesk) since it was read.
    """
    lines = []
    with open(path, encoding="utf-8", errors="replace") as bibfile:
        for line in bibfile:
            lines.append(line)
            if len(lines) >= 20:
                break
    _, timestamp = parse_header("".join(lines))
    return timestamp


def restore_trailing_space(comment_text):
    """Re-append the trailing space to a parsed BibDesk header.

    ```python
    restore_trailing_space(comment_text)
    ```

    BibDesk writes the last header line as
    `%% Saved with string encoding Unicode (UTF-8) `, with a single
    trailing space. When `bibtexparser` parses the header into an
    `ImplicitComment`, it preserves *internal* trailing spaces (such as
    the one after the date) but rstrips the whitespace at the very end
    of the comment, so that one space is lost. This function re-appends
    it, so that writing the parsed header back to disk is byte-exact.

    The space is appended only if the last line of `comment_text`
    starts with `%% Saved with string encoding` and does not already
    end in whitespace; any other text is returned unchanged.
    """
    last_line = comment_text.rsplit("\n", 1)[-1]
    if last_line.startswith(_SAVED_WITH_PREFIX.rstrip()) and (
        last_line == last_line.rstrip()
    ):
        return comment_text + " "
    return comment_text
