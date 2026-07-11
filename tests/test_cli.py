"""Tests for the `bibdeskparser` command-line interface."""

import json
import shutil
import sys
import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner

import bibdeskparser
import bibdeskparser.config as config
from bibdeskparser import Library
from bibdeskparser.cli import main

REFS_DIR = Path(__file__).parent / "Refs"


@pytest.fixture(autouse=True)
def _reset_config(tmp_path, monkeypatch):
    """Reset the process-global configuration around every test here.

    The configuration is process-global (see `tests/test_config.py`),
    and the CLI's bibfile resolution reads `default_bib_file` from it.
    Point `$XDG_CONFIG_HOME` at an empty directory so that a real
    user-level `bibdeskparser.toml` can never leak into a test.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    config.reset()
    yield
    config.reset()


@pytest.fixture(name="bibfile")
def fixture_bibfile(tmp_path):
    """A copy of `refs.bib` in `tmp_path`, with its linked PDFs.

    The entries link the PDFs by paths relative to the `.bib` file, so
    the PDFs must be copied along for `save()` not to warn about
    missing linked files. All mutating tests run against this copy.
    """
    for pdf in REFS_DIR.glob("*.pdf"):
        shutil.copy(pdf, tmp_path)
    return Path(shutil.copy(REFS_DIR / "refs.bib", tmp_path))


@pytest.fixture(name="runner")
def fixture_runner():
    try:
        # click < 8.2 mixes stderr into stdout unless told otherwise
        return CliRunner(mix_stderr=False)
    except TypeError:  # click >= 8.2 always captures stderr separately
        return CliRunner()


def _load(bibfile):
    """Load `bibfile` as a `Library`, suppressing load-time warnings
    (`refs.bib` deliberately contains a duplicate citation key)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Library(bibfile)


def _run(runner, *args):
    """Invoke the CLI with `args`, asserting success."""
    result = runner.invoke(main, [str(arg) for arg in args])
    assert result.exit_code == 0, result.output + result.stderr
    return result


def _script_editor(tmp_path, name, code):
    """A fake `$EDITOR` command (as in `tests/test_editing.py`)."""
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f"{sys.executable} {script}"


# -- read-only commands ------------------------------------------------ #


def test_keys(runner, bibfile):
    result = _run(runner, "keys", bibfile)
    lines = result.output.splitlines()
    assert lines == list(_load(bibfile))
    assert "GoerzJPB2011" in lines


def test_keys_json(runner, bibfile):
    result = _run(runner, "keys", bibfile, "--json")
    data = json.loads(result.output)
    assert data == list(_load(bibfile))


def test_show(runner, bibfile):
    result = _run(runner, "show", bibfile, "GoerzJPB2011")
    assert result.output.startswith("GoerzJPB2011 (article)")
    assert "journal:" in result.output
    assert "groups:" in result.output
    assert "My Papers" in result.output
    assert "GoerzJPB11.pdf" in result.output


def test_show_multiple(runner, bibfile):
    result = _run(runner, "show", bibfile, "GoerzJPB2011", "GoerzNJP2014")
    assert "GoerzJPB2011 (article)" in result.output
    assert "GoerzNJP2014 (article)" in result.output


def test_show_json(runner, bibfile):
    result = _run(runner, "show", bibfile, "GoerzJPB2011", "--json")
    data = json.loads(result.output)
    assert set(data) == {"GoerzJPB2011"}
    entry = data["GoerzJPB2011"]
    assert set(entry) == {
        "entry_type",
        "key",
        "fields",
        "groups",
        "keywords",
        "files",
        "urls",
        "date_added",
        "date_modified",
    }
    assert entry["entry_type"] == "article"
    assert entry["key"] == "GoerzJPB2011"
    assert isinstance(entry["fields"], dict)
    assert entry["fields"]["journal"] == "jpb"
    assert entry["groups"] == ["My Papers"]
    assert entry["files"] == ["GoerzJPB11.pdf"]
    assert isinstance(entry["urls"], list)
    lib = _load(bibfile)
    assert entry["date_added"] == lib["GoerzJPB2011"].date_added.isoformat()


def test_search(runner, bibfile):
    result = _run(runner, "search", bibfile, "Universitaet Kassel")
    assert result.output.splitlines() == ["GoerzPhd2015"]


def test_search_json(runner, bibfile):
    result = _run(runner, "search", bibfile, "Sebastian", "--json")
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert "GoerzQ2022" in data


def test_search_options(runner, bibfile):
    result = _run(
        runner,
        "search",
        bibfile,
        r"^10\.1103/",
        "--field",
        "doi",
        "--match",
        "regex",
    )
    assert result.output.splitlines() == ["GoerzPRA2014"]
    result = _run(
        runner,
        "search",
        bibfile,
        "pra",
        "--field",
        "journal",
        "--field",
        "key",
        "--match",
        "exact",
    )
    assert result.output.splitlines() == ["GoerzPRA2014"]


def test_search_no_results(runner, bibfile):
    result = _run(runner, "search", bibfile, "no such thing anywhere")
    assert result.output == ""


def test_search_bad_match(runner, bibfile):
    result = runner.invoke(
        main, ["search", str(bibfile), "x", "--match", "bogus"]
    )
    assert result.exit_code != 0


def test_search_bad_regex(runner, bibfile):
    result = runner.invoke(
        main, ["search", str(bibfile), "(", "--match", "regex"]
    )
    assert result.exit_code != 0
    assert "invalid regular expression" in result.stderr


def test_groups(runner, bibfile):
    result = _run(runner, "groups", bibfile)
    assert "My Papers: " in result.output
    assert "GoerzJPB2011, GoerzNJP2014" in result.output


def test_groups_json(runner, bibfile):
    result = _run(runner, "groups", bibfile, "--json")
    data = json.loads(result.output)
    expected = {
        name: list(keys) for name, keys in _load(bibfile).groups.items()
    }
    assert data == expected
    assert "GoerzJPB2011" in data["My Papers"]


def test_keywords(runner, bibfile):
    result = _run(runner, "keywords", bibfile)
    assert "optimal control: GoerzDiploma2010" in result.output


def test_keywords_json(runner, bibfile):
    result = _run(runner, "keywords", bibfile, "--json")
    data = json.loads(result.output)
    assert data["optimal control"] == ["GoerzDiploma2010"]


def test_strings(runner, bibfile):
    result = _run(runner, "strings", bibfile)
    assert "jpb = J. Phys. B" in result.output


def test_strings_json(runner, bibfile):
    result = _run(runner, "strings", bibfile, "--json")
    data = json.loads(result.output)
    assert data == dict(_load(bibfile).strings)
    assert data["jpb"] == "J. Phys. B"


def test_duplicate_keys(runner, bibfile):
    result = _run(runner, "duplicate_keys", bibfile)
    assert result.output.splitlines() == ["GoerzJOSS2025"]


def test_duplicate_keys_json(runner, bibfile):
    result = _run(runner, "duplicate_keys", bibfile, "--json")
    assert json.loads(result.output) == ["GoerzJOSS2025"]


def test_timestamp(runner, bibfile):
    result = _run(runner, "timestamp", bibfile)
    expected = _load(bibfile).timestamp.isoformat()
    assert result.output.strip() == expected


def test_timestamp_json(runner, bibfile):
    result = _run(runner, "timestamp", bibfile, "--json")
    expected = _load(bibfile).timestamp.isoformat()
    assert json.loads(result.output) == expected


def test_render(runner, bibfile):
    result = _run(runner, "render", bibfile, "GoerzJPB2011")
    assert "quantum speed limit" in result.output
    assert "Goerz" in result.output


def test_render_html_numbered_list(runner, bibfile):
    result = _run(
        runner,
        "render",
        bibfile,
        "GoerzJPB2011",
        "GoerzNJP2014",
        "--format",
        "html",
        "--style",
        "numbered list",
    )
    assert "<ol>" in result.output


def test_export(runner, bibfile):
    result = _run(runner, "export", bibfile, "GoerzJPB2011")
    assert "@article{GoerzJPB2011," in result.output
    # the @string macros used by the entry are included
    assert "@string{jpb" in result.output


def test_export_outfile(runner, bibfile, tmp_path):
    outfile = tmp_path / "out.bib"
    result = _run(
        runner, "export", bibfile, "GoerzJPB2011", "--outfile", outfile
    )
    assert result.output == ""
    assert "@article{GoerzJPB2011," in outfile.read_text(encoding="utf-8")


def test_export_minimal(runner, bibfile):
    result = _run(
        runner, "export", bibfile, "GoerzJPB2011", "--format", "minimal"
    )
    assert "@article{GoerzJPB2011," in result.output
    assert "abstract" not in result.output


# -- mutating commands -------------------------------------------------- #


def test_rekey(runner, bibfile):
    _run(runner, "rekey", bibfile, "GoerzDiploma2010", "Goerz2010")
    lib = _load(bibfile)
    assert "Goerz2010" in lib
    assert "GoerzDiploma2010" not in lib


def test_delete(runner, bibfile):
    _run(runner, "delete", bibfile, "GoerzDiploma2010", "GoerzPhd2015")
    lib = _load(bibfile)
    assert "GoerzDiploma2010" not in lib
    assert "GoerzPhd2015" not in lib


def test_add_to_group(runner, bibfile):
    _run(runner, "add_to_group", bibfile, "Preprints", "GoerzDiploma2010")
    lib = _load(bibfile)
    assert "GoerzDiploma2010" in lib.groups["Preprints"]


def test_remove_from_group(runner, bibfile):
    _run(runner, "remove_from_group", bibfile, "Preprints", "Aiello2605.00152")
    assert _load(bibfile).groups["Preprints"] == ()


def test_set_group(runner, bibfile):
    _run(
        runner,
        "set_group",
        bibfile,
        "Theses",
        "GoerzDiploma2010",
        "GoerzPhd2015",
    )
    lib = _load(bibfile)
    assert lib.groups["Theses"] == ("GoerzDiploma2010", "GoerzPhd2015")


def test_set_group_empty(runner, bibfile):
    _run(runner, "set_group", bibfile, "Empty Group")
    assert _load(bibfile).groups["Empty Group"] == ()


def test_delete_group(runner, bibfile):
    _run(runner, "delete_group", bibfile, "Preprints")
    assert "Preprints" not in _load(bibfile).groups


def test_set_string(runner, bibfile):
    _run(runner, "set_string", bibfile, "njpx", "New Journal X")
    assert _load(bibfile).strings["njpx"] == "New Journal X"


def test_delete_string(runner, bibfile):
    _run(runner, "set_string", bibfile, "unused", "Unused Journal")
    _run(runner, "delete_string", bibfile, "unused")
    assert "unused" not in _load(bibfile).strings


def test_rename_string(runner, bibfile):
    _run(runner, "rename_string", bibfile, "jpb", "jphysb")
    lib = _load(bibfile)
    assert "jphysb" in lib.strings
    assert "jpb" not in lib.strings
    assert lib["GoerzJPB2011"]["journal"] == "jphysb"


def test_add_to_keyword(runner, bibfile):
    _run(runner, "add_to_keyword", bibfile, "testing", "GoerzJPB2011")
    assert _load(bibfile).keywords["testing"] == ("GoerzJPB2011",)


def test_remove_from_keyword(runner, bibfile):
    _run(
        runner,
        "remove_from_keyword",
        bibfile,
        "optimal control",
        "GoerzDiploma2010",
    )
    assert "optimal control" not in _load(bibfile).keywords


def test_add_file(runner, bibfile, tmp_path):
    (tmp_path / "extra.pdf").write_bytes(b"%PDF-1.4 fake")
    _run(runner, "add_file", bibfile, "GoerzDiploma2010", "extra.pdf")
    assert _load(bibfile)["GoerzDiploma2010"].files == ["extra.pdf"]


def test_add_file_no_check_exists(runner, bibfile):
    _run(
        runner,
        "add_file",
        bibfile,
        "GoerzDiploma2010",
        "ghost.pdf",
        "--no-check-exists",
    )
    assert _load(bibfile)["GoerzDiploma2010"].files == ["ghost.pdf"]


def test_add_file_missing_fails(runner, bibfile):
    result = runner.invoke(
        main, ["add_file", str(bibfile), "GoerzDiploma2010", "ghost.pdf"]
    )
    assert result.exit_code == 1
    assert "Error" in result.stderr
    assert "Traceback" not in result.stderr


def test_replace_file(runner, bibfile, tmp_path):
    (tmp_path / "new.pdf").write_bytes(b"%PDF-1.4 fake")
    _run(
        runner,
        "replace_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB11.pdf",
        "new.pdf",
    )
    assert _load(bibfile)["GoerzJPB2011"].files == ["new.pdf"]
    # without --remove, the old file stays on disk
    assert (tmp_path / "GoerzJPB11.pdf").exists()


def test_unlink_file(runner, bibfile, tmp_path):
    _run(runner, "unlink_file", bibfile, "GoerzJPB2011", "GoerzJPB11.pdf")
    assert _load(bibfile)["GoerzJPB2011"].files == []
    assert (tmp_path / "GoerzJPB11.pdf").exists()


def test_unlink_file_remove(runner, bibfile, tmp_path):
    _run(
        runner,
        "unlink_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB11.pdf",
        "--remove",
    )
    assert _load(bibfile)["GoerzJPB2011"].files == []
    assert not (tmp_path / "GoerzJPB11.pdf").exists()


def test_rename_file(runner, bibfile, tmp_path):
    _run(
        runner,
        "rename_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB11.pdf",
        "renamed.pdf",
    )
    assert _load(bibfile)["GoerzJPB2011"].files == ["renamed.pdf"]
    assert (tmp_path / "renamed.pdf").exists()
    assert not (tmp_path / "GoerzJPB11.pdf").exists()


def test_add_url(runner, bibfile):
    _run(runner, "add_url", bibfile, "GoerzJPB2011", "https://example.org/x")
    assert "https://example.org/x" in _load(bibfile)["GoerzJPB2011"].urls


def test_replace_url(runner, bibfile):
    old = "http://michaelgoerz.net/research/diploma_thesis.pdf"
    new = "https://example.org/thesis.pdf"
    _run(runner, "replace_url", bibfile, "GoerzDiploma2010", old, new)
    assert _load(bibfile)["GoerzDiploma2010"].urls == (new,)


def test_remove_url(runner, bibfile):
    url = "http://michaelgoerz.net/research/diploma_thesis.pdf"
    _run(runner, "remove_url", bibfile, "GoerzDiploma2010", url)
    assert _load(bibfile)["GoerzDiploma2010"].urls == ()


def test_edit(runner, bibfile, tmp_path):
    editor = _script_editor(
        tmp_path,
        "editor_title.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "p.write_text(p.read_text().replace(\n"
        '    "trapped neutral atoms", "confined neutral atoms"\n'
        "))\n",
    )
    _run(runner, "edit", bibfile, "GoerzJPB2011", "--editor", editor)
    title = _load(bibfile)["GoerzJPB2011"]["title"]
    assert "confined neutral atoms" in title
    assert "trapped" not in title


def test_edit_strings(runner, bibfile, tmp_path):
    editor = _script_editor(
        tmp_path,
        "editor_strings.py",
        "import sys, pathlib\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "p.write_text(p.read_text().replace(\n"
        '    "@string{jpb = {J. Phys. B}}",\n'
        '    "@string{jpb = {Journal of Physics B}}",\n'
        "))\n",
    )
    _run(runner, "edit_strings", bibfile, "--editor", editor)
    assert _load(bibfile).strings["jpb"] == "Journal of Physics B"


# -- bibfile resolution ------------------------------------------------- #


def test_explicit_bibfile(runner, bibfile, tmp_path, monkeypatch):
    """An explicit bibfile works from an unrelated working directory."""
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    result = _run(runner, "keys", bibfile)
    assert "GoerzJPB2011" in result.output.splitlines()


def test_default_bib_file_from_cwd(runner, bibfile, tmp_path, monkeypatch):
    """`default_bib_file` from a `bibdeskparser.toml` in the cwd."""
    (tmp_path / "bibdeskparser.toml").write_text(
        'default_bib_file = "refs.bib"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = _run(runner, "keys")
    assert "GoerzJPB2011" in result.output.splitlines()


def test_default_bib_file_from_xdg(runner, bibfile, tmp_path, monkeypatch):
    """`default_bib_file` from the XDG config location."""
    monkeypatch.delenv("BIBDESKPARSER_CONFIG")
    xdg_dir = tmp_path / "xdg-config" / "bibdeskparser"
    xdg_dir.mkdir(parents=True)
    (xdg_dir / "bibdeskparser.toml").write_text(
        # forward slashes keep the path a valid TOML basic string on
        # Windows (backslashes would be read as escape sequences)
        f'default_bib_file = "{bibfile.as_posix()}"\n',
        encoding="utf-8",
    )
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    result = _run(runner, "keys")
    assert "GoerzJPB2011" in result.output.splitlines()


def test_default_bib_file_tilde_expansion(
    runner, bibfile, tmp_path, monkeypatch
):
    """A leading `~` in `default_bib_file` expands to `$HOME`."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Windows `expanduser` resolves `~` from USERPROFILE, not HOME
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "bibdeskparser.toml").write_text(
        'default_bib_file = "~/refs.bib"\n', encoding="utf-8"
    )
    monkeypatch.chdir(workdir)
    result = _run(runner, "keys")
    assert "GoerzJPB2011" in result.output.splitlines()


def test_default_bib_file_envvar_expansion(
    runner, bibfile, tmp_path, monkeypatch
):
    """`$VAR` in `default_bib_file` expands from the environment."""
    monkeypatch.setenv("BIBDESKPARSER_TEST_DIR", str(tmp_path))
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "bibdeskparser.toml").write_text(
        'default_bib_file = "$BIBDESKPARSER_TEST_DIR/refs.bib"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(workdir)
    result = _run(runner, "keys")
    assert "GoerzJPB2011" in result.output.splitlines()


def test_no_bibfile_no_config(runner, tmp_path, monkeypatch):
    """No explicit bibfile and no configured default is a usage error."""
    workdir = tmp_path / "empty"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    result = runner.invoke(main, ["keys"])
    assert result.exit_code == 2
    assert "default_bib_file" in result.stderr
    assert "BIBFILE" in result.stderr


def test_nonexistent_bibfile(runner, tmp_path):
    result = runner.invoke(main, ["keys", str(tmp_path / "missing.bib")])
    assert result.exit_code == 1
    assert "bibfile not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_non_bib_first_arg_uses_default(
    runner, bibfile, tmp_path, monkeypatch
):
    """A first argument not ending in `.bib` is a command argument."""
    (tmp_path / "bibdeskparser.toml").write_text(
        'default_bib_file = "refs.bib"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = _run(runner, "show", "GoerzDiploma2010")
    assert result.output.startswith("GoerzDiploma2010 (mastersthesis)")


# -- error handling ------------------------------------------------------ #


def test_rekey_unknown_key(runner, bibfile):
    result = runner.invoke(
        main, ["rekey", str(bibfile), "NoSuchKey", "NewKey"]
    )
    assert result.exit_code == 1
    assert "NoSuchKey" in result.stderr
    assert "'NoSuchKey'" not in result.stderr  # KeyError quotes stripped
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.output
    # the message is a single line
    errors = [
        line
        for line in result.stderr.splitlines()
        if line.startswith("Error:")
    ]
    assert len(errors) == 1


def test_add_to_group_unknown_group(runner, bibfile):
    result = runner.invoke(
        main, ["add_to_group", str(bibfile), "No Such Group", "GoerzJPB2011"]
    )
    assert result.exit_code == 1
    assert "No Such Group" in result.stderr
    assert "Traceback" not in result.stderr


def test_delete_string_in_use_fails(runner, bibfile):
    """Deleting a macro that is still referenced is a clean error."""
    result = runner.invoke(main, ["delete_string", str(bibfile), "jpb"])
    assert result.exit_code == 1
    assert "jpb" in result.stderr
    assert "Traceback" not in result.stderr
    # nothing was saved
    assert "jpb" in _load(bibfile).strings


# -- --version / --help -------------------------------------------------- #


def test_version(runner):
    result = _run(runner, "--version")
    assert bibdeskparser.__version__ in result.output


def test_help(runner):
    result = _run(runner, "--help")
    assert "Usage:" in result.output
    assert "Commands:" in result.output
    assert "rekey" in result.output
    assert "edit_strings" in result.output


def test_show_help(runner):
    result = _run(runner, "show", "--help")
    assert "[BIBFILE]" in result.output
    assert "KEY..." in result.output
    assert "--json" in result.output


def test_add_file_help(runner):
    result = _run(runner, "add_file", "--help")
    assert "[BIBFILE]" in result.output
    assert "--no-check-exists" in result.output
