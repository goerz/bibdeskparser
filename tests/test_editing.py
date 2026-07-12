"""Tests for `bibdeskparser.editing`.

Most tests use a *callable* editor (a plain function receiving the
temporary file's path and rewriting it in place), so no subprocess is
ever launched and the "editor" behavior is visible inline. A fake
command-string `$EDITOR` (a tiny standalone Python script, run with
the same interpreter as the test suite) is used only where the
command-string code path itself -- `_run_editor` resolution/parsing
and the interactive reopen-or-abandon prompt -- is under test.
"""

import os
import subprocess
import sys
import warnings
from unittest.mock import Mock

import pytest
from bibtexparser import model

from bibdeskparser.bdskfile import BibDeskFile
from bibdeskparser.editing import (
    _run_editor,
    edit_entries,
    edit_strings,
    strings_bib_text,
)
from bibdeskparser.entry import Entry
from bibdeskparser.exporting import export_entries
from bibdeskparser.library import Library


def _script_editor(tmp_path, name, code):
    """Write `code` (a Python script body) to `tmp_path / name` and
    return an editor command string that runs it, so that
    `sys.argv[1]` is the path of the file being "edited"."""
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f"{sys.executable} {script}"


def _replace_editor(old, new):
    """A callable editor replacing `old` with `new` in the edited
    file."""

    def editor(path):
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(old, new), encoding="utf-8")

    return editor


def _drop_lines_editor(substring):
    """A callable editor deleting every line containing `substring`."""

    def editor(path):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        text = "".join(line for line in lines if substring not in line)
        path.write_text(text, encoding="utf-8")

    return editor


def _write_editor(text):
    """A callable editor replacing the file content with `text`."""

    def editor(path):
        path.write_text(text, encoding="utf-8")

    return editor


# -- edit_entries: successful edits ----------------------------------- #


def test_successful_field_edit():
    """An editor changing a field's text lands in the `Entry`."""
    entry = Entry(
        "article",
        "Key2026",
        fields={"title": "Old Title", "author": "A. One"},
    )
    edit_entries([entry], editor=_replace_editor("Old Title", "New Title"))
    assert entry["title"] == "New Title"
    assert entry._dirty is True


def test_field_deletion():
    """Removing a field's line in the editor deletes it from the
    `Entry`."""
    entry = Entry(
        "article",
        "Key2026",
        fields={
            "title": "T",
            "author": "A. One",
            "note": "Some note",
        },
    )
    assert entry["note"] == "Some note"
    edit_entries([entry], editor=_drop_lines_editor("note"))
    assert "note" not in entry
    assert entry["title"] == "T"
    assert entry["author"] == "A. One"


def test_files_urls_roundtrip():
    """Editing a `bdsk-file-N`/`bdsk-url-N` line updates
    the attachments/`.urls`.

    Without a `library`, edited file paths are interpreted relative
    to the current working directory, so this reuses two of the real
    PDF fixtures under `tests/Refs/`.
    """
    entry = Entry("article", "Key2026", fields={"title": "T"})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        entry._set_files([BibDeskFile("tests/Refs/GoerzA2023.pdf")])
    entry.add_url("http://example.org/old")

    def editor(path):
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "tests/Refs/GoerzA2023.pdf", "tests/Refs/GoerzQ2022.pdf"
        )
        text = text.replace("http://example.org/old", "http://example.org/new")
        path.write_text(text, encoding="utf-8")

    edit_entries([entry], editor=editor)
    assert entry.files == ["tests/Refs/GoerzQ2022.pdf"]
    assert entry.urls == ("http://example.org/new",)


# -- edit_entries: keywords -------------------------------------------- #


def test_keywords_edit_merges_back():
    """Editing the `keywords = {...}` line updates `entry.keywords`
    and, through it, `library.keywords`."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    bib.add_to_keyword("topic one", "Key2026")
    edit_entries(
        [entry],
        library=bib,
        editor=_replace_editor("{topic one}", "{topic one, topic two}"),
    )
    assert entry.keywords == ("topic one", "topic two")
    assert bib.keywords == {
        "topic one": ("Key2026",),
        "topic two": ("Key2026",),
    }


def test_keywords_line_deletion_clears_keywords():
    """Removing the `keywords` line in the editor clears the entry's
    keywords (the stored field is removed entirely)."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry._set_keywords(("alpha", "beta"))
    edit_entries([entry], editor=_drop_lines_editor("keywords"))
    assert entry.keywords == ()


def test_keywords_reformatting_is_noop():
    """Whitespace-only reformatting of the `keywords` line does not
    dirty the entry (the parsed keywords are unchanged)."""
    model_entry = model.Entry(
        entry_type="article",
        key="Key2026",
        fields=[
            model.Field(key="title", value="{T}"),
            model.Field(key="keywords", value="{alpha, beta}"),
        ],
    )
    entry = Entry._wrap(model_entry)
    assert entry._dirty is False
    edit_entries([entry], editor=_replace_editor("alpha, beta", "alpha,beta"))
    assert entry.keywords == ("alpha", "beta")
    assert entry._dirty is False


def test_one_word_keyword_is_not_flagged_as_macro():
    """A single-word keyword that would pass as a macro name does not
    trigger undefined-macro validation, and survives the edit
    round-trip as literal text."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    bib.add_to_keyword("alpha", "Key2026")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no validation warning expected
        edit_entries(
            [entry],
            library=bib,
            editor=_replace_editor("{alpha}", "{beta}"),
        )
    assert entry.keywords == ("beta",)
    assert bib.keywords == {"beta": ("Key2026",)}
    assert entry._dirty is True  # the keyword genuinely changed


# -- edit_entries: validation failure handling ------------------------ #


def test_validation_failure_abandon(tmp_path, monkeypatch):
    """A non-interactive `input()` (`EOFError`) on validation failure
    abandons the edit, leaving the entry unchanged (command-string
    editor only; a callable editor raises instead)."""
    entry = Entry("article", "Key2026", fields={"title": "Old Title"})
    editor = _script_editor(
        tmp_path,
        "editor_corrupt.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text("@article{Key2026, title = {Old Title")\n',
    )

    def _raise_eof(*_args, **_kwargs):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)

    with pytest.warns(UserWarning):
        edit_entries([entry], editor=editor)

    assert entry["title"] == "Old Title"


def test_validation_failure_reopen_then_fix(tmp_path, monkeypatch):
    """Choosing "reopen" on the first validation failure re-invokes the
    editor; a fake editor that fixes the problem on its second
    invocation lets the edit ultimately succeed."""
    entry = Entry("article", "Key2026", fields={"title": "Old Title"})
    counter_path = tmp_path / "counter.txt"
    code = (
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        f"counter = pathlib.Path({str(counter_path)!r})\n"
        "n = int(counter.read_text()) if counter.exists() else 0\n"
        "n += 1\n"
        "counter.write_text(str(n))\n"
        "if n == 1:\n"
        '    p.write_text("@article{Key2026, title = {Old Title")\n'
        "else:\n"
        "    p.write_text(\n"
        '        "@article{Key2026,\\n\\ttitle = {New Title}\\n}\\n"\n'
        "    )\n"
    )
    editor = _script_editor(tmp_path, "editor_reopen.py", code)

    monkeypatch.setattr("builtins.input", Mock(side_effect=["r"]))

    with pytest.warns(UserWarning):
        edit_entries([entry], editor=editor)

    assert entry["title"] == "New Title"
    assert counter_path.read_text() == "2"


def test_callable_editor_validation_failure_raises(monkeypatch):
    """With a callable editor, a validation failure raises
    `ValueError` (no interactive prompt), leaving the entry
    unchanged."""
    entry = Entry("article", "Key2026", fields={"title": "Old Title"})
    monkeypatch.setattr(
        "builtins.input",
        Mock(side_effect=AssertionError("must not prompt")),
    )
    with pytest.raises(ValueError, match="Validation failed") as excinfo:
        edit_entries(
            [entry],
            editor=_write_editor("@article{Key2026, title = {Old Title"),
        )
    assert "could not parse block" in str(excinfo.value)
    assert entry["title"] == "Old Title"


# -- edit_entries: with a Library -------------------------------------- #


def test_edit_entries_with_library_field_change():
    """A field change merges back even when a `library` is given."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "Old Title"})
    bib["Key2026"] = entry
    edit_entries(
        [entry],
        library=bib,
        editor=_replace_editor("Old Title", "New Title"),
    )
    assert entry["title"] == "New Title"


def test_edit_entries_macro_rename_detection():
    """Renaming an `@string` macro (same value, new name) in the
    edited text is detected as a rename and propagated via
    `library.rename_string`."""
    bib = Library()
    bib.strings["jpb"] = "J. Phys. B"
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["journal"] = "jpb"  # bare macro reference
    bib["Key2026"] = entry

    edit_entries(
        [entry],
        library=bib,
        editor=_replace_editor(
            "@string{jpb = {J. Phys. B}}",
            "@string{jphysb = {J. Phys. B}}",
        ),
    )

    strings = dict(bib.strings)
    assert "jphysb" in strings
    assert "jpb" not in strings
    assert entry["journal"] == "jphysb"


def test_export_edit_roundtrip_invariant():
    """The text presented to the editor is byte-for-byte the
    `export_entries(..., format="default")` output for the same
    entries and strings -- i.e., exactly what `Library.export`
    returns -- so piping an export back into a no-op edit is
    guaranteed to be a no-op."""
    bib = Library()
    bib.strings["jpb"] = "J. Phys. B"
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["journal"] = "jpb"  # bare macro reference
    bib["Key2026"] = entry

    captured = []
    edit_entries(
        [entry],
        library=bib,
        editor=lambda p: captured.append(p.read_text(encoding="utf-8")),
    )
    expected = export_entries(
        [entry], strings=dict(bib.strings), format="default"
    )
    assert captured == [expected]
    assert bib.export("Key2026") == expected
    assert entry["title"] == "T"  # the no-op edit changed nothing
    assert entry["journal"] == "jpb"


# -- edit_strings -------------------------------------------------------- #


def test_strings_bib_text():
    """`strings_bib_text` renders sorted `@string` lines (and the
    empty string for an empty mapping)."""
    assert strings_bib_text({}) == ""
    assert strings_bib_text({"b": "Two", "a": "One"}) == (
        "@string{a = {One}}\n@string{b = {Two}}\n"
    )


def test_edit_strings():
    """Editing the `@string` definitions changes a value and adds a
    new macro."""
    bib = Library()
    bib.strings["jpb"] = "J. Phys. B"
    bib.strings["prl"] = "Phys. Rev. Lett."

    def editor(path):
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "@string{jpb = {J. Phys. B}}",
            "@string{jpb = {Journal of Physics B}}",
        )
        text += "@string{njp = {New J. Phys.}}\n"
        path.write_text(text, encoding="utf-8")

    edit_strings(bib, editor=editor)

    strings = dict(bib.strings)
    assert strings["jpb"] == "Journal of Physics B"
    assert strings["njp"] == "New J. Phys."
    assert strings["prl"] == "Phys. Rev. Lett."


def test_edit_strings_failed_deletion_raises():
    """With a callable editor, deleting a macro that is still
    referenced by an entry raises `ValueError`; other changes from
    the same round are already applied (documented caveat)."""
    bib = Library()
    bib.strings["jpb"] = "J. Phys. B"
    bib.strings["prl"] = "Phys. Rev. Lett."
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry["journal"] = "jpb"  # bare macro reference
    bib["Key2026"] = entry

    with pytest.raises(ValueError, match="jpb"):
        edit_strings(
            bib,
            editor=_write_editor("@string{prl = {Physical Review Letters}}\n"),
        )

    strings = dict(bib.strings)
    assert strings["jpb"] == "J. Phys. B"  # failed deletion: unchanged
    assert strings["prl"] == "Physical Review Letters"  # already merged


# -- format / editor resolution ----------------------------------------- #


def test_format_raises_value_error(monkeypatch):
    """A `format` other than `"default"` raises `ValueError` before
    ever touching the filesystem or invoking an editor."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=AssertionError("must not run"))
    )
    with pytest.raises(ValueError):
        edit_entries([entry], format="raw")
    with pytest.raises(ValueError):
        edit_entries([entry], format="minimal")


def test_editor_resolution_defaults_to_vi(monkeypatch):
    """With no `editor` argument and no `$EDITOR`, `"vi"` is run."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    monkeypatch.delenv("EDITOR", raising=False)
    mock_run = Mock()
    monkeypatch.setattr(subprocess, "run", mock_run)
    edit_entries([entry])
    command = mock_run.call_args[0][0]
    assert command[0] == "vi"


def test_run_editor_callable(monkeypatch):
    """A callable editor is called with the path; no subprocess is
    ever started."""
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=AssertionError("must not run"))
    )
    calls = []
    _run_editor(calls.append, "file.bib")
    assert calls == ["file.bib"]


def test_run_editor_windows_quoted_path(monkeypatch):
    """On Windows, a quoted editor path is unwrapped before running."""
    monkeypatch.setattr(os, "name", "nt")
    mock_run = Mock()
    monkeypatch.setattr(subprocess, "run", mock_run)
    _run_editor(r'"C:\Program Files\Editor\ed.exe"', "file.bib")
    args = mock_run.call_args[0][0]
    assert args == [r"C:\Program Files\Editor\ed.exe", "file.bib"]


def test_run_editor_windows_midtoken_quote_fallback(monkeypatch):
    """A mid-token quote (which `shlex` rejects in non-POSIX mode) falls
    back to treating the whole command as a single program path."""
    monkeypatch.setattr(os, "name", "nt")
    mock_run = Mock()
    monkeypatch.setattr(subprocess, "run", mock_run)
    command = r'C:\Program" "Files\Editor\ed.exe'
    _run_editor(command, "file.bib")
    args = mock_run.call_args[0][0]
    assert args == [command, "file.bib"]


# -- edit_entries: file attachments ------------------------------------ #


def test_edit_file_change_library_relative(tmp_path):
    """With a saved `library`, an edited `bdsk-file-N` path is
    interpreted relative to the library's `.bib` directory (not the
    CWD)."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    bib.save(tmp_path / "lib.bib")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        bib.add_file("Key2026", tmp_path / "a.pdf")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        edit_entries(
            [entry],
            library=bib,
            editor=_replace_editor("a.pdf", "b.pdf"),
        )
    assert entry.files == ["b.pdf"]


def test_edit_file_nonexistent_path_raises(tmp_path):
    """An edited `bdsk-file-N` path that does not exist relative to
    the library directory is a validation problem, leaving the
    attachment unchanged."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    bib.save(tmp_path / "lib.bib")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        bib.add_file("Key2026", tmp_path / "a.pdf")

    with pytest.raises(ValueError, match="does not exist"):
        edit_entries(
            [entry],
            library=bib,
            editor=_replace_editor("a.pdf", "ghost.pdf"),
        )
    assert entry.files == ["a.pdf"]


def test_edit_file_change_without_library_path_raises(tmp_path):
    """Changing a `bdsk-file-N` line of a never-saved library is a
    validation problem (linked files are stored relative to the
    library's `.bib` file, which does not exist yet)."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        entry._set_files(
            [BibDeskFile(tmp_path / "b.pdf", relative_to=tmp_path)]
        )
    files_before = entry.files

    with pytest.raises(ValueError, match="no file path"):
        edit_entries(
            [entry],
            library=bib,
            editor=_replace_editor("b.pdf", "c.pdf"),
        )
    assert entry.files == files_before
