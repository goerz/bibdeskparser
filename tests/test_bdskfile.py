"""Tests for `bibdeskparser.bdskfile`."""

import base64
import importlib.util
import plistlib
import re
import sys
from pathlib import Path

import pytest

from bibdeskparser.bdskfile import BibDeskFile

REFS_BIB = Path(__file__).parent / "Refs" / "refs.bib"

HAVE_PYOBJC = importlib.util.find_spec("Foundation") is not None


def _refs_field_values():
    """All `bdsk-file-N` field values in `refs.bib`."""
    text = REFS_BIB.read_text(encoding="utf-8")
    return re.findall(r"bdsk-file-\d+ = \{([^}]+)\}", text)


def test_refs_bib_roundtrip():
    """Every `bdsk-file-N` field in refs.bib round-trips byte-exactly."""
    values = _refs_field_values()
    assert len(values) == 11
    for inner in values:
        value = "{" + inner + "}"
        bdsk_file = BibDeskFile.from_field_value(value)
        assert bdsk_file.relative_path
        assert bdsk_file.relative_path.endswith(".pdf")
        assert bdsk_file.bookmark is not None
        assert bdsk_file.to_field_value() == value


def test_path_only_roundtrip():
    """A path-only plist decodes and re-encodes to the same content."""
    plist = plistlib.dumps(
        {"relativePath": "sub/file.pdf"}, fmt=plistlib.FMT_BINARY
    )
    value = "{" + base64.b64encode(plist).decode() + "}"
    bdsk_file = BibDeskFile.from_field_value(value)
    assert bdsk_file.relative_path == "sub/file.pdf"
    assert bdsk_file.bookmark is None
    assert bdsk_file.alias_data is None
    reencoded = bdsk_file.to_field_value()
    # The encoder's output must decode back to the identical dict
    payload = base64.b64decode(reencoded[1:-1])
    assert plistlib.loads(payload) == {"relativePath": "sub/file.pdf"}
    # Round-trip through from_field_value gives an equal object
    assert BibDeskFile.from_field_value(reencoded) == bdsk_file


def test_constructor_existing_file(tmp_path):
    """Constructing from an existing file gives the right relative path.

    On macOS with pyobjc installed, a bookmark is created automatically;
    otherwise the constructor warns and falls back to path-only.
    """
    pdf = tmp_path / "sub" / "file.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4")
    if sys.platform == "darwin" and HAVE_PYOBJC:
        bdsk_file = BibDeskFile(pdf, relative_to=tmp_path)
        assert bdsk_file.bookmark is not None
    else:
        with pytest.warns(UserWarning, match="path-only"):
            bdsk_file = BibDeskFile(pdf, relative_to=tmp_path)
        assert bdsk_file.bookmark is None
    assert bdsk_file.relative_path == "sub/file.pdf"
    assert bdsk_file.alias_data is None
    assert repr(bdsk_file) == 'BibDeskFile("sub/file.pdf")'


def test_constructor_validation(tmp_path):
    """Invalid constructor arguments are rejected."""
    # Both bookmark and alias_data given
    with pytest.raises(ValueError):
        BibDeskFile(
            "file.pdf",
            bookmark=b"\x00",
            alias_data=b"\x00",
            relative_to=tmp_path,
        )
    # A nonexistent file without bookmark/alias_data raises (matching the
    # prototype: auto-creating a bookmark requires the file to exist)
    with pytest.raises(FileNotFoundError):
        BibDeskFile(tmp_path / "missing.pdf", relative_to=tmp_path)
    # With an explicit bookmark, the file need not exist
    bdsk_file = BibDeskFile(
        tmp_path / "missing.pdf", bookmark=b"\x00\x01", relative_to=tmp_path
    )
    assert bdsk_file.relative_path == "missing.pdf"
    assert bdsk_file.bookmark == b"\x00\x01"


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="cross-drive paths only exist on Windows",
)
def test_constructor_cross_drive(tmp_path):
    """A file on a different drive than the .bib file is rejected.

    Such an attachment has no relative path, which BibDesk cannot
    represent, so the constructor raises rather than silently storing
    an absolute path.
    """
    other_drive = "Z:" if tmp_path.drive.upper() != "Z:" else "Y:"
    cross = Path(f"{other_drive}\\Papers\\file.pdf")
    with pytest.raises(ValueError, match="different drive"):
        BibDeskFile(cross, bookmark=b"\x00", relative_to=tmp_path)


def test_alias_data_roundtrip():
    """A legacy `aliasData` plist round-trips through the encoder."""
    alias = bytes(range(64))
    plist = plistlib.dumps(
        {"relativePath": "old.pdf", "aliasData": alias},
        fmt=plistlib.FMT_BINARY,
    )
    value = "{" + base64.b64encode(plist).decode() + "}"
    bdsk_file = BibDeskFile.from_field_value(value)
    assert bdsk_file.relative_path == "old.pdf"
    assert bdsk_file.alias_data == alias
    assert bdsk_file.bookmark is None
    reencoded = bdsk_file.to_field_value()
    payload = base64.b64decode(reencoded[1:-1])
    assert plistlib.loads(payload) == {
        "relativePath": "old.pdf",
        "aliasData": alias,
    }
    assert BibDeskFile.from_field_value(reencoded) == bdsk_file


def test_unicode_relative_path():
    """Non-ASCII paths exercise the UTF-16-BE string encoding."""
    path = "Müller/文献/paper-ü-你好.pdf"
    plist = plistlib.dumps(
        {"relativePath": path, "bookmark": b"\x01\x02\x03"},
        fmt=plistlib.FMT_BINARY,
    )
    value = "{" + base64.b64encode(plist).decode() + "}"
    bdsk_file = BibDeskFile.from_field_value(value)
    assert bdsk_file.relative_path == path
    reencoded = bdsk_file.to_field_value()
    roundtripped = BibDeskFile.from_field_value(reencoded)
    assert roundtripped == bdsk_file
    assert roundtripped.relative_path == path
    payload = base64.b64decode(reencoded[1:-1])
    assert plistlib.loads(payload) == {
        "relativePath": path,
        "bookmark": b"\x01\x02\x03",
    }
