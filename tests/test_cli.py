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
from bibdeskparser.groups import render_static_groups

REFS_DIR = Path(__file__).parent / "Refs"
FAIL_CHECKS_DIR = Path(__file__).parent / "test_cli_fail_checks"


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


@pytest.fixture(name="dupfile")
def fixture_dupfile(tmp_path):
    """A copy of `with_duplicates.bib` in `tmp_path`, with the linked
    PDFs: a variant of `refs.bib` with a deliberate duplicate citation
    key."""
    for pdf in REFS_DIR.glob("*.pdf"):
        shutil.copy(pdf, tmp_path)
    return Path(shutil.copy(REFS_DIR / "with_duplicates.bib", tmp_path))


@pytest.fixture(name="checkfile")
def fixture_checkfile(tmp_path):
    """A copy of `test_cli_fail_checks/problems.bib` in `tmp_path`: a
    library that fails every audit of the `check` command except the parse
    audit (see the `brokenfile` fixture), with one entry per problem,
    named after it (`MissingDoi2026`, `EmptyDoi2026` -- failing both
    the doi audit and the empty-fields audit, since its `doi = {}`
    would be deleted by BibDesk on save -- `LiteralJournal2026`,
    `UndefinedMacro2026`, `BadNames2026`, `Duplicate2026`), plus an
    unused `@string` macro (`unusedjrnl`) and the *passing* entry
    `Preprint2026` (a preprint-only entry, exempt from the doi and
    journal audits)."""
    return Path(shutil.copy(FAIL_CHECKS_DIR / "problems.bib", tmp_path))


@pytest.fixture(name="brokenfile")
def fixture_brokenfile(tmp_path):
    """A copy of `test_cli_fail_checks/broken_block.bib` in
    `tmp_path`: a library with one clean entry (`Good2026`) and one
    block that fails to parse (`Broken2026`, with a duplicate `title`
    field)."""
    return Path(shutil.copy(FAIL_CHECKS_DIR / "broken_block.bib", tmp_path))


@pytest.fixture(name="runner")
def fixture_runner():
    try:
        # click < 8.2 mixes stderr into stdout unless told otherwise
        return CliRunner(mix_stderr=False)
    except TypeError:  # click >= 8.2 always captures stderr separately
        return CliRunner()


def _load(bibfile):
    """Load `bibfile` as a `Library`, suppressing load-time warnings
    (e.g. the duplicate-key warning for `with_duplicates.bib`)."""
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
    assert result.output.splitlines() == ["GoerzPhd2015", "BrionPhd2004"]
    result = _run(
        runner,
        "keys",
        bibfile,
        "--type",
        "PhdThesis",  # types are matched case-insensitively
        "--type",
        "mastersthesis",
    )
    assert result.output.splitlines() == [
        "GoerzDiploma2010",
        "GoerzPhd2015",
        "BrionPhd2004",
    ]


def test_keys_filter_has_missing(runner, bibfile):
    all_keys = set(_load(bibfile))
    result = _run(runner, "keys", bibfile, "--has", "abstract")
    has_abstract = result.output.splitlines()
    result = _run(runner, "keys", bibfile, "--missing", "abstract")
    missing_abstract = result.output.splitlines()
    assert set(has_abstract) | set(missing_abstract) == all_keys
    assert set(has_abstract) & set(missing_abstract) == set()
    assert "GoerzJPB2011" in has_abstract
    assert "GoerzPhd2015" in missing_abstract
    # A defined-but-empty field counts as missing (the CLI refuses to
    # write one, so create it via the Python API):
    lib = _load(bibfile)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lib["GoerzJPB2011"]["abstract"] = ""
    lib.save()
    result = _run(runner, "keys", bibfile, "--has", "abstract")
    assert "GoerzJPB2011" not in result.output.splitlines()
    result = _run(runner, "keys", bibfile, "--missing", "abstract")
    assert "GoerzJPB2011" in result.output.splitlines()


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
    assert "KochJPCM2016" in data
    assert "GoerzJPB2011" not in data  # has a note field
    assert "GoerzSPIEO2021" not in data  # inproceedings
    lib = _load(bibfile)
    for key in data:
        entry = lib[key]
        assert entry.entry_type == "article"
        assert str(entry["eprint"]).strip()
        assert "note" not in entry


def test_keys_filter_group(runner, bibfile):
    result = _run(runner, "keys", bibfile, "--group", "Diploma")
    assert result.output.splitlines() == [
        "Tannor2007",
        "NielsenChuangCh10QEC",
        "Evans1983",
        "LapertPRA09",
    ]
    result = _run(
        runner, "keys", bibfile, "--group", "Diploma", "--type", "book"
    )
    assert result.output.splitlines() == ["Tannor2007"]
    result = _run(
        runner,
        "keys",
        bibfile,
        "--group",
        "Diploma",
        "--group",
        "My Papers",
    )
    assert result.output == ""


def test_keys_filter_not_group(runner, bibfile):
    all_keys = set(_load(bibfile))
    result = _run(runner, "keys", bibfile, "--not-group", "Diploma")
    not_diploma = result.output.splitlines()
    result = _run(runner, "keys", bibfile, "--group", "Diploma")
    diploma = result.output.splitlines()
    assert set(not_diploma) == all_keys - set(diploma)


def test_keys_filter_group_unknown(runner, bibfile):
    """An unknown group name is an error, not an empty result."""
    result = runner.invoke(main, ["keys", str(bibfile), "--group", "diploma"])
    assert result.exit_code != 0
    assert "unknown static group 'diploma'" in result.stderr
    result = runner.invoke(
        main, ["keys", str(bibfile), "--not-group", "No Such Group"]
    )
    assert result.exit_code != 0
    assert "unknown static group 'No Such Group'" in result.stderr


def test_keys_filter_by_attachment(runner, bibfile):
    all_keys = set(_load(bibfile).keys())
    with_files = _run(
        runner, "keys", bibfile, "--with-files"
    ).output.splitlines()
    without_files = _run(
        runner, "keys", bibfile, "--without-files"
    ).output.splitlines()

    assert len(with_files) == 30
    assert len(without_files) == 31
    assert set(with_files) | set(without_files) == all_keys  # exhaustive
    assert set(with_files) & set(without_files) == set()  # disjoint
    assert "BrifNJP2010" in with_files
    assert "Shapiro2012" in without_files

    # no flag = no filtering
    assert len(_run(runner, "keys", bibfile).output.splitlines()) == 61

    # composes with the other filters
    articles_no_pdf = _run(
        runner, "keys", bibfile, "--type", "article", "--without-files"
    ).output.splitlines()
    lib = _load(bibfile)
    assert articles_no_pdf  # non-empty, else the assertions below are vacuous
    for key in articles_no_pdf:
        assert lib[key].entry_type == "article"
        assert not lib[key].files


def test_show(runner, bibfile):
    result = _run(runner, "show", bibfile, "GoerzJPB2011")
    assert result.output.startswith("GoerzJPB2011 (article)")
    assert "journal:" in result.output
    assert "groups:" in result.output
    assert "My Papers" in result.output
    assert "GoerzJPB2011.pdf" in result.output


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
    assert entry["fields"]["journal"] == "J. Phys. B"
    assert entry["groups"] == ["My Papers"]
    assert entry["files"] == ["GoerzJPB2011.pdf"]
    assert isinstance(entry["urls"], list)
    lib = _load(bibfile)
    assert entry["date_added"] == lib["GoerzJPB2011"].date_added.isoformat()


def test_show_no_expand_strings(runner, bibfile):
    """With --no-expand-strings, a macro reference prints as its bare
    name, and in JSON *every* field value uniformly becomes a
    {"macro": ..., "value": ...} object."""
    result = _run(
        runner, "show", bibfile, "GoerzJPB2011", "--no-expand-strings"
    )
    assert ["journal:", "jpb"] in [
        line.split() for line in result.output.splitlines()
    ]
    result = _run(
        runner,
        "show",
        bibfile,
        "GoerzJPB2011",
        "--no-expand-strings",
        "--json",
    )
    fields = json.loads(result.output)["GoerzJPB2011"]["fields"]
    assert fields["journal"] == {"macro": "jpb", "value": "J. Phys. B"}
    for value in fields.values():
        assert set(value) == {"macro", "value"}
    assert fields["title"]["macro"] is None
    assert isinstance(fields["title"]["value"], str)


def test_show_no_unicode(runner, bibfile):
    """With --no-unicode, field values are TeX-encoded."""
    result = _run(
        runner,
        "show",
        bibfile,
        "GoerzDiploma2010",
        "--field",
        "school",
        "--no-unicode",
    )
    assert 'Universit{\\"a}t' in result.output


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
    # a macro reference prints as the macro's value ...
    result = _run(runner, "get_field", bibfile, "GoerzJPB2011", "journal")
    assert result.output.splitlines() == ["J. Phys. B"]
    # ... unless --no-expand-strings asks for the bare macro name
    result = _run(
        runner,
        "get_field",
        bibfile,
        "GoerzJPB2011",
        "journal",
        "--no-expand-strings",
    )
    assert result.output.splitlines() == ["jpb"]


def test_get_field_no_unicode(runner, bibfile):
    """With --no-unicode, the value is TeX-encoded."""
    result = _run(
        runner,
        "get_field",
        bibfile,
        "GoerzDiploma2010",
        "school",
        "--no-unicode",
    )
    assert result.output.rstrip() == 'Freie Universit{\\"a}t Berlin'


def test_get_field_json(runner, bibfile):
    result = _run(
        runner, "get_field", bibfile, "GoerzJPB2011", "title", "--json"
    )
    data = json.loads(result.output)
    assert data == str(_load(bibfile)["GoerzJPB2011"]["title"])
    # with --no-expand-strings, the value is uniformly a JSON object
    result = _run(
        runner,
        "get_field",
        bibfile,
        "GoerzJPB2011",
        "journal",
        "--no-expand-strings",
        "--json",
    )
    data = json.loads(result.output)
    assert data == {"macro": "jpb", "value": "J. Phys. B"}
    # ... for a literal field as well, with a null "macro"
    result = _run(
        runner,
        "get_field",
        bibfile,
        "GoerzJPB2011",
        "year",
        "--no-expand-strings",
        "--json",
    )
    data = json.loads(result.output)
    assert data == {"macro": None, "value": "2011"}


def test_get_field_undefined(runner, bibfile):
    result = runner.invoke(
        main, ["get_field", str(bibfile), "GoerzJPB2011", "number"]
    )
    assert result.exit_code == 1
    assert "has no field 'number'" in result.stderr
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
    # GoerzJPB2011 has no editor field
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


def test_files_single_key(runner, bibfile):
    # one KEY -> a {key: [paths]} map (absolute by default)
    expected = bibfile.resolve().parent / "GoerzJPB2011.pdf"
    assert expected.is_absolute() and expected.is_file()
    result = _run(runner, "files", bibfile, "GoerzJPB2011", "--json")
    assert json.loads(result.output) == {"GoerzJPB2011": [str(expected)]}
    result = _run(runner, "files", bibfile, "GoerzJPB2011")
    assert result.output.splitlines() == [f"GoerzJPB2011: {expected}"]


def test_files_single_key_relative(runner, bibfile):
    result = _run(
        runner, "files", bibfile, "GoerzJPB2011", "--relative", "--json"
    )
    assert json.loads(result.output) == {"GoerzJPB2011": ["GoerzJPB2011.pdf"]}


def test_files_empty(runner, bibfile):
    # SolaAAMOP2018 has no file attachments -> present, mapped to []
    result = _run(runner, "files", bibfile, "SolaAAMOP2018", "--json")
    assert json.loads(result.output) == {"SolaAAMOP2018": []}
    result = _run(runner, "files", bibfile, "SolaAAMOP2018")
    assert result.output.splitlines() == ["SolaAAMOP2018: "]


def test_files_unknown_key(runner, bibfile):
    result = runner.invoke(main, ["files", str(bibfile), "NoSuchKey"])
    assert result.exit_code == 1
    assert "Error: unknown citation key 'NoSuchKey'" in result.stderr


def test_files_whole_library_json(runner, bibfile):
    data = json.loads(_run(runner, "files", bibfile, "--json").output)
    assert len(data) == 30  # only entries with files
    assert "BrifNJP2010" in data
    assert "Shapiro2012" not in data  # no attachment -> absent
    for _, paths in data.items():
        assert isinstance(paths, list) and paths
        assert all(p.endswith(".pdf") for p in paths)


def test_files_whole_library_relative(runner, bibfile):
    data = json.loads(
        _run(runner, "files", bibfile, "--relative", "--json").output
    )
    assert data["GoerzPRA2014"] == ["GoerzPRA2014.pdf"]  # stored path


def test_files_whole_library_absolute_default(runner, bibfile):
    data = json.loads(_run(runner, "files", bibfile, "--json").output)
    assert all(Path(p).is_absolute() for paths in data.values() for p in paths)


def test_files_flat(runner, bibfile):
    # --flat -> a bare list; a single key keeps that entry's own order
    result = _run(
        runner,
        "files",
        bibfile,
        "GoerzPRA2014",
        "--relative",
        "--flat",
        "--json",
    )
    assert json.loads(result.output) == ["GoerzPRA2014.pdf"]  # list, not map
    # whole library --flat -> every referenced file, de-duplicated
    flat = json.loads(
        _run(runner, "files", bibfile, "--relative", "--flat", "--json").output
    )
    assert isinstance(flat, list)
    assert len(flat) == 30
    assert "GoerzPRA2014.pdf" in flat
    assert len(set(flat)) == len(flat)


def test_files_multiple_keys(runner, bibfile):
    # several keys -> a map, requested entries always present (empty if none)
    data = json.loads(
        _run(
            runner,
            "files",
            bibfile,
            "GoerzPRA2014",
            "Shapiro2012",
            "--relative",
            "--json",
        ).output
    )
    assert data == {
        "GoerzPRA2014": ["GoerzPRA2014.pdf"],
        "Shapiro2012": [],
    }


def test_files_multiple_keys_text(runner, bibfile):
    # the text form of the map mirrors `groups`/`keywords`
    result = _run(
        runner,
        "files",
        bibfile,
        "GoerzPRA2014",
        "Shapiro2012",
        "--relative",
    )
    assert result.output.splitlines() == [
        "GoerzPRA2014: GoerzPRA2014.pdf",
        "Shapiro2012: ",
    ]


def test_files_multiple_keys_unknown(runner, bibfile):
    result = runner.invoke(
        main, ["files", str(bibfile), "GoerzPRA2014", "NoSuchKey"]
    )
    assert result.exit_code == 1
    assert "unknown citation key 'NoSuchKey'" in result.stderr


def test_reconcile_orphans_and_gaps(runner, bibfile):
    # entries missing a PDF
    no_pdf = _run(runner, "keys", bibfile, "--without-files").output.split()
    assert "Shapiro2012" in no_pdf

    # every referenced file, as a set, to diff against files on disk
    referenced = set(
        json.loads(
            _run(
                runner, "files", bibfile, "--relative", "--flat", "--json"
            ).output
        )
    )
    assert "GoerzPRA2014.pdf" in referenced


def test_urls_single_key(runner, bibfile):
    # one KEY -> a {key: [urls]} map
    result = _run(runner, "urls", bibfile, "TomzaPRA2012", "--json")
    assert json.loads(result.output) == {
        "TomzaPRA2012": [
            "http://link.aps.org/doi/10.1103/PhysRevA.86.043424",
            "http://dx.doi.org/10.1103/PhysRevA.86.043424",
        ]
    }
    result = _run(runner, "urls", bibfile, "KochJPCM2016")
    assert result.output.splitlines() == [
        "KochJPCM2016: http://dx.doi.org/10.1088/0953-8984/28/21/213001"
    ]


def test_urls_flat(runner, bibfile):
    result = _run(runner, "urls", bibfile, "TomzaPRA2012", "--flat", "--json")
    assert json.loads(result.output) == [
        "http://link.aps.org/doi/10.1103/PhysRevA.86.043424",
        "http://dx.doi.org/10.1103/PhysRevA.86.043424",
    ]


def test_urls_empty(runner, bibfile):
    # MorzhinRMS2019 has a file attachment but no linked URLs -> mapped to []
    result = _run(runner, "urls", bibfile, "MorzhinRMS2019", "--json")
    assert json.loads(result.output) == {"MorzhinRMS2019": []}
    result = _run(runner, "urls", bibfile, "MorzhinRMS2019")
    assert result.output.splitlines() == ["MorzhinRMS2019: "]


def test_urls_whole_library(runner, bibfile):
    data = json.loads(_run(runner, "urls", bibfile, "--json").output)
    assert isinstance(data, dict)
    assert "TomzaPRA2012" in data  # has URLs
    assert "MorzhinRMS2019" not in data  # no URLs -> absent
    assert all(isinstance(v, list) and v for v in data.values())


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
        r"^10\.21468/",
        "--field",
        "doi",
        "--match",
        "regex",
    )
    assert result.output.splitlines() == ["GoerzSPP2019"]
    result = _run(
        runner,
        "search",
        bibfile,
        "rms",
        "--field",
        "journal",
        "--field",
        "key",
        "--match",
        "exact",
    )
    assert result.output.splitlines() == ["MorzhinRMS2019"]


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
    # no KEY -> forward {key: [groups]} map (entries in >=1 group)
    data = json.loads(_run(runner, "groups", bibfile, "--json").output)
    assert isinstance(data, dict)
    assert data["GoerzJPB2011"] == ["My Papers"]
    lib = _load(bibfile)
    for key in data:  # only entries that are in some group appear
        assert lib[key].groups
    result = _run(runner, "groups", bibfile)
    assert "GoerzJPB2011: My Papers" in result.output.splitlines()


def test_groups_of_entry(runner, bibfile):
    # one KEY -> a {key: [groups]} map (was a bare list before)
    result = _run(runner, "groups", bibfile, "GoerzJPB2011", "--json")
    assert json.loads(result.output) == {"GoerzJPB2011": ["My Papers"]}
    result = _run(runner, "groups", bibfile, "GoerzJPB2011")
    assert result.output.splitlines() == ["GoerzJPB2011: My Papers"]


def test_groups_flat(runner, bibfile):
    data = json.loads(
        _run(runner, "groups", bibfile, "--flat", "--json").output
    )
    assert isinstance(data, list)
    assert set(data) == {"My Papers", "Diploma"}


def test_groups_index(runner, bibfile):
    # --index -> the inverse {group: [member keys]} map (Library.groups)
    data = json.loads(
        _run(runner, "groups", bibfile, "--index", "--json").output
    )
    expected = {
        name: list(keys) for name, keys in _load(bibfile).groups.items()
    }
    assert data == expected
    assert "GoerzJPB2011" in data["My Papers"]
    result = _run(runner, "groups", bibfile, "--index")
    assert "My Papers: GoerzDiploma2010, GoerzJPB2011" in result.output


def test_groups_index_rejects_keys_and_flat(runner, bibfile):
    result = runner.invoke(
        main, ["groups", str(bibfile), "--index", "GoerzJPB2011"]
    )
    assert result.exit_code == 2
    assert "--index cannot be combined" in result.stderr
    result = runner.invoke(main, ["groups", str(bibfile), "--index", "--flat"])
    assert result.exit_code == 2


def test_keywords(runner, bibfile):
    # no KEY -> forward {key: [keywords]} map (entries with >=1 keyword)
    data = json.loads(_run(runner, "keywords", bibfile, "--json").output)
    assert isinstance(data, dict)
    assert "OCT" in data["LapertPRA09"]
    result = _run(runner, "keywords", bibfile)
    assert any(
        line.startswith("LapertPRA09: ") for line in result.output.splitlines()
    )


def test_keywords_of_entry(runner, bibfile):
    # one KEY -> a {key: [keywords]} map
    result = _run(runner, "keywords", bibfile, "GoerzDiploma2010", "--json")
    data = json.loads(result.output)
    assert data == {
        "GoerzDiploma2010": list(_load(bibfile)["GoerzDiploma2010"].keywords)
    }
    assert "Quantum Gates" in data["GoerzDiploma2010"]


def test_keywords_flat(runner, bibfile):
    result = _run(
        runner, "keywords", bibfile, "LapertPRA09", "--flat", "--json"
    )
    assert json.loads(result.output) == ["Filtering", "OCT"]


def test_keywords_index(runner, bibfile):
    data = json.loads(
        _run(runner, "keywords", bibfile, "--index", "--json").output
    )
    assert data["Filtering"] == ["LapertPRA09"]
    result = _run(runner, "keywords", bibfile, "--index")
    assert "Filtering: LapertPRA09" in result.output


def test_keywords_index_rejects_keys_and_flat(runner, bibfile):
    result = runner.invoke(
        main, ["keywords", str(bibfile), "--index", "LapertPRA09"]
    )
    assert result.exit_code == 2
    result = runner.invoke(
        main, ["keywords", str(bibfile), "--index", "--flat"]
    )
    assert result.exit_code == 2


def test_strings(runner, bibfile):
    result = _run(runner, "strings", bibfile)
    assert "jpb = J. Phys. B" in result.output


def test_strings_json(runner, bibfile):
    result = _run(runner, "strings", bibfile, "--json")
    data = json.loads(result.output)
    assert data == dict(_load(bibfile).strings)
    assert data["jpb"] == "J. Phys. B"


def test_duplicate_keys(runner, dupfile):
    result = _run(runner, "duplicate_keys", dupfile)
    assert result.output.splitlines() == ["GoerzSPP2019"]


def test_duplicate_keys_json(runner, dupfile):
    result = _run(runner, "duplicate_keys", dupfile, "--json")
    assert json.loads(result.output) == ["GoerzSPP2019"]


def test_duplicate_keys_none(runner, bibfile):
    result = _run(runner, "duplicate_keys", bibfile)
    assert result.output == ""


def test_check_pass(runner, bibfile):
    n = len(_load(bibfile))
    result = _run(runner, "check", bibfile)
    assert result.output == f"PASS ({n} entries checked)\n"


def test_check_pass_json(runner, bibfile):
    n = len(_load(bibfile))
    result = _run(runner, "check", bibfile, "--json")
    data = json.loads(result.output)
    assert data == {"passed": True, "entries_checked": n, "problems": []}


def test_check_problems(runner, checkfile):
    result = runner.invoke(main, ["check", str(checkfile)])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[0] == "Duplicate2026: duplicate citation key"
    assert lines[1] == "MissingDoi2026: missing doi"
    assert lines[2] == "EmptyDoi2026: missing doi"
    assert lines[3] == (
        "EmptyDoi2026: empty field 'doi' (BibDesk deletes empty "
        "fields on save)"
    )
    assert lines[4] == (
        "LiteralJournal2026: journal is the literal string "
        "'Some Journal', not an @string macro reference"
    )
    assert lines[5] == (
        "UndefinedMacro2026: journal references undefined @string "
        "macro 'nosuchjournal'"
    )
    assert lines[6].startswith(
        "BadNames2026: author does not parse as names: "
    )
    assert "Too many commas" in lines[6]
    assert lines[7] == "unused @string macro 'unusedjrnl'"
    assert lines[8] == "FAIL (8 problems, 7 entries checked)"
    assert len(lines) == 9


def test_check_problems_json(runner, checkfile):
    result = runner.invoke(main, ["check", str(checkfile), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["passed"] is False
    assert data["entries_checked"] == 7
    assert [(p["check"], p["key"]) for p in data["problems"]] == [
        ("duplicate_keys", "Duplicate2026"),
        ("doi", "MissingDoi2026"),
        ("doi", "EmptyDoi2026"),
        ("empty_fields", "EmptyDoi2026"),
        ("journal", "LiteralJournal2026"),
        ("journal", "UndefinedMacro2026"),
        ("names", "BadNames2026"),
        ("unused_strings", None),
    ]
    assert all("message" in p for p in data["problems"])


def test_check_per_key(runner, checkfile):
    result = runner.invoke(main, ["check", str(checkfile), "MissingDoi2026"])
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "MissingDoi2026: missing doi",
        "FAIL (1 problem, 1 entry checked)",
    ]
    result = runner.invoke(
        main,
        ["check", str(checkfile), "LiteralJournal2026", "MissingDoi2026"],
    )
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "LiteralJournal2026: journal is the literal string "
        "'Some Journal', not an @string macro reference",
        "MissingDoi2026: missing doi",
        "FAIL (2 problems, 2 entries checked)",
    ]


def test_check_per_key_passing_entries(runner, checkfile):
    # Preprint2026 is exempt from the doi and journal audits as a
    # preprint-only entry, and the unused-macros audit (which the
    # never-referenced 'unusedjrnl' macro would fail) is skipped in
    # per-key mode.
    result = _run(runner, "check", checkfile, "Preprint2026")
    assert result.output == "PASS (1 entry checked)\n"


def test_check_per_key_empty_doi(runner, checkfile):
    # A defined-but-empty doi counts as missing, and the empty field
    # itself is doomed data (BibDesk deletes it on save).
    result = runner.invoke(main, ["check", str(checkfile), "EmptyDoi2026"])
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "EmptyDoi2026: missing doi",
        "EmptyDoi2026: empty field 'doi' (BibDesk deletes empty "
        "fields on save)",
        "FAIL (2 problems, 1 entry checked)",
    ]


def _add_static_group(bibfile, name, keys):
    """Append a `BibDesk Static Groups` comment with one group to
    `bibfile` (bypassing `save()`, which would refuse to write the
    deliberately broken check fixtures)."""
    comment = render_static_groups({name: tuple(keys)})
    with open(bibfile, "a", encoding="utf-8") as handle:
        handle.write("\n@comment{" + comment + "}\n")


def test_check_known_missing_suppresses_doi(runner, checkfile):
    """Membership in the known-missing group configured for `doi`
    passes the doi audit; without configuration, the same membership
    means nothing."""
    (checkfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\ndoi = "No DOI"\n', encoding="utf-8"
    )
    _add_static_group(checkfile, "No DOI", ["MissingDoi2026"])
    result = runner.invoke(main, ["check", str(checkfile), "MissingDoi2026"])
    assert result.exit_code == 0
    assert result.output == "PASS (1 entry checked)\n"
    (checkfile.parent / "bibdeskparser.toml").unlink()
    result = runner.invoke(main, ["check", str(checkfile), "MissingDoi2026"])
    assert result.exit_code == 1
    assert "MissingDoi2026: missing doi" in result.output


def test_check_known_missing_arbitrary_field(runner, checkfile):
    """A known-missing group may be declared for any field; the
    stale-marker audit is the (only) behavior it gets. Nothing ever
    marks such a group automatically, but a contradiction is
    flagged."""
    (checkfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\nauthor = "No Author"\n', encoding="utf-8"
    )
    _add_static_group(checkfile, "No Author", ["Preprint2026"])
    result = runner.invoke(main, ["check", str(checkfile), "Preprint2026"])
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "Preprint2026: in group 'No Author' (known-missing author) "
        "but has a non-empty author",
        "FAIL (1 problem, 1 entry checked)",
    ]


def test_check_known_missing_contradiction(runner, checkfile):
    """An entry in a known-missing group for a field it actually has
    is flagged (e.g. after a manual edit in BibDesk)."""
    (checkfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\ndoi = "No DOI"\n', encoding="utf-8"
    )
    _add_static_group(checkfile, "No DOI", ["LiteralJournal2026"])
    result = runner.invoke(
        main, ["check", str(checkfile), "LiteralJournal2026"]
    )
    assert result.exit_code == 1
    assert (
        "LiteralJournal2026: in group 'No DOI' (known-missing doi) "
        "but has a non-empty doi" in result.output
    )


def test_check_duplicate_key(runner, dupfile):
    n = len(_load(dupfile))
    result = runner.invoke(main, ["check", str(dupfile)])
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "GoerzSPP2019: duplicate citation key",
        f"FAIL (1 problem, {n} entries checked)",
    ]


def test_check_duplicate_key_per_key(runner, dupfile):
    result = runner.invoke(main, ["check", str(dupfile), "GoerzSPP2019"])
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "GoerzSPP2019: duplicate citation key",
        "FAIL (1 problem, 1 entry checked)",
    ]
    result = _run(runner, "check", dupfile, "GoerzJPB2011")
    assert result.output == "PASS (1 entry checked)\n"


def test_check_parse_problem(runner, brokenfile):
    result = runner.invoke(main, ["check", str(brokenfile)])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert len(lines) == 2
    assert "could not be parsed" in lines[0]
    assert "Duplicate field" in lines[0]
    assert lines[1] == "FAIL (1 problem, 1 entry checked)"
    # A key filter never silences the parse audit, and the raw load
    # warning is not additionally shown.
    result = runner.invoke(main, ["check", str(brokenfile), "Good2026"])
    assert result.exit_code == 1
    assert "could not be parsed" in result.output
    assert result.stderr == ""


def test_check_unknown_key(runner, bibfile):
    result = runner.invoke(main, ["check", str(bibfile), "NoSuchKey"])
    assert result.exit_code == 1
    assert "unknown citation key 'NoSuchKey'" in result.stderr


# A first name that splits cleanly but cannot be initialized: the
# quoted nickname "`Eunice'" and the detached hyphenated initial "-D"
# both parse as names, so the old audit passed them, yet `render`
# turns them into "Y. K. `. Lee" and drops the hyphen of "H.-D.". The
# TeX-accented entry is well-formed and must keep passing: after
# TeX-to-unicode conversion, "{\.I}lhan" is "İlhan", which initializes
# fine.
_ILL_INITIAL_BIB = r"""@string{prl = {Phys. Rev. Lett.}}

@article{Nickname2026,
    author = {Lee, Yoo Kyung `Eunice' and Doe, John},
    doi = {10.1000/nickname},
    journal = prl,
    pages = {110501},
    title = {An Author with a Quoted Nickname},
    volume = {137},
    year = {2026}}

@article{StrayHyphen2026,
    author = {Meyer, H -D},
    doi = {10.1000/stray-hyphen},
    journal = prl,
    pages = {110502},
    title = {An Author with a Detached Hyphenated Initial},
    volume = {137},
    year = {2026}}

@article{Accent2026,
    author = {Polat, {\.I}lhan and Ribeiro, Ant{\^o}nio H.},
    doi = {10.1000/accent},
    journal = prl,
    pages = {110503},
    title = {Authors with TeX-Accented First Names},
    volume = {137},
    year = {2026}}
"""


def test_check_flags_names_with_ill_defined_initials(runner, tmp_path):
    bibfile = tmp_path / "library.bib"
    bibfile.write_text(_ILL_INITIAL_BIB, encoding="utf-8")
    result = runner.invoke(main, ["check", str(bibfile)])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[0] == (
        'Nickname2026: author name "Lee, Yoo Kyung `Eunice\'" has a '
        'first-name part ("`Eunice\'") that cannot be initialized'
    )
    assert lines[1] == (
        'StrayHyphen2026: author name "Meyer, H -D" has a first-name '
        'part ("-D") that cannot be initialized'
    )
    assert not any(line.startswith("Accent2026: ") for line in lines)
    assert lines[-1] == "FAIL (2 problems, 3 entries checked)"


def test_check_ill_defined_initials_json(runner, tmp_path):
    bibfile = tmp_path / "library.bib"
    bibfile.write_text(_ILL_INITIAL_BIB, encoding="utf-8")
    result = runner.invoke(main, ["check", str(bibfile), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert [(p["check"], p["key"]) for p in data["problems"]] == [
        ("names", "Nickname2026"),
        ("names", "StrayHyphen2026"),
    ]


# A hyphen that trails a first-name token (`H-`, from `Meyer, H- D`)
# or doubles inside one (`A--B`) is the mirror of the leading-hyphen
# `-D` case: `render` drops the empty segment, so `H- D` and `H -D`
# both render as "H. D. Meyer" for what should be "H.-D.". Both must
# be flagged, not just the leading-hyphen form.
_HYPHEN_MIRROR_BIB = r"""@article{TrailingHyphen2026,
    author = {Meyer, H- D},
    doi = {10.1000/trailing},
    title = {t},
    year = {2026}}

@article{DoubledHyphen2026,
    author = {Foo, A--B},
    doi = {10.1000/doubled},
    title = {t},
    year = {2026}}
"""


def test_check_flags_trailing_and_doubled_hyphen_initials(runner, tmp_path):
    bibfile = tmp_path / "library.bib"
    bibfile.write_text(_HYPHEN_MIRROR_BIB, encoding="utf-8")
    result = runner.invoke(main, ["check", str(bibfile)])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert (
        'TrailingHyphen2026: author name "Meyer, H- D" has a '
        'first-name part ("H-") that cannot be initialized'
    ) in lines
    assert (
        'DoubledHyphen2026: author name "Foo, A--B" has a '
        'first-name part ("A--B") that cannot be initialized'
    ) in lines


def test_timestamp(runner, bibfile):
    result = _run(runner, "timestamp", bibfile)
    expected = _load(bibfile).timestamp.isoformat()
    assert result.output.strip() == expected


def test_timestamp_json(runner, bibfile):
    result = _run(runner, "timestamp", bibfile, "--json")
    expected = _load(bibfile).timestamp.isoformat()
    assert json.loads(result.output) == expected


def test_path(runner, bibfile):
    result = _run(runner, "path", bibfile)
    assert result.output.splitlines() == [str(bibfile.resolve())]
    result = _run(runner, "path", bibfile, "--json")
    assert json.loads(result.output) == str(bibfile.resolve())


def test_path_default_bib_file(runner, bibfile, tmp_path, monkeypatch):
    """`path` resolves the configured `default_bib_file`."""
    (tmp_path / "bibdeskparser.toml").write_text(
        'default_bib_file = "refs.bib"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = _run(runner, "path")
    assert result.output.splitlines() == [str(bibfile.resolve())]


def test_config_path(runner, bibfile, tmp_path):
    """`config_path` finds the config next to the `.bib` file."""
    toml = tmp_path / "bibdeskparser.toml"
    toml.write_text("", encoding="utf-8")
    result = _run(runner, "config_path", bibfile)
    assert result.output.splitlines() == [str(toml.resolve())]
    result = _run(runner, "config_path", bibfile, "--json")
    assert json.loads(result.output) == str(toml.resolve())


def test_config_path_none(runner, bibfile):
    """Without a discoverable config, `config_path` fails cleanly."""
    result = runner.invoke(main, ["config_path", str(bibfile)])
    assert result.exit_code == 1
    assert "no configuration file found" in result.stderr


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
    result = _run(runner, "export", bibfile, "GoerzJPB2011", "--minimal")
    assert "@article{GoerzJPB2011," in result.output
    assert "Abstract" not in result.output


def test_export_expand_strings(runner, bibfile):
    """--expand-strings inlines macro values and drops the @string
    block."""
    result = _run(
        runner, "export", bibfile, "GoerzJPB2011", "--expand-strings"
    )
    assert "Journal = {J. Phys. B}," in result.output
    assert "@string" not in result.output


def test_export_no_unicode(runner, bibfile):
    """--no-unicode exports the TeX-encoded stored values."""
    result = _run(
        runner, "export", bibfile, "GoerzDiploma2010", "--no-unicode"
    )
    assert 'Universit{\\"a}t' in result.output


def test_export_field(runner, bibfile):
    """--field restricts the export to the named fields."""
    result = _run(
        runner, "export", bibfile, "GoerzJPB2011", "--field", "title,year"
    )
    assert "Title = {" in result.output
    assert "Year = {2011}," in result.output
    assert "Journal" not in result.output


def test_export_preprint_modes(runner, bibfile):
    """--preprint selects the export form of a preprint-only entry."""
    result = _run(runner, "export", bibfile, "Wilhelm2003.10132", "--minimal")
    # default: unpublished, with the stored status note
    assert "@unpublished{Wilhelm2003.10132," in result.output
    assert "Eprint = {2003.10132}," in result.output
    assert "Note = {preprint only}," in result.output
    assert "Journal" not in result.output
    result = _run(
        runner,
        "export",
        bibfile,
        "Wilhelm2003.10132",
        "--minimal",
        "--preprint",
        "misc",
    )
    assert "@misc{Wilhelm2003.10132," in result.output
    result = _run(
        runner,
        "export",
        bibfile,
        "Wilhelm2003.10132",
        "--minimal",
        "--preprint",
        "article",
    )
    assert "@article{Wilhelm2003.10132," in result.output
    assert "Journal = {arXiv:2003.10132}," in result.output
    assert (
        "Url = {https://doi.org/10.48550/arxiv.2003.10132}," in result.output
    )
    assert "Eprint" not in result.output
    result = _run(
        runner,
        "export",
        bibfile,
        "Wilhelm2003.10132",
        "--preprint",
        "stored",
    )
    assert "@unpublished{Wilhelm2003.10132," in result.output
    assert "Journal = {arXiv:2003.10132}," in result.output
    assert "Eprint = {2003.10132}," in result.output


def test_export_minimal_field_mutually_exclusive(runner, bibfile):
    result = runner.invoke(
        main,
        [
            "export",
            str(bibfile),
            "GoerzJPB2011",
            "--minimal",
            "--field",
            "doi",
        ],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.stderr


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


def test_create(runner, tmp_path):
    """`create` writes a new, empty library with a BibDesk header."""
    newfile = tmp_path / "new.bib"
    result = _run(runner, "create", newfile)
    assert result.output == ""
    lib = Library(newfile)
    assert len(lib) == 0
    assert lib.timestamp is not None
    assert "Created for" in newfile.read_text(encoding="utf-8")


def test_create_existing_file_fails(runner, bibfile):
    """`create` never overwrites an existing file."""
    before = bibfile.read_text(encoding="utf-8")
    result = runner.invoke(main, ["create", str(bibfile)])
    assert result.exit_code == 1
    assert "already exists" in result.stderr
    assert "Traceback" not in result.stderr
    assert bibfile.read_text(encoding="utf-8") == before


def test_create_default_bib_file(runner, tmp_path, monkeypatch):
    """`create` without BIBFILE bootstraps the configured
    `default_bib_file`."""
    (tmp_path / "bibdeskparser.toml").write_text(
        'default_bib_file = "new.bib"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    _run(runner, "create")
    assert len(Library(tmp_path / "new.bib")) == 0


def test_create_missing_parent_dir(runner, tmp_path):
    """`create` in a nonexistent directory fails cleanly."""
    result = runner.invoke(
        main, ["create", str(tmp_path / "no-such-dir" / "new.bib")]
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr


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


def test_set_field_empty_value_rejected(runner, bibfile):
    """An empty (or whitespace-only) VALUE is an error: BibDesk would
    delete the field on its next save."""
    for value in ("", "   "):
        result = runner.invoke(
            main, ["set_field", str(bibfile), "GoerzJPB2011", "doi", value]
        )
        assert result.exit_code != 0
        assert "an empty VALUE is never stored" in result.stderr
        assert "delete_field" in result.stderr
        assert "known-missing group" in result.stderr
    # the existing value is untouched
    doi = _load(bibfile)["GoerzJPB2011"]["doi"]
    assert str(doi) == "10.1088/0953-4075/44/15/154011"


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
        main, ["delete_field", str(bibfile), "GoerzJPB2011", "number"]
    )
    assert result.exit_code == 1
    assert "has no field 'number'" in result.stderr


def test_delete_field_protected(runner, bibfile):
    result = runner.invoke(
        main, ["delete_field", str(bibfile), "GoerzJPB2011", "keywords"]
    )
    assert result.exit_code == 1
    assert "add_to_keyword" in result.stderr


def test_add_to_group(runner, bibfile):
    _run(runner, "add_to_group", bibfile, "Diploma", "GoerzDiploma2010")
    lib = _load(bibfile)
    assert "GoerzDiploma2010" in lib.groups["Diploma"]


def test_remove_from_group(runner, bibfile):
    _run(runner, "remove_from_group", bibfile, "Diploma", "Tannor2007")
    assert "Tannor2007" not in _load(bibfile).groups["Diploma"]


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
    _run(runner, "delete_group", bibfile, "Diploma")
    assert "Diploma" not in _load(bibfile).groups


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


def test_rename_string_mixed_case(runner, bibfile):
    """A mixed-case new name (as in the command's own `--help`
    example) is normalized to lowercase, matching BibDesk's
    case-insensitive macro table."""
    _run(runner, "rename_string", bibfile, "jpb", "PhysRevLett")
    lib = _load(bibfile)
    assert lib.strings["physrevlett"] == "J. Phys. B"
    assert lib["GoerzJPB2011"]["journal"] == "physrevlett"


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
        "GoerzJPB2011.pdf",
        "new.pdf",
    )
    assert _load(bibfile)["GoerzJPB2011"].files == ["new.pdf"]
    # without --remove, the old file stays on disk
    assert (tmp_path / "GoerzJPB2011.pdf").exists()


def test_unlink_file(runner, bibfile, tmp_path):
    _run(runner, "unlink_file", bibfile, "GoerzJPB2011", "GoerzJPB2011.pdf")
    assert _load(bibfile)["GoerzJPB2011"].files == []
    assert (tmp_path / "GoerzJPB2011.pdf").exists()


def test_unlink_file_remove(runner, bibfile, tmp_path):
    _run(
        runner,
        "unlink_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB2011.pdf",
        "--remove",
    )
    assert _load(bibfile)["GoerzJPB2011"].files == []
    assert not (tmp_path / "GoerzJPB2011.pdf").exists()


def test_rename_file(runner, bibfile, tmp_path):
    _run(
        runner,
        "rename_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB2011.pdf",
        "renamed.pdf",
    )
    assert _load(bibfile)["GoerzJPB2011"].files == ["renamed.pdf"]
    assert (tmp_path / "renamed.pdf").exists()
    assert not (tmp_path / "GoerzJPB2011.pdf").exists()


def test_rename_file_auto_from_config(runner, bibfile, tmp_path):
    """`rename_file` without NEW auto-files per the `[auto_file]`
    table and prints the new library-relative path."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[auto_file]\nformat_spec = "%f{Cite Key}%u0%e"\n',
        encoding="utf-8",
    )
    # move the attachment away from its auto-filed name first
    _run(
        runner,
        "rename_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB2011.pdf",
        "misfiled.pdf",
    )
    result = _run(
        runner, "rename_file", bibfile, "GoerzJPB2011", "misfiled.pdf"
    )
    assert result.output.strip() == "GoerzJPB2011.pdf"
    assert _load(bibfile)["GoerzJPB2011"].files == ["GoerzJPB2011.pdf"]
    assert (tmp_path / "GoerzJPB2011.pdf").exists()
    assert not (tmp_path / "misfiled.pdf").exists()


def test_rename_file_options(runner, bibfile, tmp_path):
    """Explicit `--location`/`--format-spec` override the config."""
    result = _run(
        runner,
        "rename_file",
        bibfile,
        "GoerzJPB2011",
        "GoerzJPB2011.pdf",
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
            "GoerzJPB2011.pdf",
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
    old = "https://michaelgoerz.net/research/diploma_thesis.pdf"
    new = "https://example.org/thesis.pdf"
    _run(runner, "replace_url", bibfile, "GoerzDiploma2010", old, new)
    assert _load(bibfile)["GoerzDiploma2010"].urls == (new,)


def test_remove_url(runner, bibfile):
    url = "https://michaelgoerz.net/research/diploma_thesis.pdf"
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
    edited = exported.replace("Year = {2011}", "Year = nosuchmacro")
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
    assert "bibdeskparser create" in result.stderr  # points at the fix
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


def test_import_keep_journals(runner, bibfile):
    """`--keep-journals` preserves a literal journal that would
    otherwise resolve to an `@string` macro."""
    result = runner.invoke(
        main,
        ["import", str(bibfile), "--stdin", "--keep-journals"],
        input=IMPORT_SNIPPET,
    )
    assert result.exit_code == 0, result.output + result.stderr
    key = result.stdout.strip()
    text = bibfile.read_text(encoding="utf-8")
    assert f"@article{{{key}" in text
    assert "journal = {Phys. Rev. Lett.}" in text


def test_import_unrecognized_archive(runner, bibfile):
    """A pseudo-journal with an unknown archive prefix is rejected,
    with a hint at `[preprint_archives]` and `--keep-journals`."""
    text = IMPORT_SNIPPET.replace("{Phys. Rev. Lett.}", "{EarthArXiv:X5129}")
    result = runner.invoke(
        main, ["import", str(bibfile), "--stdin"], input=text
    )
    assert result.exit_code == 1
    assert "'EarthArXiv' is not recognized" in result.stderr
    assert "[preprint_archives]" in result.stderr
    result = runner.invoke(
        main,
        ["import", str(bibfile), "--stdin", "--keep-journals"],
        input=text,
    )
    assert result.exit_code == 0, result.output + result.stderr


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

    def fetch_bibtex(query, *, include_abstract=False):
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

    def fetch_bibtex(query, *, include_abstract=False):
        queries.append(query)
        return IMPORT_SNIPPET

    monkeypatch.setattr("bibdeskparser.fetch.fetch_bibtex", fetch_bibtex)
    _run(runner, "add", bibfile, "quantifying", "coherence")
    assert queries == ["quantifying coherence"]


def test_add_dry_run(runner, bibfile, monkeypatch):
    monkeypatch.setattr(
        "bibdeskparser.fetch.fetch_bibtex",
        lambda query, *, include_abstract=False: IMPORT_SNIPPET,
    )
    before = bibfile.read_text(encoding="utf-8")
    result = _run(runner, "add", bibfile, "--dry-run", "10.1103/xyz")
    assert "@article{BaumgratzPRL2014," in result.stdout
    assert "@string{prl = {Phys. Rev. Lett.}}" in result.stdout
    assert bibfile.read_text(encoding="utf-8") == before


def test_add_fetch_failure(runner, bibfile, monkeypatch):
    def fetch_bibtex(query, *, include_abstract=False):
        raise ValueError(f"could not fetch bibliographic data for {query!r}")

    monkeypatch.setattr("bibdeskparser.fetch.fetch_bibtex", fetch_bibtex)
    result = runner.invoke(main, ["add", str(bibfile), "10.1103/xyz"])
    assert result.exit_code == 1
    assert "Error: could not fetch bibliographic data" in result.stderr


ABSTRACT = (
    "We show that optimizing a quantum gate for an open quantum "
    "system requires the time evolution of only three states. This "
    "represents a significant reduction in computational resources "
    "compared to the complete basis of Liouville space that is "
    "commonly believed necessary for this task, and we illustrate "
    "the reduction for a controlled phasegate with trapped atoms."
)


def _mock_fetch_abstract(monkeypatch, results):
    """Mock `abstracts.fetch_abstract` to pop per-call results from
    the `results` list; records the call kwargs."""
    from bibdeskparser.abstracts import AbstractResult

    calls = []

    def fetch_abstract(**kwargs):
        calls.append(kwargs)
        return AbstractResult(*results.pop(0), applied=False)

    monkeypatch.setattr(
        "bibdeskparser.abstracts.fetch_abstract", fetch_abstract
    )
    return calls


def test_add_abstract_stores(runner, bibfile, monkeypatch):
    calls = _mock_fetch_abstract(
        monkeypatch, [(ABSTRACT, "crossref", "high", "ok")]
    )
    result = _run(runner, "add_abstract", bibfile, "GoerzPhd2015")
    assert result.stdout == "GoerzPhd2015: stored (crossref, high)\n"
    assert calls[0]["key"] == "GoerzPhd2015"
    lib = _load(bibfile)
    assert lib["GoerzPhd2015"]["abstract"] == ABSTRACT


def test_add_abstract_needs_review(runner, bibfile, monkeypatch):
    _mock_fetch_abstract(monkeypatch, [(ABSTRACT, "pdf", "medium", "no-doi")])
    result = _run(runner, "add_abstract", bibfile, "GoerzPhd2015")
    assert "GoerzPhd2015: needs review (pdf, medium) [no-doi]" in result.stdout
    assert ABSTRACT in result.stdout  # reported in full, for review
    lib = _load(bibfile)
    assert "abstract" not in lib["GoerzPhd2015"]


def test_add_abstract_min_confidence(runner, bibfile, monkeypatch):
    _mock_fetch_abstract(monkeypatch, [(ABSTRACT, "pdf", "medium", "no-doi")])
    result = _run(
        runner,
        "add_abstract",
        bibfile,
        "--min-confidence",
        "medium",
        "GoerzPhd2015",
    )
    assert "GoerzPhd2015: stored (pdf, medium)" in result.stdout
    lib = _load(bibfile)
    assert lib["GoerzPhd2015"]["abstract"] == ABSTRACT


def test_add_abstract_skips_existing(runner, bibfile, monkeypatch):
    def fetch_abstract(**kwargs):  # pragma: no cover
        raise AssertionError("must not fetch")

    monkeypatch.setattr(
        "bibdeskparser.abstracts.fetch_abstract", fetch_abstract
    )
    result = _run(runner, "add_abstract", bibfile, "GoerzNJP2014")
    assert "GoerzNJP2014: skipped (already has an abstract" in result.stdout


def test_add_abstract_overwrite(runner, bibfile, monkeypatch):
    _mock_fetch_abstract(monkeypatch, [(ABSTRACT, "crossref", "high", "ok")])
    _run(runner, "add_abstract", bibfile, "--overwrite", "GoerzNJP2014")
    lib = _load(bibfile)
    assert lib["GoerzNJP2014"]["abstract"] == ABSTRACT


def test_add_abstract_not_found_and_known_missing(
    runner, bibfile, monkeypatch
):
    """Without a `[known_missing]` configuration a clean no-find
    modifies nothing; with one, it is recorded as group membership
    (in the saved file), and members are skipped."""
    _mock_fetch_abstract(
        monkeypatch,
        [("", "none", "none", "cr-miss"), ("", "none", "none", "cr-miss")],
    )
    result = _run(runner, "add_abstract", bibfile, "GoerzPhd2015")
    assert "GoerzPhd2015: no abstract found [cr-miss]" in result.stdout
    lib = _load(bibfile)
    assert "abstract" not in lib["GoerzPhd2015"]
    assert "No Abstract" not in lib.groups
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\nabstract = "No Abstract"\n', encoding="utf-8"
    )
    result = _run(runner, "add_abstract", bibfile, "GoerzPhd2015")
    assert (
        "GoerzPhd2015: no abstract found (marked known missing in "
        "group 'No Abstract') [cr-miss]" in result.stdout
    )
    lib = _load(bibfile)
    assert "abstract" not in lib["GoerzPhd2015"]
    assert lib.groups["No Abstract"] == ("GoerzPhd2015",)
    monkeypatch.setattr(
        "bibdeskparser.abstracts.fetch_abstract",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("must not fetch")
        ),
    )
    result = _run(runner, "add_abstract", bibfile, "GoerzPhd2015")
    assert (
        "GoerzPhd2015: skipped (known missing; --overwrite to re-search)"
        in result.stdout
    )


def test_add_abstract_json(runner, bibfile, monkeypatch):
    _mock_fetch_abstract(
        monkeypatch,
        [
            (ABSTRACT, "crossref", "high", "ok"),
            ("", "none", "none", "cr-miss"),
        ],
    )
    result = _run(
        runner,
        "add_abstract",
        bibfile,
        "--json",
        "GoerzPhd2015",
        "GoerzDiploma2010",
    )
    data = json.loads(result.stdout)
    assert data["GoerzPhd2015"] == {
        "abstract": ABSTRACT,
        "source": "crossref",
        "confidence": "high",
        "note": "ok",
        "applied": True,
    }
    assert data["GoerzDiploma2010"]["applied"] is False
    lib = _load(bibfile)
    assert lib["GoerzPhd2015"]["abstract"] == ABSTRACT


def test_add_abstract_dry_run(runner, bibfile, monkeypatch):
    _mock_fetch_abstract(monkeypatch, [(ABSTRACT, "crossref", "high", "ok")])
    before = bibfile.read_text(encoding="utf-8")
    result = _run(runner, "add_abstract", bibfile, "--dry-run", "GoerzPhd2015")
    assert "GoerzPhd2015: stored (crossref, high)" in result.stdout
    assert bibfile.read_text(encoding="utf-8") == before


def test_add_abstract_unknown_key(runner, bibfile):
    result = runner.invoke(main, ["add_abstract", str(bibfile), "NoSuchKey"])
    assert result.exit_code == 1
    assert "unknown citation key 'NoSuchKey'" in result.stderr


def _mock_find_preprint(monkeypatch, results):
    """Mock `preprints.find_preprint` to pop per-call results from the
    `results` list -- `(eprint, match, ratio, note)` tuples, with an
    optional fifth `primaryclass` element; records the call kwargs."""
    from bibdeskparser.preprints import PreprintResult

    calls = []

    def find_preprint(**kwargs):
        calls.append(kwargs)
        eprint, match, ratio, note, *rest = results.pop(0)
        primaryclass = rest[0] if rest else ""
        return PreprintResult(eprint, match, ratio, note, False, primaryclass)

    monkeypatch.setattr("bibdeskparser.preprints.find_preprint", find_preprint)
    return calls


def _forbid_find_preprint(monkeypatch):
    def find_preprint(**kwargs):  # pragma: no cover
        raise AssertionError("must not search")

    monkeypatch.setattr("bibdeskparser.preprints.find_preprint", find_preprint)


def test_add_preprint_stores(runner, bibfile, monkeypatch):
    calls = _mock_find_preprint(
        monkeypatch, [("2510.12345", "doi", 1.0, "", "math.OC")]
    )
    result = _run(runner, "add_preprint", bibfile, "WinckelIP2008")
    assert result.stdout == (
        "WinckelIP2008: stored eprint 2510.12345 [math.OC] "
        "(match=doi, ratio=1.00)\n"
    )
    assert calls[0]["doi"] == "10.1088/0266-5611/24/3/034007"
    lib = _load(bibfile)
    assert lib["WinckelIP2008"]["eprint"] == "2510.12345"
    assert lib["WinckelIP2008"]["archiveprefix"] == "arXiv"
    assert lib["WinckelIP2008"]["primaryclass"] == "math.OC"


def test_add_preprint_skips_existing(runner, bibfile, monkeypatch):
    _forbid_find_preprint(monkeypatch)
    result = _run(runner, "add_preprint", bibfile, "GoerzNJP2014")
    assert "GoerzNJP2014: skipped (already has an eprint" in result.stdout
    lib = _load(bibfile)
    assert lib["GoerzNJP2014"]["eprint"] == "1312.0111"


def test_add_preprint_overwrite(runner, bibfile, monkeypatch):
    _mock_find_preprint(monkeypatch, [("2510.12345", "title", 0.99, "")])
    _run(runner, "add_preprint", bibfile, "--overwrite", "GoerzNJP2014")
    lib = _load(bibfile)
    assert lib["GoerzNJP2014"]["eprint"] == "2510.12345"


def test_add_preprint_not_found_and_known_missing(
    runner, bibfile, monkeypatch
):
    """Without a `[known_missing]` configuration a clean no-match
    modifies nothing; with one, it is recorded as group membership
    (in the saved file), and members are skipped."""
    _mock_find_preprint(
        monkeypatch,
        [
            ("", "none", 0.55, "best-ratio=0.55"),
            ("", "none", 0.55, "best-ratio=0.55"),
        ],
    )
    result = _run(runner, "add_preprint", bibfile, "WinckelIP2008")
    assert (
        "WinckelIP2008: no preprint found [best-ratio=0.55]" in result.stdout
    )
    lib = _load(bibfile)
    assert "eprint" not in lib["WinckelIP2008"]
    assert "No Eprint" not in lib.groups
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\neprint = "No Eprint"\n', encoding="utf-8"
    )
    result = _run(runner, "add_preprint", bibfile, "WinckelIP2008")
    assert (
        "WinckelIP2008: no preprint found (marked known missing in "
        "group 'No Eprint') [best-ratio=0.55]" in result.stdout
    )
    lib = _load(bibfile)
    assert "eprint" not in lib["WinckelIP2008"]
    assert "archiveprefix" not in lib["WinckelIP2008"]
    assert lib.groups["No Eprint"] == ("WinckelIP2008",)
    _forbid_find_preprint(monkeypatch)
    result = _run(runner, "add_preprint", bibfile, "WinckelIP2008")
    assert (
        "WinckelIP2008: skipped (known missing; --overwrite to re-search)"
        in result.stdout
    )


def test_add_preprint_error(runner, bibfile, monkeypatch):
    """A failed search is reported and stores nothing, even with a
    known-missing group configured."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\neprint = "No Eprint"\n', encoding="utf-8"
    )
    _mock_find_preprint(
        monkeypatch, [("", "error", 0.0, "arxiv-error(HTTPError: 500)")]
    )
    before = bibfile.read_text(encoding="utf-8")
    result = _run(runner, "add_preprint", bibfile, "WinckelIP2008")
    assert (
        "WinckelIP2008: search failed [arxiv-error(HTTPError: 500)]"
        in result.stdout
    )
    assert bibfile.read_text(encoding="utf-8") == before


def test_add_preprint_explicit(runner, bibfile, monkeypatch):
    _forbid_find_preprint(monkeypatch)
    result = _run(
        runner,
        "add_preprint",
        bibfile,
        "--eprint",
        "arXiv:2510.12345v2",
        "WinckelIP2008",
    )
    assert result.stdout == "WinckelIP2008: stored eprint 2510.12345\n"
    lib = _load(bibfile)
    assert lib["WinckelIP2008"]["eprint"] == "2510.12345"
    assert lib["WinckelIP2008"]["archiveprefix"] == "arXiv"


def test_add_preprint_explicit_invalid(runner, bibfile):
    result = runner.invoke(
        main,
        [
            "add_preprint",
            str(bibfile),
            "--eprint",
            "10.1103/x",
            "WinckelIP2008",
        ],
    )
    assert result.exit_code == 1
    assert "Error: not a valid arXiv identifier" in result.stderr


def test_add_preprint_explicit_single_key_only(runner, bibfile):
    result = runner.invoke(
        main,
        [
            "add_preprint",
            str(bibfile),
            "--eprint",
            "2510.12345",
            "WinckelIP2008",
            "GoerzPhd2015",
        ],
    )
    assert result.exit_code == 2
    assert "--eprint requires a single KEY" in result.stderr


def test_add_preprint_json(runner, bibfile, monkeypatch):
    _mock_find_preprint(
        monkeypatch,
        [
            ("2510.12345", "title+author", 0.95, "", "math.OC"),
            ("", "none", 0.4, "best-ratio=0.40"),
        ],
    )
    result = _run(
        runner,
        "add_preprint",
        bibfile,
        "--json",
        "WinckelIP2008",
        "GoerzPhd2015",
    )
    data = json.loads(result.stdout)
    assert data["WinckelIP2008"] == {
        "eprint": "2510.12345",
        "match": "title+author",
        "ratio": 0.95,
        "note": "",
        "applied": True,
        "primaryclass": "math.OC",
    }
    assert data["GoerzPhd2015"]["applied"] is False
    lib = _load(bibfile)
    assert lib["WinckelIP2008"]["eprint"] == "2510.12345"


def test_add_preprint_dry_run(runner, bibfile, monkeypatch):
    _mock_find_preprint(monkeypatch, [("2510.12345", "doi", 1.0, "")])
    before = bibfile.read_text(encoding="utf-8")
    result = _run(
        runner, "add_preprint", bibfile, "--dry-run", "WinckelIP2008"
    )
    assert "WinckelIP2008: stored eprint 2510.12345" in result.stdout
    assert bibfile.read_text(encoding="utf-8") == before


def test_add_preprint_unknown_key(runner, bibfile):
    result = runner.invoke(main, ["add_preprint", str(bibfile), "NoSuchKey"])
    assert result.exit_code == 1
    assert "unknown citation key 'NoSuchKey'" in result.stderr


def _mock_find_doi(monkeypatch, results):
    """Mock `dois.find_doi` to pop per-call results from the `results`
    list -- `(doi, match, ratio, note)` tuples; records the call
    kwargs."""
    from bibdeskparser.dois import DoiResult

    calls = []

    def find_doi(**kwargs):
        calls.append(kwargs)
        doi, match, ratio, note = results.pop(0)
        return DoiResult(doi, match, ratio, note, False)

    monkeypatch.setattr("bibdeskparser.dois.find_doi", find_doi)
    return calls


def _forbid_find_doi(monkeypatch):
    def find_doi(**kwargs):  # pragma: no cover
        raise AssertionError("must not search")

    monkeypatch.setattr("bibdeskparser.dois.find_doi", find_doi)


def test_add_doi_stores(runner, bibfile, monkeypatch):
    calls = _mock_find_doi(
        monkeypatch, [("10.1016/j.aop.2004.09.012", "title+author", 0.98, "")]
    )
    result = _run(runner, "add_doi", bibfile, "GoerzPhd2015")
    assert result.stdout == (
        "GoerzPhd2015: stored doi 10.1016/j.aop.2004.09.012 "
        "(match=title+author, ratio=0.98)\n"
    )
    assert calls[0]["title"] == (
        "Optimizing Robust Quantum Gates in Open Quantum Systems"
    )
    lib = _load(bibfile)
    assert lib["GoerzPhd2015"]["doi"] == "10.1016/j.aop.2004.09.012"


def test_add_doi_stores_via_eprint(runner, bibfile, monkeypatch):
    """A DOI found on arXiv (match `eprint`) reports without a
    ratio."""
    _mock_find_doi(
        monkeypatch, [("10.1016/j.aop.2004.09.012", "eprint", None, "")]
    )
    result = _run(runner, "add_doi", bibfile, "GoerzPhd2015")
    assert result.stdout == (
        "GoerzPhd2015: stored doi 10.1016/j.aop.2004.09.012 "
        "(match=eprint)\n"
    )


def test_add_doi_skips_existing(runner, bibfile, monkeypatch):
    _forbid_find_doi(monkeypatch)
    result = _run(runner, "add_doi", bibfile, "GoerzNJP2014")
    assert "GoerzNJP2014: skipped (already has a doi" in result.stdout
    lib = _load(bibfile)
    assert lib["GoerzNJP2014"]["doi"] == "10.1088/1367-2630/16/5/055012"


def test_add_doi_skips_preprint_only(runner, bibfile, monkeypatch):
    """A preprint-only entry without a `doi` is skipped without any
    lookup."""
    _forbid_find_doi(monkeypatch)
    lib = _load(bibfile)
    del lib["Wilhelm2003.10132"]["doi"]
    lib.save()
    result = _run(runner, "add_doi", bibfile, "Wilhelm2003.10132")
    assert "Wilhelm2003.10132: skipped (preprint-only entry)" in result.stdout
    lib = _load(bibfile)
    assert "doi" not in lib["Wilhelm2003.10132"]


def test_add_doi_overwrite(runner, bibfile, monkeypatch):
    _mock_find_doi(monkeypatch, [("10.5555/xyz", "title", 0.99, "")])
    _run(runner, "add_doi", bibfile, "--overwrite", "GoerzNJP2014")
    lib = _load(bibfile)
    assert lib["GoerzNJP2014"]["doi"] == "10.5555/xyz"


def test_add_doi_not_found_and_known_missing(runner, bibfile, monkeypatch):
    """Without a `[known_missing]` configuration a clean no-match
    modifies nothing; with one, it is recorded as group membership
    (in the saved file), and members are skipped."""
    _mock_find_doi(
        monkeypatch,
        [
            ("", "none", 0.55, "best-ratio=0.55"),
            ("", "none", 0.55, "best-ratio=0.55"),
        ],
    )
    result = _run(runner, "add_doi", bibfile, "GoerzPhd2015")
    assert "GoerzPhd2015: no doi found [best-ratio=0.55]" in result.stdout
    lib = _load(bibfile)
    assert "doi" not in lib["GoerzPhd2015"]
    assert "No DOI" not in lib.groups
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\ndoi = "No DOI"\n', encoding="utf-8"
    )
    result = _run(runner, "add_doi", bibfile, "GoerzPhd2015")
    assert (
        "GoerzPhd2015: no doi found (marked known missing in "
        "group 'No DOI') [best-ratio=0.55]" in result.stdout
    )
    lib = _load(bibfile)
    assert "doi" not in lib["GoerzPhd2015"]
    assert lib.groups["No DOI"] == ("GoerzPhd2015",)
    _forbid_find_doi(monkeypatch)
    result = _run(runner, "add_doi", bibfile, "GoerzPhd2015")
    assert (
        "GoerzPhd2015: skipped (known missing; --overwrite to re-search)"
        in result.stdout
    )


def test_add_doi_error(runner, bibfile, monkeypatch):
    """A failed lookup is reported and stores nothing, even with a
    known-missing group configured."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        '[known_missing]\ndoi = "No DOI"\n', encoding="utf-8"
    )
    _mock_find_doi(
        monkeypatch, [("", "error", 0.0, "crossref-error(HTTPError: 500)")]
    )
    before = bibfile.read_text(encoding="utf-8")
    result = _run(runner, "add_doi", bibfile, "GoerzPhd2015")
    assert (
        "GoerzPhd2015: lookup failed [crossref-error(HTTPError: 500)]"
        in result.stdout
    )
    assert bibfile.read_text(encoding="utf-8") == before


def test_add_doi_explicit(runner, bibfile, monkeypatch):
    _forbid_find_doi(monkeypatch)
    result = _run(
        runner,
        "add_doi",
        bibfile,
        "--doi",
        "https://doi.org/10.1016/j.aop.2004.09.012",
        "GoerzPhd2015",
    )
    assert result.stdout == (
        "GoerzPhd2015: stored doi 10.1016/j.aop.2004.09.012\n"
    )
    lib = _load(bibfile)
    assert lib["GoerzPhd2015"]["doi"] == "10.1016/j.aop.2004.09.012"


def test_add_doi_explicit_invalid(runner, bibfile):
    result = runner.invoke(
        main,
        ["add_doi", str(bibfile), "--doi", "2205.15044", "GoerzPhd2015"],
    )
    assert result.exit_code == 1
    assert "Error: not a valid DOI" in result.stderr


def test_add_doi_explicit_single_key_only(runner, bibfile):
    result = runner.invoke(
        main,
        [
            "add_doi",
            str(bibfile),
            "--doi",
            "10.5555/xyz",
            "GoerzPhd2015",
            "GoerzDiploma2010",
        ],
    )
    assert result.exit_code == 2
    assert "--doi requires a single KEY" in result.stderr


def test_add_doi_json(runner, bibfile, monkeypatch):
    _mock_find_doi(
        monkeypatch,
        [
            ("10.5555/xyz", "title+author", 0.95, ""),
            ("", "none", 0.4, "best-ratio=0.40"),
        ],
    )
    result = _run(
        runner,
        "add_doi",
        bibfile,
        "--json",
        "GoerzPhd2015",
        "GoerzDiploma2010",
    )
    data = json.loads(result.stdout)
    assert data["GoerzPhd2015"] == {
        "doi": "10.5555/xyz",
        "match": "title+author",
        "ratio": 0.95,
        "note": "",
        "applied": True,
    }
    assert data["GoerzDiploma2010"]["applied"] is False
    lib = _load(bibfile)
    assert lib["GoerzPhd2015"]["doi"] == "10.5555/xyz"


def test_add_doi_dry_run(runner, bibfile, monkeypatch):
    _mock_find_doi(monkeypatch, [("10.5555/xyz", "title", 1.0, "")])
    before = bibfile.read_text(encoding="utf-8")
    result = _run(runner, "add_doi", bibfile, "--dry-run", "GoerzPhd2015")
    assert "GoerzPhd2015: stored doi 10.5555/xyz" in result.stdout
    assert bibfile.read_text(encoding="utf-8") == before


def test_add_doi_unknown_key(runner, bibfile):
    result = runner.invoke(main, ["add_doi", str(bibfile), "NoSuchKey"])
    assert result.exit_code == 1
    assert "unknown citation key 'NoSuchKey'" in result.stderr


def test_add_passes_add_abstract(runner, bibfile, monkeypatch):
    flags = []

    def fetch_bibtex(query, *, include_abstract=False):
        flags.append(include_abstract)
        return IMPORT_SNIPPET

    monkeypatch.setattr("bibdeskparser.fetch.fetch_bibtex", fetch_bibtex)
    _run(runner, "add", bibfile, "--dry-run", "--add-abstract", "10.1103/x")
    _run(runner, "add", bibfile, "--dry-run", "--no-add-abstract", "10.1103/x")
    assert flags == [True, False]


def test_add_with_add_preprint(runner, bibfile, monkeypatch):
    """`add --add-preprint` searches for the new entry's preprint and
    reports the result on stderr (stdout stays the citation key)."""
    monkeypatch.setattr(
        "bibdeskparser.fetch.fetch_bibtex",
        lambda query, *, include_abstract=False: IMPORT_SNIPPET.replace(
            "PhysRevLett.113.140401,", "Fetched,"
        ),
    )
    _mock_find_preprint(monkeypatch, [("1311.0275", "doi", 1.0, "")])
    result = _run(
        runner, "add", bibfile, "--add-preprint", "10.1103/PhysRevLett.x"
    )
    assert result.stdout == "BaumgratzPRL2014\n"
    assert (
        "BaumgratzPRL2014: stored eprint 1311.0275 (match=doi, ratio=1.00)"
        in result.stderr
    )
    lib = _load(bibfile)
    assert lib["BaumgratzPRL2014"]["eprint"] == "1311.0275"


def test_add_add_preprint_config_default(runner, bibfile, monkeypatch):
    """Without `--add-preprint`, the `[add]` configuration next to the
    `.bib` file supplies the default; `--no-add-preprint` overrides
    it."""
    (bibfile.parent / "bibdeskparser.toml").write_text(
        "[add]\nadd_preprint = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "bibdeskparser.fetch.fetch_bibtex",
        lambda query, *, include_abstract=False: IMPORT_SNIPPET.replace(
            "PhysRevLett.113.140401,", "Fetched,"
        ),
    )
    _mock_find_preprint(monkeypatch, [("1311.0275", "doi", 1.0, "")])
    _run(runner, "add", bibfile, "10.1103/PhysRevLett.x")
    lib = _load(bibfile)
    assert lib["BaumgratzPRL2014"]["eprint"] == "1311.0275"


def test_add_no_add_preprint_overrides_config(runner, bibfile, monkeypatch):
    (bibfile.parent / "bibdeskparser.toml").write_text(
        "[add]\nadd_preprint = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "bibdeskparser.fetch.fetch_bibtex",
        lambda query, *, include_abstract=False: IMPORT_SNIPPET.replace(
            "PhysRevLett.113.140401,", "Fetched,"
        ),
    )
    _forbid_find_preprint(monkeypatch)
    _run(runner, "add", bibfile, "--no-add-preprint", "10.1103/PhysRevLett.x")
    lib = _load(bibfile)
    assert "eprint" not in lib["BaumgratzPRL2014"]


def test_negative_flag_forms_accepted(runner, bibfile, monkeypatch):
    """Every boolean behavior option has an explicit negative form
    (so that defaults can change without breaking compatibility)."""
    monkeypatch.setattr(
        "bibdeskparser.fetch.fetch_bibtex",
        lambda query, *, include_abstract=False: IMPORT_SNIPPET,
    )
    _run(
        runner,
        "add",
        bibfile,
        "--dry-run",
        "--no-fix-uppercase",
        "--no-add-abstract",
        "--no-add-preprint",
        "10.1103/xyz",
    )
    result = _run(runner, "show", bibfile, "GoerzNJP2014", "--no-skip-missing")
    assert "GoerzNJP2014" in result.stdout


def test_export_preprint_unpublished(runner, bibfile):
    """--preprint unpublished writes @unpublished with a guaranteed
    note (the stored note here; TuriniciHAL00640217 also gets the
    HAL `archive` link base)."""
    result = _run(
        runner,
        "export",
        bibfile,
        "TuriniciHAL00640217",
        "--minimal",
        "--preprint",
        "unpublished",
    )
    assert "@unpublished{TuriniciHAL00640217," in result.output
    assert "Note = {lecture notes}," in result.output
    assert "Eprint = {hal-00640217}," in result.output
    assert "Archive = {https://hal.science}," in result.output
    assert "Journal" not in result.output
