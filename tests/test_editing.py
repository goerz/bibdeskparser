"""Tests for `bibdeskparser.editing`.

A fake `$EDITOR` (a tiny standalone Python script, run with the same
interpreter as the test suite) is used throughout, so no real
interactive program is ever launched and the tests can never hang.
"""

import subprocess
import sys
import warnings
from unittest.mock import Mock

import pytest
from bibtexparser import model

from bibdeskparser.bdskfile import BibDeskFile
from bibdeskparser.editing import edit_entries, edit_strings
from bibdeskparser.entry import Entry
from bibdeskparser.library import Library


def _script_editor(tmp_path, name, code):
    """Write `code` (a Python script body) to `tmp_path / name` and
    return an editor command string that runs it, so that
    `sys.argv[1]` is the path of the file being "edited"."""
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f"{sys.executable} {script}"


# -- edit_entries: successful edits ----------------------------------- #


def test_successful_field_edit(tmp_path):
    """A fake editor changing a field's text lands in the `Entry`."""
    entry = Entry(
        "article",
        "Key2026",
        fields={"title": "Old Title", "author": "A. One"},
    )
    editor = _script_editor(
        tmp_path,
        "editor_title.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text(p.read_text().replace("Old Title", "New Title"))\n',
    )
    edit_entries([entry], editor=editor)
    assert entry["title"] == "New Title"
    assert entry.dirty is True


def test_field_deletion(tmp_path):
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
    editor = _script_editor(
        tmp_path,
        "editor_delete_note.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "lines = p.read_text().splitlines(keepends=True)\n"
        'lines = [l for l in lines if "note" not in l]\n'
        'p.write_text("".join(lines))\n',
    )
    edit_entries([entry], editor=editor)
    assert "note" not in entry
    assert entry["title"] == "T"
    assert entry["author"] == "A. One"


def test_files_urls_roundtrip(tmp_path):
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
    entry.urls = ["http://example.org/old"]
    editor = _script_editor(
        tmp_path,
        "editor_files_urls.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "text = p.read_text()\n"
        "text = text.replace(\n"
        '    "tests/Refs/GoerzA2023.pdf", "tests/Refs/GoerzQ2022.pdf"\n'
        ")\n"
        "text = text.replace(\n"
        '    "http://example.org/old", "http://example.org/new"\n'
        ")\n"
        "p.write_text(text)\n",
    )
    edit_entries([entry], editor=editor)
    assert entry.files == ["tests/Refs/GoerzQ2022.pdf"]
    assert entry.urls == ["http://example.org/new"]


# -- edit_entries: keywords -------------------------------------------- #


def test_keywords_edit_merges_back(tmp_path):
    """Editing the `keywords = {...}` line updates `entry.keywords`
    and, through it, `library.keywords`."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    bib.add_to_keyword("topic one", "Key2026")
    editor = _script_editor(
        tmp_path,
        "editor_keywords.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "p.write_text(\n"
        '    p.read_text().replace("{topic one}", "{topic one, topic two}")\n'
        ")\n",
    )
    edit_entries([entry], library=bib, editor=editor)
    assert entry.keywords == ("topic one", "topic two")
    assert bib.keywords == {
        "topic one": ("Key2026",),
        "topic two": ("Key2026",),
    }


def test_keywords_line_deletion_clears_keywords(tmp_path):
    """Removing the `keywords` line in the editor clears the entry's
    keywords (the stored field is removed entirely)."""
    entry = Entry("article", "Key2026", fields={"title": "T"})
    entry._set_keywords(("alpha", "beta"))
    editor = _script_editor(
        tmp_path,
        "editor_delete_keywords.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "lines = p.read_text().splitlines(keepends=True)\n"
        'lines = [l for l in lines if "keywords" not in l]\n'
        'p.write_text("".join(lines))\n',
    )
    edit_entries([entry], editor=editor)
    assert entry.keywords == ()


def test_keywords_reformatting_is_noop(tmp_path):
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
    assert entry.dirty is False
    editor = _script_editor(
        tmp_path,
        "editor_reformat_keywords.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text(p.read_text().replace("alpha, beta", "alpha,beta"))\n',
    )
    edit_entries([entry], editor=editor)
    assert entry.keywords == ("alpha", "beta")


def test_one_word_keyword_is_not_flagged_as_macro(tmp_path):
    """A single-word keyword that would pass as a macro name does not
    trigger undefined-macro validation, and survives the edit
    round-trip as literal text."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    bib.add_to_keyword("alpha", "Key2026")
    editor = _script_editor(
        tmp_path,
        "editor_one_word_keyword.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text(p.read_text().replace("{alpha}", "{beta}"))\n',
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no validation warning expected
        edit_entries([entry], library=bib, editor=editor)
    assert entry.keywords == ("beta",)
    assert bib.keywords == {"beta": ("Key2026",)}
    assert entry.dirty is True  # the keyword genuinely changed


# -- edit_entries: validation failure handling ------------------------ #


def test_validation_failure_abandon(tmp_path, monkeypatch):
    """A non-interactive `input()` (`EOFError`) on validation failure
    abandons the edit, leaving the entry unchanged."""
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


# -- edit_entries: with a Library -------------------------------------- #


def test_edit_entries_with_library_field_change(tmp_path):
    """A field change merges back even when a `library` is given."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "Old Title"})
    bib["Key2026"] = entry
    editor = _script_editor(
        tmp_path,
        "editor_lib_field.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text(p.read_text().replace("Old Title", "New Title"))\n',
    )
    edit_entries([entry], library=bib, editor=editor)
    assert entry["title"] == "New Title"


def test_edit_entries_macro_rename_detection(tmp_path):
    """Renaming an `@string` macro (same value, new name) in the
    edited text is detected as a rename and propagated via
    `library.rename_string`."""
    bib = Library()
    bib.strings["jpb"] = "J. Phys. B"
    entry = Entry("article", "Key2026", fields={"title": "T"})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entry["journal"] = "jpb"  # bare macro reference
    bib["Key2026"] = entry

    editor = _script_editor(
        tmp_path,
        "editor_rename_macro.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "text = p.read_text()\n"
        "text = text.replace(\n"
        '    "@string{jpb = {J. Phys. B}}",\n'
        '    "@string{jphysb = {J. Phys. B}}",\n'
        ")\n"
        "p.write_text(text)\n",
    )
    edit_entries([entry], library=bib, editor=editor)

    strings = dict(bib.strings)
    assert "jphysb" in strings
    assert "jpb" not in strings
    assert entry["journal"] == "jphysb"


# -- edit_strings -------------------------------------------------------- #


def test_edit_strings(tmp_path):
    """Editing the `@string` definitions changes a value and adds a
    new macro."""
    bib = Library()
    bib.strings["jpb"] = "J. Phys. B"
    bib.strings["prl"] = "Phys. Rev. Lett."

    editor = _script_editor(
        tmp_path,
        "editor_strings.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "text = p.read_text()\n"
        "text = text.replace(\n"
        '    "@string{jpb = {J. Phys. B}}",\n'
        '    "@string{jpb = {Journal of Physics B}}",\n'
        ")\n"
        'text += "@string{njp = {New J. Phys.}}\\n"\n'
        "p.write_text(text)\n",
    )
    edit_strings(bib, editor=editor)

    strings = dict(bib.strings)
    assert strings["jpb"] == "Journal of Physics B"
    assert strings["njp"] == "New J. Phys."
    assert strings["prl"] == "Phys. Rev. Lett."


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
    editor = _script_editor(
        tmp_path,
        "editor_swap_file.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text(p.read_text().replace("a.pdf", "b.pdf"))\n',
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        edit_entries([entry], library=bib, editor=editor)
    assert entry.files == ["b.pdf"]


def test_edit_file_nonexistent_path_abandons(tmp_path, monkeypatch):
    """An edited `bdsk-file-N` path that does not exist relative to
    the library directory is a validation problem; abandoning leaves
    the attachment unchanged."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    bib.save(tmp_path / "lib.bib")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        bib.add_file("Key2026", tmp_path / "a.pdf")
    editor = _script_editor(
        tmp_path,
        "editor_ghost_file.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text(p.read_text().replace("a.pdf", "ghost.pdf"))\n',
    )

    def _raise_eof(*_args, **_kwargs):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)

    with pytest.warns(UserWarning, match="does not exist"):
        edit_entries([entry], library=bib, editor=editor)
    assert entry.files == ["a.pdf"]


def test_edit_file_change_without_library_path_abandons(tmp_path, monkeypatch):
    """Changing a `bdsk-file-N` line of a never-saved library is a
    validation problem (linked files are stored relative to the
    library's `.bib` file, which does not exist yet)."""
    bib = Library()
    entry = Entry("article", "Key2026", fields={"title": "T"})
    bib["Key2026"] = entry
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # possibly no macOS bookmark
        entry._set_files([BibDeskFile(tmp_path / "b.pdf")])
    files_before = entry.files
    editor = _script_editor(
        tmp_path,
        "editor_change_unsaved.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        'p.write_text(p.read_text().replace("b.pdf", "c.pdf"))\n',
    )

    def _raise_eof(*_args, **_kwargs):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)

    with pytest.warns(UserWarning, match="no file path"):
        edit_entries([entry], library=bib, editor=editor)
    assert entry.files == files_before
