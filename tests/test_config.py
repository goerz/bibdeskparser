"""Tests for `bibdeskparser.config` and the config-file feature."""

import warnings

import pytest

import bibdeskparser.config as config
import bibdeskparser.entrytypes as entrytypes
from bibdeskparser import Entry, Library

_CONFIG = "bibdeskparser.toml"


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the process-global configuration around every test here.

    The configuration (entry-type/field validation and its flags) is
    process-global, so a test that loads a custom config or flips a flag
    must not leak into any other test.
    """
    config.reset()
    yield
    config.reset()


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
    """With nothing local, the XDG location is used."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    target = xdg / "bibdeskparser" / _CONFIG
    target.parent.mkdir(parents=True)
    _write(target.parent, "verify_types = false\n")
    assert config.discover(bib_dir=tmp_path / "empty") == target


def test_discover_precedence_first_found_wins(tmp_path, monkeypatch):
    """config_file beats the bib directory, which beats XDG."""
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


# -- flags ------------------------------------------------------------ #


def test_defaults():
    assert Library.verify_types is True
    assert Library.verify_fields is True
    assert Library.config_file is None


def test_verify_types_flag_via_class_attribute():
    """Library.verify_types controls whether unknown types raise."""
    with pytest.raises(ValueError):
        Entry("nosuchtype", "k")
    Library.verify_types = False
    entry = Entry("nosuchtype", "k")  # accepted, lowercased
    assert entry.entry_type == "nosuchtype"
    Library.verify_types = True
    with pytest.raises(ValueError):
        Entry("nosuchtype", "k")


def test_verify_fields_flag_via_class_attribute():
    """Library.verify_fields controls the inappropriate-field warning."""
    with pytest.warns(UserWarning, match="not appropriate"):
        Entry("article", "k")["publisher"] = "ACME"
    Library.verify_fields = False
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Entry("article", "k")["publisher"] = "ACME"  # no warning


def test_load_from_bib_dir_sets_flags(tmp_path):
    """Loading a config file with verify_types=false disables it."""
    _write(tmp_path, "verify_types = false\nverify_fields = false\n")
    config.load(bib_dir=tmp_path)
    assert Library.verify_types is False
    assert Library.verify_fields is False


def test_load_none_resets_to_defaults(tmp_path):
    """load() with no file found resets to the built-in defaults."""
    Library.verify_types = False
    assert config.load(bib_dir=tmp_path) is None
    assert Library.verify_types is True


# -- custom types / fields -------------------------------------------- #


def test_custom_type_defined(tmp_path):
    """A brand-new entry type is recognized and templated."""
    _write(
        tmp_path,
        "[types.mytype]\n"
        'required = ["author", "title"]\n'
        'optional = ["note"]\n',
    )
    config.load(bib_dir=tmp_path)
    entry = Entry("mytype", "k")  # does not raise
    assert entry.entry_type == "mytype"
    assert entrytypes.field_is_appropriate("mytype", "note")
    assert not entrytypes.field_is_appropriate("mytype", "publisher")


def test_type_extend_adds_optional_field(tmp_path):
    """Without replace, a [types.X] table extends the built-in fields."""
    _write(tmp_path, '[types.article]\noptional = ["customfield"]\n')
    config.load(bib_dir=tmp_path)
    # built-in article fields still appropriate ...
    assert entrytypes.field_is_appropriate("article", "journal")
    # ... plus the new one
    assert entrytypes.field_is_appropriate("article", "customfield")


def test_type_replace(tmp_path):
    """replace = true discards the built-in template."""
    _write(
        tmp_path,
        "[types.article]\nreplace = true\n"
        'required = ["title"]\noptional = ["note"]\n',
    )
    config.load(bib_dir=tmp_path)
    assert entrytypes.field_is_appropriate("article", "note")
    # 'journal' was a built-in article field, now gone (and not
    # universal), so it is no longer appropriate
    assert not entrytypes.field_is_appropriate("article", "journal")


def test_custom_universal_field(tmp_path):
    """[fields] universal makes a field appropriate on every type."""
    _write(tmp_path, '[fields]\nuniversal = ["myglobal"]\n')
    config.load(bib_dir=tmp_path)
    assert entrytypes.field_is_appropriate("article", "myglobal")
    assert entrytypes.field_is_appropriate("book", "myglobal")


# -- default_bib_file -------------------------------------------------- #


def test_default_bib_file(tmp_path, monkeypatch):
    """`default_bib_file` is stored as a `Path`, `~`- and
    `$VAR`-expanded, and cleared again by `reset()`."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path))
    _write(tmp_path, 'default_bib_file = "~/refs.bib"\n')
    config.load(bib_dir=tmp_path)
    assert config.get_default_bib_file() == tmp_path / "refs.bib"
    config.reset()
    assert config.get_default_bib_file() is None


def test_default_bib_file_envvar_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("MYBIBDIR", str(tmp_path / "bibs"))
    _write(tmp_path, 'default_bib_file = "$MYBIBDIR/refs.bib"\n')
    config.load(bib_dir=tmp_path)
    assert config.get_default_bib_file() == tmp_path / "bibs" / "refs.bib"


def test_default_bib_file_cleared_when_no_config(tmp_path, monkeypatch):
    """A `load()` that finds no config file clears `default_bib_file`."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, 'default_bib_file = "refs.bib"\n')
    config.load(bib_dir=tmp_path)
    assert config.get_default_bib_file() is not None
    empty = tmp_path / "empty"
    empty.mkdir()
    config.load(bib_dir=empty)
    assert config.get_default_bib_file() is None


def test_default_bib_file_non_string_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    _write(tmp_path, "default_bib_file = 42\n")
    with pytest.raises(ValueError, match="default_bib_file"):
        config.load(bib_dir=tmp_path)


# -- error handling --------------------------------------------------- #


def test_malformed_toml_raises(tmp_path):
    _write(tmp_path, "this is not = valid = toml\n")
    with pytest.raises(ValueError, match="invalid config file"):
        config.load(bib_dir=tmp_path)


def test_non_bool_flag_raises(tmp_path):
    _write(tmp_path, 'verify_types = "yes"\n')
    with pytest.raises(ValueError, match="verify_types"):
        config.load(bib_dir=tmp_path)


def test_unknown_key_warns(tmp_path):
    _write(tmp_path, "nonsense = 1\n")
    with pytest.warns(UserWarning, match="unknown key"):
        config.load(bib_dir=tmp_path)


# -- Library integration ---------------------------------------------- #


def test_library_construction_applies_bib_dir_config(tmp_path):
    """Constructing a Library applies a config next to its .bib file."""
    _write(tmp_path, "verify_types = false\n")
    (tmp_path / "x.bib").write_text("@nosuchtype{k,\n}\n", encoding="utf-8")
    Library(str(tmp_path / "x.bib"))
    assert Library.verify_types is False
    # a fresh Entry now accepts unknown types
    assert Entry("anothernonexistenttype", "k").entry_type == (
        "anothernonexistenttype"
    )


def test_config_file_override(tmp_path):
    """Library.config_file takes precedence over directory discovery."""
    explicit = tmp_path / "custom.toml"
    explicit.write_text("verify_fields = false\n", encoding="utf-8")
    Library.config_file = str(explicit)
    try:
        config.load(bib_dir=tmp_path, config_file=Library.config_file)
        assert Library.verify_fields is False
    finally:
        Library.config_file = None
