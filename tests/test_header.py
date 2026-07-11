"""Tests for `bibdeskparser.header`."""

import datetime
from pathlib import Path

import pytest

from bibdeskparser.header import (
    make_header,
    parse_header,
    peek_timestamp,
    restore_trailing_space,
    update_header,
)

REFS = Path(__file__).parent / "Refs" / "refs.bib"

#: The `Created for` timestamp in `refs.bib`.
REFS_TIMESTAMP = datetime.datetime(
    2026,
    7,
    11,
    13,
    35,
    0,
    tzinfo=datetime.timezone(datetime.timedelta(hours=-4)),
)


@pytest.fixture(scope="module", name="header_text")
def fixture_header_text():
    """The first 8 lines of `refs.bib`: the on-disk BibDesk header."""
    text = REFS.read_text(encoding="utf-8")
    return "\n".join(text.split("\n")[:8])


@pytest.fixture(name="parsed_header_text")
def fixture_parsed_header_text(header_text):
    """The header as bibtexparser parses it (final line rstripped)."""
    assert header_text.endswith("(UTF-8) ")
    return header_text[:-1]


def test_parse_header(header_text):
    """`parse_header` extracts creator and timestamp from `refs.bib`."""
    creator, timestamp = parse_header(header_text)
    assert creator == "Michael Goerz"
    assert timestamp == REFS_TIMESTAMP
    assert timestamp.utcoffset() == datetime.timedelta(hours=-4)


def test_parse_header_absent():
    """`parse_header` returns `(None, None)` for a non-BibDesk file."""
    assert parse_header("") == (None, None)
    assert parse_header("% just a comment\n% another line") == (None, None)
    # A truncated "Created for" line must not match:
    assert parse_header("%% Created for Michael Goerz") == (None, None)


def test_update_header(header_text):
    """`update_header` replaces only the date substring."""
    new_timestamp = datetime.datetime(
        2027, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc
    )
    updated = update_header(header_text, new_timestamp)
    assert updated == header_text.replace(
        "2026-07-11 13:35:00 -0400", "2027-01-02 03:04:05 +0000"
    )
    # Everything else is byte-identical (incl. trailing spaces):
    assert (
        updated.replace(
            "2027-01-02 03:04:05 +0000", "2026-07-11 13:35:00 -0400"
        )
        == header_text
    )
    # Round-trip: writing the original timestamp back is a no-op.
    assert update_header(updated, REFS_TIMESTAMP) == header_text


def test_update_header_no_header():
    """`update_header` raises `ValueError` without a Created line."""
    with pytest.raises(ValueError, match="no BibDesk 'Created for' line"):
        update_header("% not a header", REFS_TIMESTAMP)


def test_make_header(header_text):
    """`make_header` reproduces the `refs.bib` header byte-exactly."""
    header = make_header("Michael Goerz", REFS_TIMESTAMP)
    assert header == header_text


def test_make_header_other_creator():
    """`make_header` substitutes creator and timestamp."""
    timestamp = datetime.datetime(
        2027, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc
    )
    header = make_header("Ada Lovelace", timestamp)
    assert (
        "%% Created for Ada Lovelace at 2027-12-31 23:59:59 +0000 \n" in header
    )
    assert parse_header(header) == ("Ada Lovelace", timestamp)


def test_peek_timestamp():
    """`peek_timestamp` reads the timestamp from `refs.bib`."""
    assert peek_timestamp(REFS) == REFS_TIMESTAMP


def test_peek_timestamp_no_header(tmp_path):
    """`peek_timestamp` returns `None` for files without a header."""
    bibfile = tmp_path / "plain.bib"
    bibfile.write_text("@article{key1,\n\ttitle = {T}}\n", encoding="utf-8")
    assert peek_timestamp(bibfile) is None
    empty = tmp_path / "empty.bib"
    empty.write_text("", encoding="utf-8")
    assert peek_timestamp(empty) is None


def test_peek_timestamp_only_reads_head(tmp_path):
    """`peek_timestamp` ignores a Created line beyond the first 20
    lines."""
    bibfile = tmp_path / "late.bib"
    bibfile.write_text(
        "%\n" * 25 + "%% Created for A at 2026-07-04 13:45:42 -0400 \n",
        encoding="utf-8",
    )
    assert peek_timestamp(bibfile) is None


def test_restore_trailing_space(header_text, parsed_header_text):
    """`restore_trailing_space` re-appends the rstripped space."""
    assert restore_trailing_space(parsed_header_text) == header_text


def test_restore_trailing_space_idempotent(header_text):
    """A header that already ends in a space is returned unchanged."""
    assert restore_trailing_space(header_text) == header_text


def test_restore_trailing_space_other_comment():
    """Comments not ending in a `Saved with` line are unchanged."""
    assert restore_trailing_space("%% some comment") == "%% some comment"
    assert restore_trailing_space("") == ""
