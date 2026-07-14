"""Tests for `bibdeskparser.config` and the config-file feature."""

import warnings
from pathlib import Path

import pytest

import bibdeskparser.config as config
from bibdeskparser import Entry, Library

_CONFIG = "bibdeskparser.toml"


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the process-global configuration around every test here.

    The configuration (entry-type/field validation and its flags) is
    process-global, so a test that loads a custom config or flips a flag
    must not leak into any other test.
    """
    config.active.reset()
    yield
    config.active.reset()


def _write(directory, text):
    (directory / _CONFIG).write_text(text, encoding="utf-8")


# -- discovery -------------------------------------------------------- #


def test_discover_none(tmp_path, monkeypatch):
    """No config file anywhere -> discover returns None."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.discover(bib_dir=tmp_path) is None


def test_discover_bib_dir(tmp_path, monkeypatch):
    """A file next to the .bib file is found."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "verify_types = false\n")
    assert config.discover(bib_dir=tmp_path) == tmp_path / _CONFIG


def test_discover_xdg(tmp_path, monkeypatch):
    """With nothing local and `$BIBDESKPARSER_CONFIG` unset, the XDG
    location is used."""
    monkeypatch.delenv("BIBDESKPARSER_CONFIG")
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    target = xdg / "bibdeskparser" / _CONFIG
    target.parent.mkdir(parents=True)
    _write(target.parent, "verify_types = false\n")
    assert config.discover(bib_dir=tmp_path / "empty") == target


def test_discover_precedence_first_found_wins(tmp_path, monkeypatch):
    """config_file beats the bib directory, which beats XDG."""
    monkeypatch.delenv("BIBDESKPARSER_CONFIG")
    xdg = tmp_path / "xdg" / "bibdeskparser"
    xdg.mkdir(parents=True)
    _write(xdg, "verify_types = false\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    bib_dir = tmp_path / "lib"
    bib_dir.mkdir()
    _write(bib_dir, "verify_types = false\n")
    explicit = tmp_path / "explicit.toml"
    explicit.write_text("verify_types = false\n", encoding="utf-8")
    assert config.discover(bib_dir=bib_dir, config_file=explicit) == explicit
    assert config.discover(bib_dir=bib_dir) == bib_dir / _CONFIG


def test_discover_missing_config_file_raises(tmp_path):
    """An explicit config_file that does not exist raises."""
    with pytest.raises(FileNotFoundError):
        config.discover(config_file=tmp_path / "nope.toml")


def test_discover_env_var(tmp_path, monkeypatch):
    """`$BIBDESKPARSER_CONFIG` names the user-level config file, and
    takes precedence over the XDG location."""
    xdg = tmp_path / "xdg"
    target = xdg / "bibdeskparser" / _CONFIG
    target.parent.mkdir(parents=True)
    _write(target.parent, "verify_types = false\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    custom = tmp_path / "custom.toml"
    custom.write_text("verify_fields = false\n", encoding="utf-8")
    monkeypatch.setenv("BIBDESKPARSER_CONFIG", str(custom))
    assert config.discover(bib_dir=tmp_path / "empty") == custom


def test_discover_env_var_empty_disables_xdg(tmp_path, monkeypatch):
    """An empty `$BIBDESKPARSER_CONFIG` disables the XDG location."""
    xdg = tmp_path / "xdg"
    target = xdg / "bibdeskparser" / _CONFIG
    target.parent.mkdir(parents=True)
    _write(target.parent, "verify_types = false\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("BIBDESKPARSER_CONFIG", "")
    assert config.discover(bib_dir=tmp_path / "empty") is None


def test_discover_env_var_missing_raises(tmp_path, monkeypatch):
    """A `$BIBDESKPARSER_CONFIG` that does not exist raises."""
    monkeypatch.setenv("BIBDESKPARSER_CONFIG", str(tmp_path / "nope.toml"))
    with pytest.raises(FileNotFoundError, match="BIBDESKPARSER_CONFIG"):
        config.discover(bib_dir=tmp_path)


def test_discover_local_beats_env_var(tmp_path, monkeypatch):
    """A file next to the .bib file beats `$BIBDESKPARSER_CONFIG`."""
    _write(tmp_path, "verify_types = false\n")
    custom = tmp_path / "custom.toml"
    custom.write_text("verify_fields = false\n", encoding="utf-8")
    monkeypatch.setenv("BIBDESKPARSER_CONFIG", str(custom))
    assert config.discover(bib_dir=tmp_path) == tmp_path / _CONFIG


# -- flags ------------------------------------------------------------ #


def test_defaults():
    assert Library.config.verify_types is True
    assert Library.config.verify_fields is True
    assert Library.config.config_file is None
    assert Library.config.journal_macros == {}
    assert Library.config.protected_words == []


def test_config_instance_access():
    """The configuration is the same object on the class and on any
    instance, and mutating it through one is visible through the
    other."""
    bib = Library()
    assert bib.config is Library.config
    assert bib.config is config.active
    assert bib.config.verify_types is True
    Library.config.verify_types = False
    assert bib.config.verify_types is False
    bib.config.verify_types = True
    assert Library.config.verify_types is True


def test_verify_types_flag_via_class_attribute():
    """Library.config.verify_types controls whether unknown types raise."""
    with pytest.raises(ValueError):
        Entry("nosuchtype", "k")
    Library.config.verify_types = False
    entry = Entry("nosuchtype", "k")  # accepted, lowercased
    assert entry.entry_type == "nosuchtype"
    Library.config.verify_types = True
    with pytest.raises(ValueError):
        Entry("nosuchtype", "k")


def test_verify_fields_flag_via_class_attribute():
    """Library.config.verify_fields controls the inappropriate-field
    warning."""
    with pytest.warns(UserWarning, match="not appropriate"):
        Entry("article", "k")["publisher"] = "ACME"
    Library.config.verify_fields = False
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Entry("article", "k")["publisher"] = "ACME"  # no warning


def test_load_from_bib_dir_sets_flags(tmp_path):
    """Loading a config file with verify_types=false disables it."""
    _write(tmp_path, "verify_types = false\nverify_fields = false\n")
    config.active.load(bib_dir=tmp_path)
    assert Library.config.verify_types is False
    assert Library.config.verify_fields is False


def test_load_none_resets_to_defaults(tmp_path):
    """load() with no file found resets to the built-in defaults."""
    Library.config.verify_types = False
    assert config.active.load(bib_dir=tmp_path) is None
    assert Library.config.verify_types is True


# -- custom types / fields -------------------------------------------- #


def test_custom_type_defined(tmp_path):
    """A brand-new entry type is recognized and templated."""
    _write(
        tmp_path,
        "[types.mytype]\n"
        'required = ["author", "title"]\n'
        'optional = ["note"]\n',
    )
    config.active.load(bib_dir=tmp_path)
    entry = Entry("mytype", "k")  # does not raise
    assert entry.entry_type == "mytype"
    assert config.active.field_is_appropriate("mytype", "note")
    assert not config.active.field_is_appropriate("mytype", "publisher")


def test_type_extend_adds_optional_field(tmp_path):
    """Without replace, a [types.X] table extends the built-in fields."""
    _write(tmp_path, '[types.article]\noptional = ["customfield"]\n')
    config.active.load(bib_dir=tmp_path)
    # built-in article fields still appropriate ...
    assert config.active.field_is_appropriate("article", "journal")
    # ... plus the new one
    assert config.active.field_is_appropriate("article", "customfield")


def test_type_replace(tmp_path):
    """replace = true discards the built-in template."""
    _write(
        tmp_path,
        "[types.article]\nreplace = true\n"
        'required = ["title"]\noptional = ["note"]\n',
    )
    config.active.load(bib_dir=tmp_path)
    assert config.active.field_is_appropriate("article", "note")
    # 'journal' was a built-in article field, now gone (and not
    # universal), so it is no longer appropriate
    assert not config.active.field_is_appropriate("article", "journal")


def test_custom_universal_field(tmp_path):
    """[fields] universal makes a field appropriate on every type."""
    _write(tmp_path, '[fields]\nuniversal = ["myglobal"]\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.field_is_appropriate("article", "myglobal")
    assert config.active.field_is_appropriate("book", "myglobal")


# -- default_bib_file -------------------------------------------------- #


def test_default_bib_file(tmp_path, monkeypatch):
    """`default_bib_file` is stored as a `Path`, `~`- and
    `$VAR`-expanded, and cleared again by `reset()`."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path))
    # Windows `expanduser` resolves `~` from USERPROFILE, not HOME
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _write(tmp_path, 'default_bib_file = "~/refs.bib"\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.default_bib_file == tmp_path / "refs.bib"
    config.active.reset()
    assert config.active.default_bib_file is None


def test_default_bib_file_envvar_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("MYBIBDIR", str(tmp_path / "bibs"))
    _write(tmp_path, 'default_bib_file = "$MYBIBDIR/refs.bib"\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.default_bib_file == tmp_path / "bibs" / "refs.bib"


def test_default_bib_file_cleared_when_no_config(tmp_path, monkeypatch):
    """A `load()` that finds no config file clears `default_bib_file`."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, 'default_bib_file = "refs.bib"\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.default_bib_file is not None
    empty = tmp_path / "empty"
    empty.mkdir()
    config.active.load(bib_dir=empty)
    assert config.active.default_bib_file is None


def test_default_bib_file_non_string_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "default_bib_file = 42\n")
    with pytest.raises(ValueError, match="default_bib_file"):
        config.active.load(bib_dir=tmp_path)


# -- auto_key and initials --------------------------------------------- #


def test_auto_key_defaults(tmp_path, monkeypatch):
    """Without an `[auto_key]` table, no format is configured and the
    post-processing options are at their defaults."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "verify_types = false\n")
    config.active.load(bib_dir=tmp_path)
    assert config.active.auto_key.format_spec is None
    assert config.active.auto_key.lowercase is False
    assert config.active.auto_key.clean == "tex"
    assert config.active.initials == {}


def test_auto_key_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(
        tmp_path,
        "[auto_key]\n"
        'format_spec = "%a1%c{journal}0%Y%u0"\n'
        "lowercase = true\n"
        'clean = "braces"\n'
        "\n"
        "[initials.journal]\n"
        '"npj Quantum Inf" = "NPJQI"\n'
        '"SIAM Rev." = "SR"\n',
    )
    config.active.load(bib_dir=tmp_path)
    assert config.active.auto_key.format_spec == "%a1%c{journal}0%Y%u0"
    assert config.active.auto_key.lowercase is True
    assert config.active.auto_key.clean == "braces"
    assert config.active.initials == {
        "journal": {"npj Quantum Inf": "NPJQI", "SIAM Rev.": "SR"}
    }
    config.active.reset()
    assert config.active.auto_key.format_spec is None
    assert config.active.initials == {}


def test_auto_key_format_spec_override_not_persisted(tmp_path, monkeypatch):
    """Assigning `Library.config.auto_key.format_spec` overrides the
    value for the current process only; it does not write back to the
    config file."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    original = '[auto_key]\nformat_spec = "%a1%Y%u0"\n'
    _write(tmp_path, original)
    config.active.load(bib_dir=tmp_path)
    assert Library.config.auto_key.format_spec == "%a1%Y%u0"

    Library.config.auto_key.format_spec = "%a1%c{journal}0%Y"
    assert Library.config.auto_key.format_spec == "%a1%c{journal}0%Y"
    # the file on disk is untouched
    assert (tmp_path / _CONFIG).read_text(encoding="utf-8") == original
    # reloading discards the in-process override
    config.active.load(bib_dir=tmp_path)
    assert Library.config.auto_key.format_spec == "%a1%Y%u0"


def test_auto_key_per_type_format_spec(tmp_path, monkeypatch):
    """An `[auto_key.format_spec]` table maps a format per entry type,
    with type names lowercased and `""` kept as the fallback."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(
        tmp_path,
        "[auto_key.format_spec]\n"
        '"" = "%a1%Y%u0"\n'
        'Article = "%a1%c{journal}0%Y%u0"\n'
        'inproceedings = "%a1%c{booktitle}0%Y%u0"\n',
    )
    config.active.load(bib_dir=tmp_path)
    assert config.active.auto_key.format_spec == {
        "": "%a1%Y%u0",
        "article": "%a1%c{journal}0%Y%u0",
        "inproceedings": "%a1%c{booktitle}0%Y%u0",
    }


def test_auto_key_format_spec_required(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "[auto_key]\nlowercase = true\n")
    with pytest.raises(ValueError, match="'format_spec'"):
        config.active.load(bib_dir=tmp_path)


def test_auto_key_format_spec_validated(tmp_path, monkeypatch):
    """A malformed format is rejected at load time, whether it is a
    single string or a per-type table value."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, '[auto_key]\nformat_spec = "%a1%x"\n')
    with pytest.raises(ValueError, match="invalid specifier"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, '[auto_key]\nformat_spec = "%a1%i{Project}"\n')
    with pytest.raises(NotImplementedError, match="%i"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, '[auto_key.format_spec]\narticle = "%a1%x"\n')
    with pytest.raises(ValueError, match="invalid specifier"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, "[auto_key.format_spec]\narticle = 3\n")
    with pytest.raises(ValueError, match="format_spec values"):
        config.active.load(bib_dir=tmp_path)


def test_auto_key_format_spec_non_string_key():
    """A per-type table with a non-string key (only reachable via the
    Python API) raises `ValueError`, not `AttributeError`."""
    with pytest.raises(ValueError, match="format_spec keys"):
        Library.config.auto_key.format_spec = {1: "%a1%Y"}


def test_auto_key_option_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, '[auto_key]\nformat_spec = "%a1"\nlowercase = "yes"\n')
    with pytest.raises(ValueError, match="lowercase"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, '[auto_key]\nformat_spec = "%a1"\nclean = "all"\n')
    with pytest.raises(ValueError, match="clean"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, '[auto_key]\nformat_spec = "%a1"\nnonsense = 1\n')
    with pytest.warns(UserWarning, match=r"unknown key\(s\) in \[auto_key\]"):
        config.active.load(bib_dir=tmp_path)


# -- auto_file ---------------------------------------------------------- #


def test_auto_file_defaults(tmp_path, monkeypatch):
    """Without an `[auto_file]` table, no format is configured and the
    other settings are at their defaults."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "verify_types = false\n")
    config.active.load(bib_dir=tmp_path)
    auto_file = config.active.auto_file
    assert auto_file.format_spec is None
    assert auto_file.location == Path(".")
    assert auto_file.lowercase is False
    assert auto_file.clean == "tex"
    assert auto_file.file_automatically is False


def test_auto_file_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(
        tmp_path,
        "[auto_file]\n"
        'format_spec = "%f{Cite Key}%u0%e"\n'
        'location = "Papers"\n'
        "lowercase = true\n"
        'clean = "braces"\n'
        "file_automatically = true\n",
    )
    config.active.load(bib_dir=tmp_path)
    auto_file = config.active.auto_file
    assert auto_file.format_spec == "%f{Cite Key}%u0%e"
    assert auto_file.location == Path("Papers")
    assert auto_file.lowercase is True
    assert auto_file.clean == "braces"
    assert auto_file.file_automatically is True
    config.active.reset()
    assert config.active.auto_file.format_spec is None
    assert config.active.auto_file.file_automatically is False


def test_auto_file_per_type_format_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(
        tmp_path,
        "[auto_file.format_spec]\n"
        '"" = "%l%u0%e"\n'
        'Article = "%f{Cite Key}%u0%e"\n',
    )
    config.active.load(bib_dir=tmp_path)
    assert config.active.auto_file.format_spec == {
        "": "%l%u0%e",
        "article": "%f{Cite Key}%u0%e",
    }


def test_auto_file_format_spec_required(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, '[auto_file]\nlocation = "."\n')
    with pytest.raises(ValueError, match="'format_spec'"):
        config.active.load(bib_dir=tmp_path)


def test_auto_file_format_spec_requires_unique(tmp_path, monkeypatch):
    """A file-name format without a `%u`/`%U`/`%n` specifier is
    rejected at load time."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, '[auto_file]\nformat_spec = "%f{Cite Key}%e"\n')
    with pytest.raises(ValueError, match="unique specifier"):
        config.active.load(bib_dir=tmp_path)


def test_auto_file_location_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    base = '[auto_file]\nformat_spec = "%l%u0%e"\n'
    _write(tmp_path, base + 'location = ""\n')
    with pytest.raises(ValueError, match="location"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, base + "location = 3\n")
    with pytest.raises(ValueError, match="location"):
        config.active.load(bib_dir=tmp_path)


def test_auto_file_location_expansion(tmp_path, monkeypatch):
    """`~` and `$VAR` are expanded in the auto-file location."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("PAPERS_DIR", str(tmp_path / "papers"))
    base = '[auto_file]\nformat_spec = "%l%u0%e"\n'
    _write(tmp_path, base + 'location = "$PAPERS_DIR"\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.auto_file.location == tmp_path / "papers"
    _write(tmp_path, base + 'location = "~/Papers"\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.auto_file.location == Path.home() / "Papers"


def test_auto_file_option_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    base = '[auto_file]\nformat_spec = "%l%u0%e"\n'
    _write(tmp_path, base + 'lowercase = "yes"\n')
    with pytest.raises(ValueError, match="lowercase"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, base + 'file_automatically = "yes"\n')
    with pytest.raises(ValueError, match="file_automatically"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, base + 'clean = "all"\n')
    with pytest.raises(ValueError, match="clean"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, base + "nonsense = 1\n")
    with pytest.warns(UserWarning, match=r"unknown key\(s\) in \[auto_file\]"):
        config.active.load(bib_dir=tmp_path)


def test_initials_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "initials = 1\n")
    with pytest.raises(ValueError, match=r"\[initials\] must be a table"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, "[initials]\njournal = 1\n")
    with pytest.raises(ValueError, match=r"\[initials.journal\]"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, '[initials.journal]\n"npj Quantum Inf" = 1\n')
    with pytest.raises(ValueError, match=r"\[initials.journal\]"):
        config.active.load(bib_dir=tmp_path)


def test_initials_field_names_lowercased(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, '[initials.Journal]\n"npj Quantum Inf" = "NPJQI"\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.initials == {"journal": {"npj Quantum Inf": "NPJQI"}}


def test_journal_macros_parsing(tmp_path, monkeypatch):
    """Macro names are normalized; values may be a name or a list of
    names (canonical value first, aliases after)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(
        tmp_path,
        "[journal_macros]\n"
        'PRL = "Phys. Rev. Lett."\n'
        'jpb = ["J. Phys. B", "J. Phys. B: At. Mol. Opt. Phys."]\n',
    )
    config.active.load(bib_dir=tmp_path)
    assert config.active.journal_macros == {
        "prl": ("Phys. Rev. Lett.",),
        "jpb": ("J. Phys. B", "J. Phys. B: At. Mol. Opt. Phys."),
    }
    config.active.reset()
    assert config.active.journal_macros == {}


def test_journal_macros_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "journal_macros = 1\n")
    with pytest.raises(
        ValueError, match=r"\[journal_macros\] must be a table"
    ):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, '[journal_macros]\n"1abc" = "Some Journal"\n')
    with pytest.raises(ValueError, match="invalid macro name"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, "[journal_macros]\nprl = 1\n")
    with pytest.raises(ValueError, match="journal name"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, "[journal_macros]\nprl = []\n")
    with pytest.raises(ValueError, match="journal name"):
        config.active.load(bib_dir=tmp_path)
    _write(tmp_path, '[journal_macros]\nprl = ["Phys. Rev. Lett.", ""]\n')
    with pytest.raises(ValueError, match="journal name"):
        config.active.load(bib_dir=tmp_path)
    _write(
        tmp_path,
        '[journal_macros]\nprl = "Phys. Rev. Lett."\nPRL = "PRL"\n',
    )
    with pytest.raises(ValueError, match="more than once"):
        config.active.load(bib_dir=tmp_path)


def test_protected_words_parsing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, 'protected_words = ["Rydberg", " NMR "]\n')
    config.active.load(bib_dir=tmp_path)
    assert config.active.protected_words == ["Rydberg", "NMR"]
    config.active.reset()
    assert config.active.protected_words == []


def test_protected_words_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for bad in ('protected_words = "Rydberg"\n', "protected_words = [1]\n"):
        _write(tmp_path, bad)
        with pytest.raises(ValueError, match="protected_words"):
            config.active.load(bib_dir=tmp_path)
    _write(tmp_path, 'protected_words = [""]\n')
    with pytest.raises(ValueError, match="protected_words"):
        config.active.load(bib_dir=tmp_path)


# -- error handling --------------------------------------------------- #


def test_malformed_toml_raises(tmp_path):
    _write(tmp_path, "this is not = valid = toml\n")
    with pytest.raises(ValueError, match="invalid config file"):
        config.active.load(bib_dir=tmp_path)


def test_non_bool_flag_raises(tmp_path):
    _write(tmp_path, 'verify_types = "yes"\n')
    with pytest.raises(ValueError, match="verify_types"):
        config.active.load(bib_dir=tmp_path)


def test_unknown_key_warns(tmp_path):
    _write(tmp_path, "nonsense = 1\n")
    with pytest.warns(UserWarning, match="unknown key"):
        config.active.load(bib_dir=tmp_path)


# -- Library integration ---------------------------------------------- #


def test_library_construction_applies_bib_dir_config(tmp_path):
    """Constructing a Library applies a config next to its .bib file."""
    _write(tmp_path, "verify_types = false\n")
    (tmp_path / "x.bib").write_text("@nosuchtype{k,\n}\n", encoding="utf-8")
    Library(str(tmp_path / "x.bib"))
    assert Library.config.verify_types is False
    # a fresh Entry now accepts unknown types
    assert Entry("anothernonexistenttype", "k").entry_type == (
        "anothernonexistenttype"
    )


def test_config_file_override(tmp_path):
    """Library.config.config_file takes precedence over directory
    discovery."""
    explicit = tmp_path / "custom.toml"
    explicit.write_text("verify_fields = false\n", encoding="utf-8")
    _write(tmp_path, "verify_fields = true\n")  # would otherwise win
    Library.config.config_file = str(explicit)
    try:
        assert config.active.load(bib_dir=tmp_path) == explicit
        assert Library.config.verify_fields is False
    finally:
        Library.config.config_file = None
