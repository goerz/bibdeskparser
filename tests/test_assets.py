"""Tests for the `[assets]` feature: pattern compilation, resolution,
presence reporting, the `rekey`/`delete` file lifecycle, and the
`check` audits."""

import shutil
import warnings
from functools import partial
from pathlib import Path

import pytest

import bibdeskparser.config as config
from bibdeskparser import Entry, Library
from bibdeskparser.assets import _compile_asset_pattern
from bibdeskparser.checks import collect_problems

REFS_DIR = Path(__file__).parent / "Refs"

ASSETS = {
    "summary": "%f{Cite Key}_summary.md",
    "fulltext": "%f{Cite Key}.ingest/fulltext.md",
    "source": "%f{Cite Key}.ingest/source/",
    "topics": "%i{Topics-File}",
}


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the process-global configuration around every test."""
    config.active.reset()
    yield
    config.active.reset()


@pytest.fixture(name="bibfile")
def fixture_bibfile(tmp_path):
    """A copy of `refs.bib` in `tmp_path`, with its linked PDFs."""
    for pdf in REFS_DIR.glob("*.pdf"):
        shutil.copy(pdf, tmp_path)
    return Path(shutil.copy(REFS_DIR / "refs.bib", tmp_path))


@pytest.fixture(name="bib")
def fixture_bib(bibfile):
    """The library at `bibfile`, with the example `[assets]` map and
    an `[auto_file]` format configured."""
    bib = Library(bibfile)
    config.active.assets = dict(ASSETS)
    config.active.auto_file.format_spec = "%f{Cite Key}%u0%e"
    return bib


def _make_assets(tmp_path, key):
    """Create the summary file and ingest bundle for entry `key`.

    The bundle holds a file no asset pattern names (`notes.txt`), so a
    rename can be checked to carry the whole bundle along."""
    (tmp_path / f"{key}_summary.md").write_text("summary")
    bundle = tmp_path / f"{key}.ingest"
    (bundle / "source").mkdir(parents=True)
    (bundle / "fulltext.md").write_text("fulltext")
    (bundle / "notes.txt").write_text("unrecognized")


# -- pattern compilation ----------------------------------------------- #


def test_compile_asset_pattern():
    """Compilation tells an entry asset from a library asset, and
    finds the lifecycle unit and the directory marker."""
    cls = _compile_asset_pattern("summary", "%f{Cite Key}_summary.md")
    assert cls.per_entry and cls.unit_index == 0 and not cls.is_dir
    cls = _compile_asset_pattern("fulltext", "%f{Cite Key}.ingest/full.md")
    assert cls.per_entry and cls.unit_index == 0 and not cls.is_dir
    cls = _compile_asset_pattern("source", "%f{Cite Key}.ingest/source/")
    assert cls.per_entry and cls.unit_index == 0 and cls.is_dir
    cls = _compile_asset_pattern("deep", "%i{Dir}/%f{Cite Key}_s.md")
    assert cls.per_entry and cls.unit_index == 1
    cls = _compile_asset_pattern("topics", "%i{Topics-File}")
    assert not cls.per_entry and cls.unit_index is None
    assert _compile_asset_pattern("off", "") is None


@pytest.mark.parametrize(
    "pattern",
    [
        "%f{Cite Key}%u0.md",  # unique specifier
        "%f{Cite Key}%r.md",  # random specifier
        "%f{Cite Key}%e",  # original-name specifier
        "/abs/%f{Cite Key}.md",  # absolute
        "a//%f{Cite Key}.md",  # empty component
        "%x{Cite Key}.md",  # invalid specifier
    ],
)
def test_compile_asset_pattern_invalid(pattern):
    """Malformed asset patterns are rejected at compile time."""
    with pytest.raises(ValueError):
        _compile_asset_pattern("bad", pattern)


# -- resolution --------------------------------------------------------- #


def test_asset_resolution(bib, tmp_path):
    """`Library.asset` resolves a per-entry class for its entry and a
    library-level class for the library."""
    _make_assets(tmp_path, "GoerzQ2022")
    (tmp_path / "topics.md").write_text("topics")
    assert bib.asset("summary", "GoerzQ2022") == "GoerzQ2022_summary.md"
    assert (
        bib.asset("fulltext", "GoerzQ2022") == "GoerzQ2022.ingest/fulltext.md"
    )
    assert bib.asset("source", "GoerzQ2022") == "GoerzQ2022.ingest/source"
    assert bib.asset("topics") is None  # document info lacks the key
    bib.info["Topics-File"] = "topics.md"
    assert bib.asset("topics") == "topics.md"
    assert bib.asset("undeclared", "GoerzQ2022") is None


def test_asset_entry_versus_library(bib):
    """An entry asset requires a citation key and a library asset
    rejects one; an unknown key is a `KeyError`."""
    with pytest.raises(ValueError, match="is an entry asset"):
        bib.asset("summary")
    bib.info["Topics-File"] = "topics.md"
    with pytest.raises(ValueError, match="is a library asset"):
        bib.asset("topics", "GoerzQ2022")
    with pytest.raises(KeyError):
        bib.asset("summary", "NoSuchKey")


def test_asset_check_that_file_exists(bib, tmp_path):
    """The existence check is on by default and typed; switching it
    off resolves a path that is not there yet."""
    with pytest.raises(FileNotFoundError, match="no such file"):
        bib.asset("summary", "GoerzQ2022")
    assert (
        bib.asset("summary", "GoerzQ2022", check_that_file_exists=False)
        == "GoerzQ2022_summary.md"
    )
    _make_assets(tmp_path, "GoerzQ2022")
    assert bib.asset("summary", "GoerzQ2022") == "GoerzQ2022_summary.md"
    assert bib.asset("source", "GoerzQ2022") == "GoerzQ2022.ingest/source"
    # a file where the directory-valued class expects a directory
    (tmp_path / "GoerzA2023.ingest").mkdir()
    (tmp_path / "GoerzA2023.ingest" / "source").write_text("not a dir")
    with pytest.raises(FileNotFoundError, match="no such directory"):
        bib.asset("source", "GoerzA2023")


def test_asset_disabled_class(bib):
    """An empty pattern disables the class."""
    config.active.assets["summary"] = ""
    assert bib.asset("summary", "GoerzQ2022") is None


def test_asset_in_memory_library():
    """An unsaved library resolves paths but cannot check them."""
    bib = Library()  # constructing reloads the configuration
    config.active.assets = dict(ASSETS)
    bib["Key2026"] = Entry("misc", "Key2026", fields={"title": "T"})
    assert (
        bib.asset("summary", "Key2026", check_that_file_exists=False)
        == "Key2026_summary.md"
    )
    with pytest.raises(ValueError, match="file path"):
        bib.asset("summary", "Key2026")


def test_asset_info_inside_per_entry_pattern(bib):
    """A `%i{Key}` inside a per-entry pattern gates its resolution;
    an empty value counts as unset, so no empty path component (and no
    doubled separator) can reach the result."""
    config.active.assets = {"summary": "%i{Assets-Dir}/%f{Cite Key}.md"}
    resolve = partial(bib.asset, check_that_file_exists=False)
    assert resolve("summary", "GoerzQ2022") is None
    bib.info["Assets-Dir"] = ""
    assert resolve("summary", "GoerzQ2022") is None
    bib.info["Assets-Dir"] = "notes"
    assert resolve("summary", "GoerzQ2022") == "notes/GoerzQ2022.md"


# -- presence ------------------------------------------------------------ #


def test_assets_per_entry(bib, tmp_path):
    """With keys, `Library.assets` reports the per-entry classes for
    exactly those entries."""
    _make_assets(tmp_path, "GoerzQ2022")
    assert bib.assets("GoerzQ2022", "GoerzA2023") == {
        "GoerzQ2022": {"summary": True, "fulltext": True, "source": True},
        "GoerzA2023": {"summary": False, "fulltext": False, "source": False},
    }
    # the coverage table over the whole library is an explicit sweep
    assert len(bib.assets(*bib)) == len(bib)


def test_assets_library_level(bib, tmp_path):
    """Without keys, `Library.assets` reports the library-level
    classes; a class that does not resolve is omitted."""
    assert bib.assets() == {}  # document info lacks Topics-File
    bib.info["Topics-File"] = "topics.md"
    assert bib.assets() == {"topics": False}
    (tmp_path / "topics.md").write_text("topics")
    assert bib.assets() == {"topics": True}


def test_assets_type_mismatch(bib, tmp_path):
    """A file where a directory is expected does not count as present."""
    (tmp_path / "GoerzQ2022.ingest").mkdir()
    (tmp_path / "GoerzQ2022.ingest" / "source").write_text("not a dir")
    assert bib.assets("GoerzQ2022")["GoerzQ2022"]["source"] is False


def test_assets_unknown_key(bib):
    with pytest.raises(KeyError):
        bib.assets("NoSuchKey")


# -- rekey lifecycle ----------------------------------------------------- #


def test_rekey_moves_assets_and_attachments(bib, tmp_path):
    """`rekey` moves the summary, the bundle as one unit, and re-files
    the attachment."""
    _make_assets(tmp_path, "GoerzQ2022")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # macOS-bookmark fallback
        bib.rekey("GoerzQ2022", "GoerzQ2022SAD")
    assert (tmp_path / "GoerzQ2022SAD_summary.md").is_file()
    assert (tmp_path / "GoerzQ2022SAD.ingest" / "fulltext.md").is_file()
    assert (tmp_path / "GoerzQ2022SAD.ingest" / "notes.txt").is_file()
    assert not (tmp_path / "GoerzQ2022.ingest").exists()
    assert not (tmp_path / "GoerzQ2022_summary.md").exists()
    assert bib["GoerzQ2022SAD"].files == ["GoerzQ2022SAD.pdf"]
    assert (tmp_path / "GoerzQ2022SAD.pdf").is_file()
    assert not (tmp_path / "GoerzQ2022.pdf").exists()


def test_rekey_moves_nested_units(bib, tmp_path):
    """A unit nested inside another unit is renamed at every level:
    the inner one travels with its ancestor and is then renamed where
    it landed."""
    config.active.assets = {
        "bundle": "%f{Cite Key}.ingest/fulltext.md",
        "inner": "%f{Cite Key}.ingest/%f{Cite Key}_data/values.csv",
    }
    inner = tmp_path / "GoerzQ2022.ingest" / "GoerzQ2022_data"
    inner.mkdir(parents=True)
    (inner / "values.csv").write_text("1,2")
    (tmp_path / "GoerzQ2022.ingest" / "fulltext.md").write_text("fulltext")
    bib.rekey("GoerzQ2022", "GoerzQ2022SAD", rename_attachments=False)
    moved = tmp_path / "GoerzQ2022SAD.ingest" / "GoerzQ2022SAD_data"
    assert (moved / "values.csv").read_text() == "1,2"
    assert (tmp_path / "GoerzQ2022SAD.ingest" / "fulltext.md").is_file()
    assert not (tmp_path / "GoerzQ2022.ingest").exists()


def test_rekey_switches_off(bib, tmp_path):
    """The `rename_assets`/`rename_attachments` switches leave the
    files alone."""
    _make_assets(tmp_path, "GoerzQ2022")
    bib.rekey(
        "GoerzQ2022",
        "GoerzQ2022SAD",
        rename_assets=False,
        rename_attachments=False,
    )
    assert (tmp_path / "GoerzQ2022_summary.md").is_file()
    assert (tmp_path / "GoerzQ2022.pdf").is_file()
    assert bib["GoerzQ2022SAD"].files == ["GoerzQ2022.pdf"]


def test_rekey_config_defaults(bib, tmp_path):
    """The `[rekey]` configuration supplies the switch defaults."""
    _make_assets(tmp_path, "GoerzQ2022")
    config.active.rekey.rename_assets = False
    config.active.rekey.rename_attachments = False
    bib.rekey("GoerzQ2022", "GoerzQ2022SAD")
    assert (tmp_path / "GoerzQ2022_summary.md").is_file()
    assert (tmp_path / "GoerzQ2022.pdf").is_file()


def test_rekey_skips_hand_named_attachment(bib, tmp_path):
    """An attachment not following the [auto_file] format is left
    alone, with a warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bib.rename_file("GoerzQ2022", "GoerzQ2022.pdf", "hand-named.pdf")
    with pytest.warns(UserWarning, match="does not follow"):
        bib.rekey("GoerzQ2022", "GoerzQ2022SAD")
    assert (tmp_path / "hand-named.pdf").is_file()
    assert bib["GoerzQ2022SAD"].files == ["hand-named.pdf"]


def test_rekey_skips_missing_attachment(bibfile):
    """An attachment absent from disk is skipped with a warning."""
    bib = Library(bibfile)
    config.active.auto_file.format_spec = "%f{Cite Key}%u0%e"
    (bibfile.parent / "GoerzQ2022.pdf").unlink()
    with pytest.warns(UserWarning, match="does not exist"):
        bib.rekey("GoerzQ2022", "GoerzQ2022SAD")
    assert bib["GoerzQ2022SAD"].files == ["GoerzQ2022.pdf"]


def test_rekey_no_auto_file_format(bibfile, recwarn):
    """Without any [auto_file] format, attachments are silently not
    re-filed; a per-type format that misses the entry's type warns."""
    bib = Library(bibfile)
    bib.rekey("GoerzQ2022", "GoerzQ2022SAD")
    assert not recwarn.list
    assert bib["GoerzQ2022SAD"].files == ["GoerzQ2022.pdf"]
    config.active.auto_file.format_spec = {"book": "%f{Cite Key}%u0%e"}
    with pytest.warns(UserWarning, match="no entry for type 'article'"):
        bib.rekey("GoerzQ2022SAD", "GoerzQ2022")
    assert bib["GoerzQ2022"].files == ["GoerzQ2022.pdf"]


def test_rekey_asset_target_occupied(bib, tmp_path):
    """An asset whose target path already exists is skipped with a
    warning."""
    _make_assets(tmp_path, "GoerzQ2022")
    (tmp_path / "GoerzQ2022SAD_summary.md").write_text("other")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bib.rekey("GoerzQ2022", "GoerzQ2022SAD")
    assert any("target already exists" in str(w.message) for w in caught)
    assert (tmp_path / "GoerzQ2022_summary.md").is_file()  # left alone
    assert (tmp_path / "GoerzQ2022SAD_summary.md").read_text() == "other"
    assert (tmp_path / "GoerzQ2022SAD.ingest").is_dir()  # still moved


def test_rekey_in_memory_library():
    """Rekeying an in-memory library skips the file lifecycle."""
    bib = Library()  # constructing reloads the configuration
    config.active.assets = dict(ASSETS)
    bib["Key2026"] = Entry("misc", "Key2026", fields={"title": "T"})
    assert bib.rekey("Key2026", "NewKey2026") == "NewKey2026"


# -- delete lifecycle ---------------------------------------------------- #


def test_delete_reports_files_left_behind(bib, tmp_path):
    """With removal off (the default), `delete` warns about the files
    it leaves behind."""
    _make_assets(tmp_path, "GoerzQ2022")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        del bib["GoerzQ2022"]
    messages = [str(w.message) for w in caught]
    assert any("leaves asset files behind" in m for m in messages)
    assert any("leaves attached files behind" in m for m in messages)
    assert (tmp_path / "GoerzQ2022_summary.md").is_file()
    assert (tmp_path / "GoerzQ2022.pdf").is_file()


def test_delete_removes_files(bib, tmp_path):
    """With removal on, asset files and attachments are deleted."""
    _make_assets(tmp_path, "GoerzQ2022")
    bib.delete("GoerzQ2022", remove_assets=True, remove_attachments=True)
    assert not (tmp_path / "GoerzQ2022_summary.md").exists()
    assert not (tmp_path / "GoerzQ2022.ingest").exists()
    assert not (tmp_path / "GoerzQ2022.pdf").exists()
    assert "GoerzQ2022" not in bib


def test_delete_config_defaults(bib, tmp_path):
    """The `[delete]` configuration supplies the switch defaults."""
    _make_assets(tmp_path, "GoerzQ2022")
    config.active.delete.remove_assets = True
    config.active.delete.remove_attachments = True
    del bib["GoerzQ2022"]
    assert not (tmp_path / "GoerzQ2022.ingest").exists()
    assert not (tmp_path / "GoerzQ2022.pdf").exists()


def test_delete_keeps_shared_attachment(bib, tmp_path):
    """A file still linked from another entry survives the deletion of
    one of the entries."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # macOS-bookmark fallback
        bib.add_file("GoerzA2023", "GoerzQ2022.pdf", auto_file_location="")
    with pytest.warns(UserWarning, match="still linked"):
        bib.delete("GoerzQ2022", remove_attachments=True)
    assert (tmp_path / "GoerzQ2022.pdf").is_file()
    assert bib["GoerzA2023"].files == ["GoerzA2023.pdf", "GoerzQ2022.pdf"]


def test_delete_unknown_key(bib):
    with pytest.raises(KeyError):
        bib.delete("NoSuchKey")


# -- check audits --------------------------------------------------------- #


def test_check_orphans(bib, tmp_path):
    """Files matching a pattern without an entry are reported once,
    naming every matching class."""
    _make_assets(tmp_path, "GoerzQ2022")  # belongs to an entry
    _make_assets(tmp_path, "SomeOldKey")  # orphaned
    problems = collect_problems(bib)
    orphans = [p for p in problems if p.check == "asset_orphans"]
    assert len(orphans) == 2
    messages = [p.message for p in orphans]
    assert any("'SomeOldKey.ingest' (fulltext, source)" in m for m in messages)
    assert any("'SomeOldKey_summary.md' (summary)" in m for m in messages)
    assert all(p.key is None for p in orphans)


def test_check_orphans_case_mismatch(bib, tmp_path):
    """A file that matches an entry's unit only up to case is reported
    as a case mismatch, not as an orphan: on a case-insensitive
    filesystem it *is* that entry's asset, so the verdict must not
    depend on the platform."""
    (tmp_path / "goerzq2022_summary.md").write_text("summary")
    problems = [p for p in collect_problems(bib) if p.check == "asset_orphans"]
    assert len(problems) == 1
    assert "'goerzq2022_summary.md' (summary)" in problems[0].message
    assert "matches the expected 'GoerzQ2022_summary.md'" in (
        problems[0].message
    )
    assert "belongs to no entry" not in problems[0].message


def test_check_orphans_type_filter(bib, tmp_path):
    """A directory where the pattern expects a file (and vice versa)
    is not an orphan."""
    (tmp_path / "SomeOldKey_summary.md").mkdir()  # dir, not a file
    problems = collect_problems(bib)
    assert not [p for p in problems if p.check == "asset_orphans"]


def test_check_orphans_off(bib, tmp_path):
    """`audit_orphans=False` and a `keys` subset skip the audit."""
    _make_assets(tmp_path, "SomeOldKey")
    problems = collect_problems(bib, audit_orphans=False)
    assert not [p for p in problems if p.check == "asset_orphans"]
    problems = collect_problems(bib, keys=["GoerzQ2022"])
    assert not [p for p in problems if p.check == "asset_orphans"]


def test_check_missing_assets(bib, tmp_path):
    """`audit_assets` reports resolving assets missing from disk,
    per entry and library-level."""
    _make_assets(tmp_path, "GoerzQ2022")
    bib.info["Topics-File"] = "topics.md"
    problems = collect_problems(bib, keys=["GoerzQ2022"], audit_assets=True)
    assert not [p for p in problems if p.check == "assets"]
    problems = collect_problems(bib, keys=["GoerzA2023"], audit_assets=True)
    missing = [p for p in problems if p.check == "assets"]
    assert {p.message.split()[2] for p in missing} == {
        "'summary':",
        "'fulltext':",
        "'source':",
    }
    # whole-library audit also covers the library-level topics.md
    problems = collect_problems(bib, audit_assets=True)
    assert any(
        p.check == "assets" and p.key is None and "'topics'" in p.message
        for p in problems
    )


def test_check_no_assets_configured(bibfile):
    """Without an [assets] map, the audits are no-ops."""
    bib = Library(bibfile)
    problems = collect_problems(bib, audit_assets=True)
    assert not [p for p in problems if p.check in ("assets", "asset_orphans")]
