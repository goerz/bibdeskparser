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


def test_help_examples(runner):
    """Every `--help` output ends with an "Examples:" block that
    mentions the command itself (so that the CLI is discoverable from
    `--help` alone, without a bibfile or external documentation)."""
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Examples:" in result.output
    for name in main.commands:
        result = runner.invoke(main, [name, "--help"])
        assert result.exit_code == 0, name
        assert "Examples:" in result.output, name
        assert f"bibdeskparser {name} " in result.output, name


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


def test_keys_filter_type(runner, bibfile):
    result = _run(runner, "keys", bibfile, "--type", "phdthesis")
    assert result.output.splitlines() == ["GoerzPhd2015"]
    result = _run(
        runner,
        "keys",
        bibfile,
        "--type",
        "PhdThesis",  # types are matched case-insensitively
        "--type",
        "mastersthesis",
    )
    assert result.output.splitlines() == ["GoerzDiploma2010", "GoerzPhd2015"]


def test_keys_filter_has_missing_empty(runner, bibfile):
    all_keys = set(_load(bibfile))
    result = _run(runner, "keys", bibfile, "--has", "abstract")
    has_abstract = result.output.splitlines()
    result = _run(runner, "keys", bibfile, "--missing", "abstract")
    missing_abstract = result.output.splitlines()
    result = _run(runner, "keys", bibfile, "--empty", "abstract")
    assert result.output == ""  # no empty fields in the pristine file
    assert set(has_abstract) | set(missing_abstract) == all_keys
    assert set(has_abstract) & set(missing_abstract) == set()
    assert "GoerzJPB2011" in has_abstract
    assert "GoerzPhd2015" in missing_abstract
    # A defined-but-empty field is neither "missing" nor "has":
    _run(runner, "set_field", bibfile, "GoerzJPB2011", "abstract", "")
    result = _run(runner, "keys", bibfile, "--empty", "abstract")
    assert result.output.splitlines() == ["GoerzJPB2011"]
    result = _run(runner, "keys", bibfile, "--has", "abstract")
    assert "GoerzJPB2011" not in result.output.splitlines()
    result = _run(runner, "keys", bibfile, "--missing", "abstract")
    assert "GoerzJPB2011" not in result.output.splitlines()


def test_keys_filter_combined(runner, bibfile):
    result = _run(
        runner,
        "keys",
        bibfile,
        "--type",
        "article",
        "--has",
        "eprint",
        "--missing",
        "note",
        "--json",
    )
    data = json.loads(result.output)
    assert "GoerzJPB2011" in data
    assert "GoerzSPIEO2021" not in data  # inproceedings
    lib = _load(bibfile)
    for key in data:
        entry = lib[key]
        assert entry.entry_type == "article"
        assert str(entry["eprint"]).strip()
        assert "note" not in entry


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


def test_show_field(runner, bibfile):
    """`--field` restricts the human-readable output to named fields."""
    result = _run(
        runner, "show", bibfile, "GoerzJPB2011", "--field", "doi,title"
    )
    assert result.output.startswith("GoerzJPB2011 (article)")
    assert "doi:" in result.output
    assert "title:" in result.output
    # other fields and the derived data are omitted
    assert "journal:" not in result.output
    assert "groups:" not in result.output


def test_show_field_json(runner, bibfile):
    """`--field --json` yields a flat map of just the named fields."""
    result = _run(
        runner,
        "show",
        bibfile,
        "GoerzJPB2011",
        "--field",
        "doi",
        "--field",
        "title",
        "--json",
    )
    data = json.loads(result.output)
    assert set(data) == {"GoerzJPB2011"}
    assert set(data["GoerzJPB2011"]) == {"doi", "title"}
    assert data["GoerzJPB2011"]["doi"] == "10.1088/0953-4075/44/15/154011"


def test_show_field_case_insensitive_and_missing_omitted(runner, bibfile):
    """Field names match case-insensitively; absent fields are dropped."""
    result = _run(
        runner,
        "show",
        bibfile,
        "GoerzJPB2011",
        "--field",
        "DOI,nosuchfield",
        "--json",
    )
    data = json.loads(result.output)
    # canonical (stored) name, and the undefined field simply omitted
    assert set(data["GoerzJPB2011"]) == {"doi"}


def test_show_unknown_key_aborts(runner, bibfile):
    """Without --skip-missing, an unknown key aborts with a clean
    message and no partial output."""
    result = runner.invoke(
        main, ["show", str(bibfile), "GoerzJPB2011", "NoSuchKey"]
    )
    assert result.exit_code == 1
    assert "Error: unknown citation key 'NoSuchKey'" in result.stderr
    # no entry was shown before the abort
    assert "GoerzJPB2011 (article)" not in result.output


def test_show_skip_missing(runner, bibfile):
    """`--skip-missing` reports misses on stderr and shows the rest."""
    result = _run(
        runner,
        "show",
        bibfile,
        "GoerzJPB2011",
        "NoSuchKey",
        "--skip-missing",
    )
    assert "GoerzJPB2011 (article)" in result.output
    # the miss is a warning, not shown as an entry heading
    assert "NoSuchKey (" not in result.output
    assert "Warning: unknown citation key 'NoSuchKey'" in result.stderr


def test_show_keys_from_stdin(runner, bibfile):
    """`--keys-from -` reads citation keys from standard input."""
    result = runner.invoke(
        main,
        ["show", str(bibfile), "--field", "title", "--keys-from", "-"],
        input="GoerzJPB2011\nGoerzNJP2014\n",
    )
    assert result.exit_code == 0, result.stderr
    assert "GoerzJPB2011 (article)" in result.output
    assert "GoerzNJP2014 (article)" in result.output


def test_show_keys_from_file(runner, bibfile, tmp_path):
    """`--keys-from FILE` reads keys from a file, combined with args."""
    keyfile = tmp_path / "keys.txt"
    keyfile.write_text("GoerzNJP2014\n\nGoerzPRA2014\n", encoding="utf-8")
    result = _run(
        runner,
        "show",
        bibfile,
        "GoerzJPB2011",
        "--field",
        "year",
        "--keys-from",
        keyfile,
    )
    assert "GoerzJPB2011 (article)" in result.output
    assert "GoerzNJP2014 (article)" in result.output
    assert "GoerzPRA2014 (article)" in result.output


def test_show_requires_keys(runner, bibfile):
    """`show` with neither KEY nor --keys-from is a usage error."""
    result = runner.invoke(main, ["show", str(bibfile)])
    assert result.exit_code == 2
    assert "no citation keys given" in result.stderr


def test_fields(runner, bibfile):
    result = _run(runner, "fields", bibfile, "GoerzJPB2011")
    lines = result.output.splitlines()
    assert lines == list(_load(bibfile)["GoerzJPB2011"])
    assert "author" in lines
    assert "journal" in lines
    assert "keywords" in lines
    assert "date-added" not in lines
    assert not any(name.startswith("bdsk-") for name in lines)


def test_fields_json(runner, bibfile):
    result = _run(runner, "fields", bibfile, "GoerzJPB2011", "--json")
    data = json.loads(result.output)
    assert data == list(_load(bibfile)["GoerzJPB2011"])


def test_get_field(runner, bibfile):
    result = _run(runner, "get_field", bibfile, "GoerzJPB2011", "eprint")
    assert result.output.splitlines() == ["1103.6050"]
    # field names are case-insensitive
    result = _run(runner, "get_field", bibfile, "GoerzJPB2011", "EPRINT")
    assert result.output.splitlines() == ["1103.6050"]
    # a macro reference prints as the bare macro name
    result = _run(runner, "get_field", bibfile, "GoerzJPB2011", "journal")
    assert result.output.splitlines() == ["jpb"]


def test_get_field_json(runner, bibfile):
    result = _run(
        runner, "get_field", bibfile, "GoerzJPB2011", "title", "--json"
    )
    data = json.loads(result.output)
    assert data == str(_load(bibfile)["GoerzJPB2011"]["title"])


def test_get_field_undefined(runner, bibfile):
    result = runner.invoke(
        main, ["get_field", str(bibfile), "GoerzJPB2011", "note"]
    )
    assert result.exit_code == 1
    assert "has no field 'note'" in result.stderr
    assert "Traceback" not in result.stderr


def test_author(runner, bibfile):
    result = _run(runner, "author", bibfile, "GoerzJPB2011")
    assert result.output.splitlines() == [
        "Goerz, Michael H",
        "Calarco, Tommaso",
        "Koch, Christiane P",
    ]


def test_author_json(runner, bibfile):
    result = _run(runner, "author", bibfile, "GoerzJPB2011", "--json")
    data = json.loads(result.output)
    assert data[0] == {
        "first": ["Michael", "H"],
        "von": [],
        "last": ["Goerz"],
        "jr": [],
    }
    assert [name["last"] for name in data] == [
        ["Goerz"],
        ["Calarco"],
        ["Koch"],
    ]


def test_editor(runner, bibfile):
    # no entry in refs.bib has an editor field
    result = _run(runner, "editor", bibfile, "GoerzJPB2011")
    assert result.output == ""
    result = _run(runner, "editor", bibfile, "GoerzJPB2011", "--json")
    assert json.loads(result.output) == []
    _run(
        runner,
        "set_field",
        bibfile,
        "GoerzJPB2011",
        "editor",
        "van der Berg, Anne and Smith, John",
    )
    result = _run(runner, "editor", bibfile, "GoerzJPB2011")
    assert result.output.splitlines() == [
        "van der Berg, Anne",
        "Smith, John",
    ]


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


def test_search_help_documents_match_levels(runner):
    """`search --help` describes each match level (fuzzy in
    particular), so an agent can choose one without external docs."""
    result = runner.invoke(main, ["search", "--help"])
    assert result.exit_code == 0
    for level in ("exact", "folded", "words", "fuzzy", "regex"):
        assert level in result.output
    # the fuzzy caveat is spelled out
    assert "verify" in result.output


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


def test_groups_of_entry(runner, bibfile):
    result = _run(runner, "groups", bibfile, "GoerzJPB2011")
    assert result.output.splitlines() == ["My Papers"]
    result = _run(runner, "groups", bibfile, "GoerzJPB2011", "--json")
    assert json.loads(result.output) == ["My Papers"]


def test_keywords(runner, bibfile):
    result = _run(runner, "keywords", bibfile)
    assert "optimal control: GoerzDiploma2010" in result.output


def test_keywords_json(runner, bibfile):
    result = _run(runner, "keywords", bibfile, "--json")
    data = json.loads(result.output)
    assert data["optimal control"] == ["GoerzDiploma2010"]


def test_keywords_of_entry(runner, bibfile):
    result = _run(runner, "keywords", bibfile, "GoerzDiploma2010")
    assert "optimal control" in result.output.splitlines()
    result = _run(runner, "keywords", bibfile, "GoerzDiploma2010", "--json")
    data = json.loads(result.output)
    assert data == list(_load(bibfile)["GoerzDiploma2010"].keywords)


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


def test_set_type(runner, bibfile):
    _run(runner, "set_type", bibfile, "GoerzJPB2011", "Misc")
    assert _load(bibfile)["GoerzJPB2011"].entry_type == "misc"


def test_set_type_invalid(runner, bibfile):
    result = runner.invoke(
        main, ["set_type", str(bibfile), "GoerzJPB2011", "bogus"]
    )
    assert result.exit_code == 1
    assert "invalid entry type: 'bogus'" in result.stderr


def test_set_field(runner, bibfile):
    _run(runner, "set_field", bibfile, "GoerzJPB2011", "note", "A note")
    entry = _load(bibfile)["GoerzJPB2011"]
    assert entry["note"] == "A note"
    assert isinstance(entry["note"], bibdeskparser.ValueString)
    # updating an existing field, with non-ASCII text
    _run(runner, "set_field", bibfile, "GoerzJPB2011", "note", "Universität")
    assert _load(bibfile)["GoerzJPB2011"]["note"] == "Universität"


def test_set_field_macro(runner, bibfile):
    # a plain VALUE that is a valid macro name becomes a macro reference
    _run(runner, "set_field", bibfile, "GoerzJPB2011", "journal", "pra")
    entry = _load(bibfile)["GoerzJPB2011"]
    assert entry["journal"] == "pra"
    assert isinstance(entry["journal"], bibdeskparser.MacroString)
    # --literal forces literal text
    _run(
        runner,
        "set_field",
        bibfile,
        "GoerzJPB2011",
        "journal",
        "pra",
        "--literal",
    )
    entry = _load(bibfile)["GoerzJPB2011"]
    assert isinstance(entry["journal"], bibdeskparser.ValueString)
    # --macro forces a macro reference, and validates the name
    _run(
        runner,
        "set_field",
        bibfile,
        "GoerzJPB2011",
        "journal",
        "pra",
        "--macro",
    )
    entry = _load(bibfile)["GoerzJPB2011"]
    assert isinstance(entry["journal"], bibdeskparser.MacroString)
    result = runner.invoke(
        main,
        [
            "set_field",
            str(bibfile),
            "GoerzJPB2011",
            "journal",
            "J. Phys. B",
            "--macro",
        ],
    )
    assert result.exit_code == 1
    assert "invalid BibDesk macro name" in result.stderr


def test_set_field_literal_and_macro_conflict(runner, bibfile):
    result = runner.invoke(
        main,
        [
            "set_field",
            str(bibfile),
            "GoerzJPB2011",
            "note",
            "x",
            "--literal",
            "--macro",
        ],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stderr


def test_set_field_inappropriate_warns(runner, bibfile):
    result = _run(
        runner, "set_field", bibfile, "GoerzJPB2011", "school", "Uni"
    )
    assert (
        "Warning: field 'school' is not appropriate for entry type "
        "'article'" in result.stderr
    )
    assert _load(bibfile)["GoerzJPB2011"]["school"] == "Uni"


def test_set_field_invalid_author(runner, bibfile):
    result = runner.invoke(
        main,
        ["set_field", str(bibfile), "GoerzJPB2011", "author", "A, B, C, D"],
    )
    assert result.exit_code == 1
    assert "invalid author field" in result.stderr


def test_set_field_protected(runner, bibfile):
    for fieldname in ("keywords", "date-added", "bdsk-file-1"):
        result = runner.invoke(
            main,
            ["set_field", str(bibfile), "GoerzJPB2011", fieldname, "x"],
        )
        assert result.exit_code == 1, fieldname
        assert "Traceback" not in result.stderr


def test_delete_field(runner, bibfile):
    _run(runner, "delete_field", bibfile, "GoerzJPB2011", "abstract")
    assert "abstract" not in _load(bibfile)["GoerzJPB2011"]


def test_delete_field_undefined(runner, bibfile):
    result = runner.invoke(
        main, ["delete_field", str(bibfile), "GoerzJPB2011", "note"]
    )
    assert result.exit_code == 1
    assert "has no field 'note'" in result.stderr


def test_delete_field_protected(runner, bibfile):
    result = runner.invoke(
        main, ["delete_field", str(bibfile), "GoerzJPB2011", "keywords"]
    )
    assert result.exit_code == 1
    assert "add_to_keyword" in result.stderr


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


def test_add_file_auto_file_forced(runner, bibfile, tmp_path):
    """`--auto-file` forces auto-filing despite `file_automatically =
    false` in the config."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        "[auto_file]\n"
        'format_spec = "%f{Cite Key}%u0%e"\n'
        "file_automatically = false\n",
        encoding="utf-8",
    )
    (tmp_path / "extra.pdf").write_bytes(b"%PDF-1.4 fake")
    result = _run(
        runner,
        "add_file",
        bibfile,
        "GoerzDiploma2010",
        "extra.pdf",
        "--auto-file",
    )
    assert result.output.strip() == "GoerzDiploma2010.pdf"
    assert _load(bibfile)["GoerzDiploma2010"].files == ["GoerzDiploma2010.pdf"]
    assert (tmp_path / "GoerzDiploma2010.pdf").exists()
    assert not (tmp_path / "extra.pdf").exists()


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
    assert "Error: unknown citation key 'NoSuchKey'" in result.stderr
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
    assert "Error: unknown static group 'No Such Group'" in result.stderr
    assert "Traceback" not in result.stderr


def test_add_to_group_unknown_key_message(runner, bibfile):
    """Adding an unknown citation key to a real group names the key."""
    result = runner.invoke(
        main, ["add_to_group", str(bibfile), "My Papers", "NoSuchKey"]
    )
    assert result.exit_code == 1
    assert "Error: unknown citation key 'NoSuchKey'" in result.stderr


def test_delete_group_unknown_message(runner, bibfile):
    result = runner.invoke(main, ["delete_group", str(bibfile), "Nope"])
    assert result.exit_code == 1
    assert "Error: unknown static group 'Nope'" in result.stderr


def test_delete_unknown_keys_message(runner, bibfile):
    """Several unknown keys are reported together."""
    result = runner.invoke(
        main, ["delete", str(bibfile), "NoSuchKey", "AlsoMissing"]
    )
    assert result.exit_code == 1
    assert "unknown citation keys:" in result.stderr
    assert "'NoSuchKey'" in result.stderr
    assert "'AlsoMissing'" in result.stderr
    # nothing was deleted
    assert "GoerzJPB2011" in _load(bibfile)


def test_delete_string_unknown_message(runner, bibfile):
    result = runner.invoke(
        main, ["delete_string", str(bibfile), "nosuchmacro"]
    )
    assert result.exit_code == 1
    assert "Error: unknown @string macro 'nosuchmacro'" in result.stderr


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


# -- import / add ------------------------------------------------------- #


IMPORT_SNIPPET = """\
@article{PhysRevLett.113.140401,
    Author = {Baumgratz, T. and Cramer, M. and Plenio, M. B.},
    Title = {Quantifying Coherence},
    Journal = {Phys. Rev. Lett.},
    Year = {2014},
    Doi = {10.1103/PhysRevLett.113.140401},
    Pages = {140401},
    Volume = {113},
}
"""


def test_import_from_file(runner, bibfile, tmp_path):
    snippet = tmp_path / "entries.bib"
    snippet.write_text(IMPORT_SNIPPET, encoding="utf-8")
    result = _run(runner, "import", bibfile, snippet)
    assert result.stdout == "BaumgratzPRL2014\n"
    assert "created new @string macro" in result.stderr
    lib = _load(bibfile)
    assert lib["BaumgratzPRL2014"]["journal"] == "prl"
    assert lib.strings["prl"] == "Phys. Rev. Lett."


def test_import_stdin(runner, bibfile):
    result = runner.invoke(
        main, ["import", str(bibfile), "--stdin"], input=IMPORT_SNIPPET
    )
    assert result.exit_code == 0, result.output + result.stderr
    assert result.stdout == "BaumgratzPRL2014\n"
    assert "BaumgratzPRL2014" in _load(bibfile)


def test_import_url(runner, bibfile, monkeypatch):
    urls = []

    def fetch_text(url):
        urls.append(url)
        return IMPORT_SNIPPET

    monkeypatch.setattr("bibdeskparser.fetch.fetch_text", fetch_text)
    result = _run(
        runner, "import", bibfile, "--url", "https://example.com/x.bib"
    )
    assert urls == ["https://example.com/x.bib"]
    assert result.stdout == "BaumgratzPRL2014\n"


def test_import_requires_exactly_one_source(runner, bibfile, tmp_path):
    result = runner.invoke(main, ["import", str(bibfile)])
    assert result.exit_code == 2
    assert "exactly one of FILE, --stdin, or --url" in result.stderr
    snippet = tmp_path / "entries.bib"
    snippet.write_text(IMPORT_SNIPPET, encoding="utf-8")
    result = runner.invoke(
        main,
        ["import", str(bibfile), str(snippet), "--stdin"],
        input=IMPORT_SNIPPET,
    )
    assert result.exit_code == 2
    assert "exactly one of FILE, --stdin, or --url" in result.stderr


def test_import_empty_stdin(runner, bibfile):
    result = runner.invoke(main, ["import", str(bibfile), "--stdin"], input="")
    assert result.exit_code == 2
    assert "standard input is empty" in result.stderr


def test_import_keep_keys(runner, bibfile):
    result = runner.invoke(
        main,
        ["import", str(bibfile), "--stdin", "--keep-keys"],
        input=IMPORT_SNIPPET,
    )
    assert result.exit_code == 0, result.output + result.stderr
    assert result.stdout == "PhysRevLett.113.140401\n"


def test_import_unique_suffix(runner, bibfile):
    """A key collision with the library gets a unique suffix."""
    text = IMPORT_SNIPPET.replace(
        "{Baumgratz, T. and Cramer, M. and Plenio, M. B.}",
        "{Goerz, Michael H.}",
    ).replace("{Phys. Rev. Lett.}", "{Phys. Rev. A}")
    result = runner.invoke(
        main, ["import", str(bibfile), "--stdin"], input=text
    )
    assert result.exit_code == 0, result.output + result.stderr
    assert result.stdout == "GoerzPRA2014a\n"  # GoerzPRA2014 exists


def test_import_validation_error(runner, bibfile):
    text = IMPORT_SNIPPET.replace(
        "{Baumgratz, T. and Cramer, M. and Plenio, M. B.}",
        "{Baumgratz, T., Jr, X, Y}",
    )
    before = bibfile.read_text(encoding="utf-8")
    result = runner.invoke(
        main, ["import", str(bibfile), "--stdin"], input=text
    )
    assert result.exit_code == 1
    assert "Error:" in result.stderr
    assert "invalid author field" in result.stderr
    assert bibfile.read_text(encoding="utf-8") == before


def test_import_duplicate_doi(runner, bibfile):
    text = IMPORT_SNIPPET.replace(
        "{10.1103/PhysRevLett.113.140401}", "{10.1103/PhysRevA.90.032329}"
    )
    result = runner.invoke(
        main, ["import", str(bibfile), "--stdin"], input=text
    )
    assert result.exit_code == 1
    assert "already in the library as entry 'GoerzPRA2014'" in result.stderr


def test_import_default_bibfile_gotcha(runner, bibfile, monkeypatch):
    """With a configured default_bib_file, a `.bib` FILE argument is
    still consumed as the library (the documented limitation): the
    command then fails for lack of an import source."""
    monkeypatch.chdir(bibfile.parent)
    Path("bibdeskparser.toml").write_text(
        f'default_bib_file = "{bibfile.name}"\n', encoding="utf-8"
    )
    snippet = bibfile.parent / "entries.bib"
    snippet.write_text(IMPORT_SNIPPET, encoding="utf-8")
    result = runner.invoke(main, ["import", "entries.bib"])
    assert result.exit_code == 2
    assert "exactly one of FILE, --stdin, or --url" in result.stderr


def test_add(runner, bibfile, monkeypatch):
    queries = []

    def fetch_bibtex(query):
        queries.append(query)
        return IMPORT_SNIPPET.replace("PhysRevLett.113.140401,", "Fetched,")

    monkeypatch.setattr("bibdeskparser.fetch.fetch_bibtex", fetch_bibtex)
    result = _run(runner, "add", bibfile, "10.1103/PhysRevLett.113.140401")
    assert queries == ["10.1103/PhysRevLett.113.140401"]
    assert result.stdout == "BaumgratzPRL2014\n"
    lib = _load(bibfile)
    assert lib["BaumgratzPRL2014"]["journal"] == "prl"


def test_add_joins_query_args(runner, bibfile, monkeypatch):
    queries = []

    def fetch_bibtex(query):
        queries.append(query)
        return IMPORT_SNIPPET

    monkeypatch.setattr("bibdeskparser.fetch.fetch_bibtex", fetch_bibtex)
    _run(runner, "add", bibfile, "quantifying", "coherence")
    assert queries == ["quantifying coherence"]


def test_add_dry_run(runner, bibfile, monkeypatch):
    monkeypatch.setattr(
        "bibdeskparser.fetch.fetch_bibtex", lambda query: IMPORT_SNIPPET
    )
    before = bibfile.read_text(encoding="utf-8")
    result = _run(runner, "add", bibfile, "--dry-run", "10.1103/xyz")
    assert "@article{BaumgratzPRL2014," in result.stdout
    assert "@string{prl = {Phys. Rev. Lett.}}" in result.stdout
    assert bibfile.read_text(encoding="utf-8") == before


def test_add_fetch_failure(runner, bibfile, monkeypatch):
    def fetch_bibtex(query):
        raise ValueError(f"could not fetch bibliographic data for {query!r}")

    monkeypatch.setattr("bibdeskparser.fetch.fetch_bibtex", fetch_bibtex)
    result = runner.invoke(main, ["add", str(bibfile), "10.1103/xyz"])
    assert result.exit_code == 1
    assert "Error: could not fetch bibliographic data" in result.stderr
