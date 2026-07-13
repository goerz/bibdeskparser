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
    config.active.reset()
    yield
    config.active.reset()


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


def test_eval_format_spec(runner, bibfile):
    """`eval_format_spec` prints the key a format yields, without
    modifying the `.bib` file."""
    before = bibfile.read_text(encoding="utf-8")
    result = _run(
        runner, "eval_format_spec", bibfile, "GoerzPRA2014", "%a1%Y%u0"
    )
    assert result.output.strip() == "Goerz2014"
    assert bibfile.read_text(encoding="utf-8") == before


def test_eval_format_spec_json(runner, bibfile):
    result = _run(
        runner,
        "eval_format_spec",
        bibfile,
        "GoerzPRA2014",
        "%a1%Y%u0",
        "--json",
    )
    assert json.loads(result.output) == "Goerz2014"


def test_eval_format_spec_from_config(runner, bibfile):
    """Without a FORMAT argument, the `[auto_key]` format from the
    `bibdeskparser.toml` next to the `.bib` file is used."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[auto_key]\nformat_spec = "%a1%c{journal}0%Y%u0"\n',
        encoding="utf-8",
    )
    result = _run(runner, "eval_format_spec", bibfile, "GoerzPRA2014")
    assert result.output.strip() == "GoerzPRA2014"  # already matches


def test_eval_format_spec_without_format_fails(runner, bibfile):
    result = runner.invoke(
        main, ["eval_format_spec", str(bibfile), "GoerzPRA2014"]
    )
    assert result.exit_code == 1
    assert "no auto-key format" in result.stderr


def test_eval_format_spec_filename(runner, bibfile):
    """With `--filename`, `eval_format_spec` evaluates the format as a
    file name without touching the filesystem. The file need not
    exist; only its extension feeds the format here."""
    before = bibfile.read_text(encoding="utf-8")
    result = _run(
        runner,
        "eval_format_spec",
        bibfile,
        "GoerzJPB2011",
        "%f{Cite Key}%u0%e",
        "--filename",
        "no-such-file.pdf",
    )
    assert result.output.strip() == "GoerzJPB2011.pdf"
    assert bibfile.read_text(encoding="utf-8") == before


def test_eval_format_spec_empty_filename(runner, bibfile):
    """An empty `--filename` still selects the file-name dialect."""
    result = _run(
        runner,
        "eval_format_spec",
        bibfile,
        "GoerzJPB2011",
        "%f{Cite Key}%u0",
        "--filename",
        "",
    )
    assert result.output.strip() == "GoerzJPB2011"


# -- mutating commands -------------------------------------------------- #


def test_rekey(runner, bibfile):
    result = _run(runner, "rekey", bibfile, "GoerzDiploma2010", "Goerz2010")
    assert result.output == ""  # explicit renames print nothing
    lib = _load(bibfile)
    assert "Goerz2010" in lib
    assert "GoerzDiploma2010" not in lib


def test_rekey_format_spec_option(runner, bibfile):
    """`rekey` without NEW_KEY generates the key from the
    `--format-spec` pattern and prints it."""
    result = _run(
        runner, "rekey", bibfile, "GoerzPRA2014", "--format-spec", "%a1%Y%u0"
    )
    assert result.output.strip() == "Goerz2014"
    lib = _load(bibfile)
    assert "Goerz2014" in lib
    assert "GoerzPRA2014" not in lib


def test_rekey_auto_from_config(runner, bibfile):
    """`rekey` without NEW_KEY falls back to the `[auto_key]` format
    from the `bibdeskparser.toml` next to the `.bib` file, including
    the `[initials]` mapping."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[auto_key]\nformat_spec = "%a1%c{journal}0%Y%u0"\n\n'
        '[initials.journal]\n"npj Quantum Inf" = "NPJQI"\n',
        encoding="utf-8",
    )
    # already matching keys are kept (idempotent):
    result = _run(runner, "rekey", bibfile, "GoerzNPJQI2017")
    assert result.output.strip() == "GoerzNPJQI2017"
    # a non-matching key is regenerated:
    _run(runner, "rekey", bibfile, "GoerzNPJQI2017", "xxx")
    result = _run(runner, "rekey", bibfile, "xxx")
    assert result.output.strip() == "GoerzNPJQI2017"


def test_rekey_auto_without_format_fails(runner, bibfile):
    result = runner.invoke(main, ["rekey", str(bibfile), "GoerzPRA2014"])
    assert result.exit_code == 1
    assert "no auto-key format" in result.stderr


def test_rekey_format_spec_with_new_key_fails(runner, bibfile):
    result = runner.invoke(
        main,
        [
            "rekey",
            str(bibfile),
            "GoerzPRA2014",
            "NewKey",
            "--format-spec",
            "%a1%Y%u0",
        ],
    )
    assert result.exit_code == 1
    assert "not both" in result.stderr


def test_rekey_format_spec_not_implemented_specifier(runner, bibfile):
    """`%i` in a `--format-spec` pattern is a clean error."""
    result = runner.invoke(
        main,
        ["rekey", str(bibfile), "GoerzPRA2014", "--format-spec", "%i{X}"],
    )
    assert result.exit_code == 1
    assert "%i" in result.stderr
    assert "Traceback" not in result.stderr


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


def test_add_file_auto_from_config(runner, bibfile, tmp_path):
    """With `file_automatically = true`, `add_file` moves the file
    and prints the stored path."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        "[auto_file]\n"
        'format_spec = "%f{Cite Key}%u0%e"\n'
        "file_automatically = true\n",
        encoding="utf-8",
    )
    (tmp_path / "extra.pdf").write_bytes(b"%PDF-1.4 fake")
    result = _run(runner, "add_file", bibfile, "GoerzDiploma2010", "extra.pdf")
    assert result.output.strip() == "GoerzDiploma2010.pdf"
    assert _load(bibfile)["GoerzDiploma2010"].files == ["GoerzDiploma2010.pdf"]
    assert (tmp_path / "GoerzDiploma2010.pdf").exists()
    assert not (tmp_path / "extra.pdf").exists()


def test_add_file_no_auto_file(runner, bibfile, tmp_path):
    """`--no-auto-file` forces a plain attach despite the config."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        "[auto_file]\n"
        'format_spec = "%f{Cite Key}%u0%e"\n'
        "file_automatically = true\n",
        encoding="utf-8",
    )
    (tmp_path / "extra.pdf").write_bytes(b"%PDF-1.4 fake")
    result = _run(
        runner,
        "add_file",
        bibfile,
        "GoerzDiploma2010",
        "extra.pdf",
        "--no-auto-file",
    )
    assert result.output == ""
    assert _load(bibfile)["GoerzDiploma2010"].files == ["extra.pdf"]
    assert (tmp_path / "extra.pdf").exists()


def test_add_file_no_auto_file_with_location_fails(runner, bibfile, tmp_path):
    (tmp_path / "extra.pdf").write_bytes(b"%PDF-1.4 fake")
    result = runner.invoke(
        main,
        [
            "add_file",
            str(bibfile),
            "GoerzDiploma2010",
            "extra.pdf",
            "--no-auto-file",
            "--location",
            "Papers",
        ],
    )
    assert result.exit_code == 2
    assert "--no-auto-file" in result.stderr


def test_add_file_location_option(runner, bibfile, tmp_path):
    """Explicit `--format-spec`/`--location` auto-file without any
    configuration."""
    (tmp_path / "extra.pdf").write_bytes(b"%PDF-1.4 fake")
    result = _run(
        runner,
        "add_file",
        bibfile,
        "GoerzDiploma2010",
        "extra.pdf",
        "--format-spec",
        "%f{Cite Key}%u0%e",
        "--location",
        "Papers",
    )
    assert result.output.strip() == "Papers/GoerzDiploma2010.pdf"
    assert _load(bibfile)["GoerzDiploma2010"].files == [
        "Papers/GoerzDiploma2010.pdf"
    ]
    assert (tmp_path / "Papers" / "GoerzDiploma2010.pdf").exists()
    assert not (tmp_path / "extra.pdf").exists()


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


def test_rename_file_auto_from_config(runner, bibfile, tmp_path):
    """`rename_file` without NEW auto-files per the `[auto_file]`
    table and prints the new library-relative path."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[auto_file]\nformat_spec = "%f{Cite Key}%u0%e"\n',
        encoding="utf-8",
    )
    result = _run(
        runner, "rename_file", bibfile, "GoerzJPB2011", "GoerzJPB11.pdf"
    )
    assert result.output.strip() == "GoerzJPB2011.pdf"
    assert _load(bibfile)["GoerzJPB2011"].files == ["GoerzJPB2011.pdf"]
    assert (tmp_path / "GoerzJPB2011.pdf").exists()
    assert not (tmp_path / "GoerzJPB11.pdf").exists()


def test_rename_file_options(runner, bibfile, tmp_path):
    """Explicit `--location`/`--format-spec` override the config."""
    result = _run(
        runner,
        "rename_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB11.pdf",
        "--format-spec",
        "%f{Cite Key}%u0%e",
        "--location",
        "Papers",
    )
    assert result.output.strip() == "Papers/GoerzJPB2011.pdf"
    assert _load(bibfile)["GoerzJPB2011"].files == ["Papers/GoerzJPB2011.pdf"]
    assert (tmp_path / "Papers" / "GoerzJPB2011.pdf").exists()


def test_rename_file_new_with_format_spec_fails(runner, bibfile):
    result = runner.invoke(
        main,
        [
            "rename_file",
            str(bibfile),
            "GoerzJPB2011",
            "GoerzJPB11.pdf",
            "new.pdf",
            "--format-spec",
            "%f{Cite Key}%u0%e",
        ],
    )
    assert result.exit_code == 1
    assert "not both" in result.stderr


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


def test_edit_stdin_noop_roundtrip(runner, bibfile):
    """Piping `export` output back through `edit --stdin` is a no-op."""
    before = dict(_load(bibfile)["GoerzJPB2011"])
    exported = _run(runner, "export", bibfile, "GoerzJPB2011").output
    result = runner.invoke(
        main,
        ["edit", str(bibfile), "GoerzJPB2011", "--stdin"],
        input=exported,
    )
    assert result.exit_code == 0, result.output + result.stderr
    assert dict(_load(bibfile)["GoerzJPB2011"]) == before


def test_edit_stdin_changes_field(runner, bibfile):
    """A field change piped through `edit --stdin` lands in the file."""
    exported = _run(runner, "export", bibfile, "GoerzJPB2011").output
    edited = exported.replace(
        "trapped neutral atoms", "confined neutral atoms"
    )
    assert edited != exported
    result = runner.invoke(
        main, ["edit", str(bibfile), "GoerzJPB2011", "--stdin"], input=edited
    )
    assert result.exit_code == 0, result.output + result.stderr
    title = _load(bibfile)["GoerzJPB2011"]["title"]
    assert "confined neutral atoms" in title
    assert "trapped" not in title


def test_edit_stdin_empty_input(runner, bibfile):
    """Empty stdin is rejected instead of silently doing nothing."""
    result = runner.invoke(
        main, ["edit", str(bibfile), "GoerzJPB2011", "--stdin"], input=""
    )
    assert result.exit_code == 2
    assert "standard input is empty" in result.stderr


def test_edit_stdin_editor_mutually_exclusive(runner, bibfile):
    result = runner.invoke(
        main,
        ["edit", str(bibfile), "GoerzJPB2011", "--stdin", "--editor", "vi"],
        input="x",
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stderr


def test_edit_requires_terminal_or_stdin(runner, bibfile):
    """Without a terminal, `edit` fails fast instead of blocking on
    `$EDITOR` (the `CliRunner` stdin is never a TTY)."""
    result = runner.invoke(main, ["edit", str(bibfile), "GoerzJPB2011"])
    assert result.exit_code == 2
    assert "stdin is not a terminal" in result.stderr
    assert "--stdin" in result.stderr


def test_edit_strings_requires_terminal_or_stdin(runner, bibfile):
    result = runner.invoke(main, ["edit_strings", str(bibfile)])
    assert result.exit_code == 2
    assert "stdin is not a terminal" in result.stderr
    assert "--stdin" in result.stderr


def test_edit_stdin_validation_failure(runner, bibfile):
    """Invalid edited text exits 1 with the validation problems; the
    file is left unchanged."""
    before = bibfile.read_text(encoding="utf-8")
    exported = _run(runner, "export", bibfile, "GoerzJPB2011").output
    edited = exported.replace("year = {2011}", "year = nosuchmacro")
    assert edited != exported
    result = runner.invoke(
        main, ["edit", str(bibfile), "GoerzJPB2011", "--stdin"], input=edited
    )
    assert result.exit_code == 1
    assert "Validation failed" in result.stderr
    assert "nosuchmacro" in result.stderr
    assert bibfile.read_text(encoding="utf-8") == before


def test_strings_bib(runner, bibfile):
    result = _run(runner, "strings", bibfile, "--bib")
    expected = [
        f"@string{{{name} = {{{value}}}}}"
        for name, value in sorted(_load(bibfile).strings.items())
    ]
    assert result.output.splitlines() == expected
    assert "@string{jpb = {J. Phys. B}}" in expected


def test_strings_bib_json_mutually_exclusive(runner, bibfile):
    result = runner.invoke(main, ["strings", str(bibfile), "--bib", "--json"])
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stderr


def test_edit_strings_stdin_noop_roundtrip(runner, bibfile):
    """Piping `strings --bib` back through `edit_strings --stdin` is a
    no-op."""
    before = dict(_load(bibfile).strings)
    baseline = _run(runner, "strings", bibfile, "--bib").output
    result = runner.invoke(
        main, ["edit_strings", str(bibfile), "--stdin"], input=baseline
    )
    assert result.exit_code == 0, result.output + result.stderr
    assert dict(_load(bibfile).strings) == before


def test_edit_strings_stdin_empty_roundtrip(runner, tmp_path):
    """For a library without `@string` macros, `strings --bib` prints
    nothing, and piping that empty text back through `edit_strings
    --stdin` is still an accepted no-op."""
    nostrings = tmp_path / "nostrings.bib"
    nostrings.write_text(
        "@article{Key2024,\n\tTitle = {A Title},\n\tYear = {2024}}\n",
        encoding="utf-8",
    )
    baseline = _run(runner, "strings", nostrings, "--bib").output
    assert baseline == ""
    result = runner.invoke(
        main, ["edit_strings", str(nostrings), "--stdin"], input=baseline
    )
    assert result.exit_code == 0, result.output + result.stderr
    lib = _load(nostrings)
    assert dict(lib.strings) == {}
    assert lib["Key2024"]["title"] == "A Title"


def test_edit_strings_stdin_empty_input_with_macros(runner, bibfile):
    """With existing `@string` macros, empty stdin is rejected instead
    of silently deleting them all."""
    before = bibfile.read_text(encoding="utf-8")
    assert dict(_load(bibfile).strings)
    result = runner.invoke(
        main, ["edit_strings", str(bibfile), "--stdin"], input=""
    )
    assert result.exit_code == 2
    assert "standard input is empty" in result.stderr
    assert bibfile.read_text(encoding="utf-8") == before


def test_edit_strings_stdin_changes_macro(runner, bibfile):
    baseline = _run(runner, "strings", bibfile, "--bib").output
    edited = baseline.replace("{J. Phys. B}", "{Journal of Physics B}")
    assert edited != baseline
    result = runner.invoke(
        main, ["edit_strings", str(bibfile), "--stdin"], input=edited
    )
    assert result.exit_code == 0, result.output + result.stderr
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
    assert "--no-auto-file" in result.output
    assert "--format-spec" in result.output
    assert "--location" in result.output
