"""Loading of the `bibdeskparser.toml` configuration file.

This module discovers and applies a `bibdeskparser.toml` file, which
replicates some of the preferences the BibDesk application offers: the
`verify_types` and `verify_fields` flags, and custom or extended entry
types and field names. The effective configuration is process-global
(applied to `bibdeskparser.entrytypes`), because entry-type and field
validation happens on individual {class}`~bibdeskparser.Entry` objects,
which hold no reference to any owning library. See the
[configuration](configuration) reference page for the file format and
discovery rules.
"""

import os
import warnings
from pathlib import Path

from . import entrytypes

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "CONFIG_FILENAME",
    "discover",
    "load",
    "reset",
    "get_verify_types",
    "set_verify_types",
    "get_verify_fields",
    "set_verify_fields",
    "get_config_file",
    "set_config_file",
    "get_default_bib_file",
]

#: The name of the configuration file that is searched for.
CONFIG_FILENAME = "bibdeskparser.toml"

# Backs the `Library.config_file` class attribute: an explicit config
# file path that takes precedence over directory-based discovery.
_config_file_override = None

# The recognized top-level keys of a `bibdeskparser.toml`; anything else
# triggers a (non-fatal) warning, for forward compatibility.
_KNOWN_TOP_LEVEL_KEYS = frozenset(
    ("verify_types", "verify_fields", "types", "fields", "default_bib_file")
)

# The `default_bib_file` from the most recently applied config file (a
# `Path`, with environment variables and `~` expanded), or `None`. Used
# by the command-line interface when no bibfile is given explicitly.
_default_bib_file = None


def _xdg_config_path():
    """The XDG standard location of `bibdeskparser.toml` (a `Path`).

    This is `$XDG_CONFIG_HOME/bibdeskparser/bibdeskparser.toml`, falling
    back to `~/.config/bibdeskparser/bibdeskparser.toml` when
    `$XDG_CONFIG_HOME` is unset.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "bibdeskparser" / CONFIG_FILENAME


def discover(bib_dir=None, config_file=None):
    """Locate the applicable `bibdeskparser.toml`, first found wins.

    The locations are searched in order of precedence:

    1. `config_file`, if given (the `Library.config_file` override);
       raises {exc}`FileNotFoundError` if it does not exist.
    2. `CONFIG_FILENAME` in `bib_dir` (the directory of the `.bib` file,
       or the current working directory if `bib_dir` is `None`).
    3. `CONFIG_FILENAME` in the XDG location (see `_xdg_config_path`).

    Returns the `Path` of the first existing file, or `None` if none of
    the locations has one.
    """
    if config_file is not None:
        path = Path(config_file)
        if not path.exists():
            raise FileNotFoundError(
                f"config_file does not exist: {config_file}"
            )
        return path
    local = Path(bib_dir or Path.cwd()) / CONFIG_FILENAME
    if local.exists():
        return local
    xdg = _xdg_config_path()
    if xdg.exists():
        return xdg
    return None


def _parse(path):
    """Parse the TOML file at `path`, raising a {exc}`ValueError` (that
    names the file) if it is malformed."""
    try:
        with open(path, "rb") as toml_file:
            return tomllib.load(toml_file)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid config file {path}: {exc}") from exc


def _bool(raw, key):
    """Read boolean `key` from `raw`, defaulting to `True`."""
    value = raw.get(key, True)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean, not {type(value)!r}")
    return value


def _field_list(value, context):
    """Validate `value` as a list of field-name strings; return them
    lowercased."""
    if not isinstance(value, list) or not all(
        isinstance(field, str) for field in value
    ):
        raise ValueError(f"{context} must be a list of strings")
    return [field.lower() for field in value]


def _build(raw):
    """Build the keyword arguments for {func}`entrytypes.set_active`
    from a parsed `bibdeskparser.toml` (`raw`), layering its
    customizations onto the built-in defaults."""
    unknown = set(raw) - _KNOWN_TOP_LEVEL_KEYS
    if unknown:
        warnings.warn(
            f"unknown key(s) in {CONFIG_FILENAME}: {sorted(unknown)}",
            UserWarning,
            stacklevel=3,
        )

    documented_types = {
        entry_type: {
            "required": tuple(spec["required"]),
            "optional": tuple(spec["optional"]),
        }
        for entry_type, spec in entrytypes.DOCUMENTED_TYPES.items()
    }
    recognized = set(entrytypes.RECOGNIZED_ENTRY_TYPES)
    universal = set(entrytypes.UNIVERSAL_FIELDS)
    known = set(entrytypes.KNOWN_FIELDS)

    types_table = raw.get("types", {})
    if not isinstance(types_table, dict):
        raise ValueError("[types] must be a table")
    for name, spec in types_table.items():
        if not isinstance(spec, dict):
            raise ValueError(f"[types.{name}] must be a table")
        name = name.lower()
        required = _field_list(
            spec.get("required", []), f"[types.{name}] required"
        )
        optional = _field_list(
            spec.get("optional", []), f"[types.{name}] optional"
        )
        replace = bool(spec.get("replace", False))
        if replace or name not in documented_types:
            documented_types[name] = {
                "required": tuple(required),
                "optional": tuple(optional),
            }
        else:
            base = documented_types[name]
            documented_types[name] = {
                "required": base["required"]
                + tuple(f for f in required if f not in base["required"]),
                "optional": base["optional"]
                + tuple(f for f in optional if f not in base["optional"]),
            }
        recognized.add(name)
        known.update(required)
        known.update(optional)

    fields_table = raw.get("fields", {})
    if not isinstance(fields_table, dict):
        raise ValueError("[fields] must be a table")
    extra_universal = _field_list(
        fields_table.get("universal", []), "[fields] universal"
    )
    universal.update(extra_universal)
    known.update(extra_universal)
    known.update(_field_list(fields_table.get("known", []), "[fields] known"))

    return {
        "verify_types": _bool(raw, "verify_types"),
        "verify_fields": _bool(raw, "verify_fields"),
        "documented_types": documented_types,
        "recognized_entry_types": recognized,
        "universal_fields": universal,
        "known_fields": known,
    }


def _parse_default_bib_file(raw):
    """Read the optional `default_bib_file` key from `raw`.

    Returns a `Path` with environment variables (`$VAR`) and a leading
    `~` expanded, or `None` if the key is absent.
    """
    value = raw.get("default_bib_file", None)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"default_bib_file must be a string, not {type(value)!r}"
        )
    return Path(os.path.expandvars(value)).expanduser()


def load(bib_dir=None, config_file=None):
    """Discover and apply a `bibdeskparser.toml`.

    Searches (see {func}`discover`) and, if a file is found, parses it
    and applies it to the active configuration; otherwise resets the
    active configuration to the built-in defaults. Returns the `Path`
    that was applied, or `None` if none was found.

    Raises {exc}`ValueError` if the discovered file is malformed, and
    {exc}`FileNotFoundError` if an explicit `config_file` does not
    exist.
    """
    global _default_bib_file
    path = discover(bib_dir=bib_dir, config_file=config_file)
    if path is None:
        entrytypes.reset_active()
        _default_bib_file = None
        return None
    raw = _parse(path)
    default_bib_file = _parse_default_bib_file(raw)
    entrytypes.set_active(**_build(raw))
    _default_bib_file = default_bib_file
    return path


def reset():
    """Reset all configuration to the built-in defaults.

    Clears the `Library.config_file` override, the `default_bib_file`
    setting, and resets the active entry-type/field configuration.
    Mainly useful for tests.
    """
    global _config_file_override, _default_bib_file
    _config_file_override = None
    _default_bib_file = None
    entrytypes.reset_active()


# -- accessors backing the Library class attributes ------------------- #
# (trivial forwarders; see `_LibraryMeta` for what each one backs)
# pylint: disable=missing-function-docstring


def get_verify_types():
    return entrytypes._active.verify_types


def set_verify_types(value):
    entrytypes.set_verify_types(value)


def get_verify_fields():
    return entrytypes._active.verify_fields


def set_verify_fields(value):
    entrytypes.set_verify_fields(value)


def get_config_file():
    return _config_file_override


def set_config_file(value):
    global _config_file_override
    _config_file_override = value


def get_default_bib_file():
    return _default_bib_file
