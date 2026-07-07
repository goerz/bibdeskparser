"""Support for BibDesk local file attachments (`bdsk-file-N` fields).

BibDesk links local files to an entry via `bdsk-file-1`, `bdsk-file-2`,
etc. Each field contains a base64 payload that encodes
an Apple *binary plist* dictionary with a `relativePath` string and,
optionally, `bookmark` or `aliasData` bytes. The `BibDeskFile` class
decodes and re-encodes these values byte-exactly; it is used
internally by `Entry.files` (see `entry.py`), which is the public way
to read or set an entry's linked files.
"""

import base64
import os
import plistlib
import struct
import sys
import warnings
from pathlib import Path
from typing import Optional

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__all__ = []
__private__ = ["BibDeskFile", "bookmark_for_path"]


class BibDeskFile:
    """Decoded BibDesk local file attachment (`bdsk-file-N` field).

    ```python
    BibDeskFile(
        path,
        bookmark=None,
        alias_data=None,
        relative_to=None,
        must_exist=True,
    )
    ```

    A `bdsk-file-N` field value in a `.bib` file written by BibDesk is
    `{` + base64 + `}`, where the base64 payload is an Apple binary
    plist encoding a dictionary with a `relativePath` string and
    (usually) a `bookmark` data blob (or, in legacy files, `aliasData`).

    Arguments:

    * `path`: Path to the attached file (absolute, or relative to the
      current working directory).
    * `bookmark`: macOS URL bookmark bytes, or `None`.
    * `alias_data`: Legacy HFS alias bytes, or `None`.
    * `relative_to`: `.bib` file path or its directory (absolute, or
      relative to the current working directory); defaults to the
      current working directory.
    * `must_exist`: whether to require `path` to point to an existing
      file (raising {py:class}`FileNotFoundError` otherwise). With
      `must_exist=False`, a nonexistent `path` yields a path-only
      attachment, without a bookmark and without any warning.

    At most one of `bookmark` and `alias_data` may be given. If both are
    `None` and the file exists, a bookmark is created automatically on
    macOS (requires `pyobjc-framework-Cocoa`). Where a bookmark cannot
    be created, the instance falls back to a path-only attachment with
    a {py:class}`UserWarning` (BibDesk will generate a bookmark on its
    next save).

    Use {py:meth}`from_field_value` and {py:meth}`to_field_value` to
    convert from and to the string value of a `bdsk-file-N` field:

    ```python
    >>> from bibdeskparser.bdskfile import BibDeskFile
    >>> value = (
    ...     "{YnBsaXN0MDDRAQJccmVsYXRpdmVQYXRoWXBhcGVyLnBkZggLG"
    ...     "AAAAAAAAAEBAAAAAAAAAAMAAAAAAAAAAAAAAAAAAAAi}"
    ... )
    >>> bdsk_file = BibDeskFile.from_field_value(value)
    >>> bdsk_file
    BibDeskFile("paper.pdf")
    >>> bdsk_file.to_field_value() == value
    True

    ```

    Attributes:

    * `relative_path`: Path of the file relative to the `.bib`
      directory, e.g. `Smith2023.pdf`, `Subdir/Smith2023.pdf`, or
      `../GoodReader/Smith2023.pdf`. BibDesk's primary locator: it is
      tried first when resolving the attachment (and is all that is
      available on a different machine).
    * `bookmark`: macOS URL bookmark
      (`NSURL bookmarkDataWithOptions:0`), written by default by
      modern BibDesk (since ~2012). The fallback locator when
      `relative_path` no longer resolves: it tracks the file by
      inode, so it survives renames and moves within the same volume,
      and BibDesk repairs the stored path from it on its next save.
      `None` for path-only or legacy alias entries.
    * `alias_data`: Legacy HFS Resource Manager alias (`FSNewAlias()`),
      present in `.bib` files saved by older BibDesk versions or with
      `BDSKSaveLinkedFilesAsAliasKey=YES`. `None` in modern files.
      Read-only in practice: keep the existing value when
      round-tripping; use `bookmark` for new attachments.

    The underlying plist uses the keys `relativePath`, `bookmark`, and
    `aliasData`.
    """

    def __init__(
        self,
        path: "str | Path",
        bookmark: Optional[bytes] = None,
        alias_data: Optional[bytes] = None,
        relative_to: "str | Path | None" = None,
        *,
        must_exist: bool = True,
    ) -> None:
        if bookmark is not None and alias_data is not None:
            raise ValueError(
                "at most one of bookmark and alias_data may be set"
            )
        if relative_to is not None:
            base = Path(relative_to).resolve()
        else:
            base = Path.cwd()
        if base.is_file():
            base = base.parent
        abs_path = Path(path).resolve()
        if bookmark is None and alias_data is None:
            if not abs_path.exists():
                if must_exist:
                    raise FileNotFoundError(f"No such file: {abs_path}")
                # An intentional path-only attachment: no bookmark can
                # be created for a file that does not exist (BibDesk
                # adds one on its next save, once the file appears).
            else:
                if sys.platform == "darwin":
                    try:
                        bookmark = bookmark_for_path(str(abs_path))
                    except (ImportError, OSError):
                        pass
                if bookmark is None:
                    warnings.warn(
                        f"Could not create a macOS bookmark for "
                        f"{abs_path}; falling back to a path-only "
                        "attachment",
                        UserWarning,
                        stacklevel=2,
                    )
        self._relative_path = os.path.relpath(abs_path, base)
        self._bookmark = bookmark
        self._alias_data = alias_data

    @property
    def relative_path(self) -> str:
        """Path of the file relative to the `.bib` directory."""
        return self._relative_path

    @property
    def bookmark(self) -> Optional[bytes]:
        """The macOS URL bookmark bytes, or `None`."""
        return self._bookmark

    @property
    def alias_data(self) -> Optional[bytes]:
        """The legacy HFS alias bytes, or `None`."""
        return self._alias_data

    def __repr__(self) -> str:
        return f'BibDeskFile("{self._relative_path}")'

    def __eq__(self, other) -> bool:
        if not isinstance(other, BibDeskFile):
            return NotImplemented
        return (
            self._relative_path == other._relative_path
            and self._bookmark == other._bookmark
            and self._alias_data == other._alias_data
        )

    @classmethod
    def from_field_value(cls, value: str) -> "BibDeskFile":
        """Parse a `{base64...}` field value from a `.bib` entry."""
        if value.startswith("{") and value.endswith("}"):
            inner = value[1:-1]
        else:
            inner = value
        plist = plistlib.loads(base64.b64decode(inner))
        obj = object.__new__(cls)
        obj._relative_path = plist.get("relativePath") or ""
        obj._bookmark = None
        if "bookmark" in plist:
            obj._bookmark = bytes(plist["bookmark"])
        obj._alias_data = None
        if "aliasData" in plist:
            obj._alias_data = bytes(plist["aliasData"])
        return obj

    def to_field_value(self) -> str:
        """Encode to the `{base64...}` string for a `.bib` file."""
        return "{" + base64.b64encode(self._to_plist_bytes()).decode() + "}"

    def _to_plist_bytes(self) -> bytes:
        """Serialize as a binary plist matching Cocoa's byte layout.

        `NSPropertyListSerialization` writes `relativePath` as the
        first key (hash-table order, not alphabetical); we replicate
        this so that unmodified entries produce bytes identical to the
        original BibDesk output.
        """
        path_key = _bplist_str("relativePath")
        path_val = _bplist_str(self.relative_path)

        if self.bookmark is not None or self.alias_data is not None:
            if self.bookmark is not None:
                data_key, data_val = "bookmark", self.bookmark
            else:
                data_key, data_val = "aliasData", self.alias_data
            # 5 objects:
            # 0=root-dict, 1=path-key, 2=data-key, 3=path-val, 4=data-val
            root = bytes([0xD2, 0x01, 0x02, 0x03, 0x04])
            objs = [
                root,
                path_key,
                _bplist_str(data_key),
                path_val,
                _bplist_data(data_val),
            ]
        else:
            # Path-only: 3 objects: 0=root-dict, 1=path-key, 2=path-val
            root = bytes([0xD1, 0x01, 0x02])
            objs = [root, path_key, path_val]

        return _bplist_assemble(objs)


def bookmark_for_path(path: str) -> bytes:
    """Create a macOS URL bookmark for a local file (macOS only).

    Calls `-[NSURL bookmarkDataWithOptions:0
    includingResourceValuesForKeys:nil relativeToURL:nil error:NULL]`
    via pyobjc, replicating exactly the Cocoa API BibDesk uses
    (`BDSKBookmarkLinkedFile.initWithURL:delegate:`). The resulting
    bytes go into {py:attr}`BibDeskFile.bookmark`. The file must exist
    on disk.

    Requires macOS and `pyobjc-framework-Cocoa` (install
    `bibdeskparser[macos]`). For cross-platform code, use
    {py:class}`BibDeskFile` directly; it falls back to a path-only
    entry where bookmarks are unavailable (BibDesk auto-creates the
    bookmark on its next save).

    Raises:

    * {py:class}`NotImplementedError`: on platforms other than macOS.
    * {py:class}`ImportError`: if pyobjc is not installed.
    * {py:class}`OSError`: if Cocoa fails to create the bookmark
      (e.g., because the file does not exist).
    """
    if sys.platform != "darwin":
        raise NotImplementedError(
            "bookmark_for_path is macOS-only; use BibDeskFile() "
            "for cross-platform code"
        )
    try:
        # pylint: disable=import-outside-toplevel
        from Foundation import NSURL  # pyobjc-framework-Cocoa
    except ImportError as exc:
        raise ImportError(
            "bookmark_for_path requires pyobjc-framework-Cocoa; "
            "install the 'bibdeskparser[macos]' extra"
        ) from exc
    url = NSURL.fileURLWithPath_(os.path.abspath(path))
    # The selector name exceeds the line length limit, hence `getattr`.
    make_bookmark = getattr(
        url,
        "bookmarkDataWithOptions_includingResourceValuesForKeys_"
        "relativeToURL_error_",
    )
    data, err = make_bookmark(0, None, None, None)
    if data is None:
        raise OSError(f"Could not create bookmark for {path!r}: {err}")
    return bytes(data)


def _bplist_count(n: int) -> bytes:
    """Encode an integer count for an extended-length object header."""
    if n < 256:
        return bytes([0x10, n])
    if n < 65536:
        return bytes([0x11]) + struct.pack(">H", n)
    if n < 2**32:
        return bytes([0x12]) + struct.pack(">I", n)
    return bytes([0x13]) + struct.pack(">Q", n)


def _bplist_str(s: str) -> bytes:
    """Encode a string object for a binary plist."""
    try:
        b = s.encode("ascii")
        n = len(b)
        if n < 15:
            marker = bytes([0x50 | n])
        else:
            marker = bytes([0x5F]) + _bplist_count(n)
        return marker + b
    except UnicodeEncodeError:
        b = s.encode("utf-16-be")
        n = len(s)  # character count, not byte count
        if n < 15:
            marker = bytes([0x60 | n])
        else:
            marker = bytes([0x6F]) + _bplist_count(n)
        return marker + b


def _bplist_data(b: bytes) -> bytes:
    """Encode a data object for a binary plist."""
    n = len(b)
    if n < 15:
        marker = bytes([0x40 | n])
    else:
        marker = bytes([0x4F]) + _bplist_count(n)
    return marker + b


def _bplist_assemble(objs: list) -> bytes:
    """Assemble a `bplist00` from a pre-ordered list of encoded objects."""
    header = b"bplist00"
    cur = len(header)
    offsets = []
    for obj in objs:
        offsets.append(cur)
        cur += len(obj)

    ot_start = cur
    if ot_start < 256:
        off_size, off_fmt = 1, ">B"
    elif ot_start < 65536:
        off_size, off_fmt = 2, ">H"
    elif ot_start < 2**32:
        off_size, off_fmt = 4, ">I"
    else:
        off_size, off_fmt = 8, ">Q"

    ot = b"".join(struct.pack(off_fmt, o) for o in offsets)
    trailer = struct.pack(">5xBBBQQQ", 0, off_size, 1, len(objs), 0, ot_start)
    return header + b"".join(objs) + ot + trailer
