"""Compilation and resolution of `[assets]` path patterns.

An asset class (a name in the `[assets]` table of the configuration)
maps to a path pattern in the format-specifier language, compiled in
the `"asset"` context of {func}`~bibdeskparser.specifiers.compile_format`.
This module turns a pattern into an {class}`_AssetClass` and resolves
it to relative paths; everything filesystem- or library-facing (the
public accessors, the `rekey`/`delete` lifecycle, the `check` audits)
lives in `library.py` and `checks.py`, which call in here with a
rendering environment (`strings`, document info, document name,
initials) supplied by the owning library.

A pattern is split into its `/`-separated components, each compiled
separately, so that per-component questions can be answered: which
components reference entry data (via
{func}`~bibdeskparser.specifiers._references_entry`), and which
component is the *unit* that the rename/remove lifecycle moves or
deletes as a whole -- the deepest component that depends on the entry.
"""

import dataclasses
import glob as _glob_module

from .specifiers import (
    _ENTRY_SPECIFIERS,
    _Literal,
    _references_entry,
    _Spec,
    compile_format,
    render_format,
)

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = []


@dataclasses.dataclass
class _AssetClass:
    """One compiled `[assets]` pattern.

    `name` is the class name (the key in the `[assets]` table),
    `pattern` the raw configured pattern. `is_dir` records the
    trailing-slash marker (the asset is expected to be a directory).
    `components` holds the `/`-separated components of the pattern,
    each compiled in the `"asset"` context. `per_entry` is whether any
    component references entry data; `unit_index` is the index of the
    deepest component that does (`None` for a library-level class):
    the sub-path ending at that component is the *unit* that the
    lifecycle operations move or remove as a whole."""

    name: str
    pattern: str
    is_dir: bool
    components: tuple
    per_entry: bool
    unit_index: int = None  # None for a library-level class


def _compile_asset_pattern(name, pattern):
    """Compile the `[assets]` pattern `pattern` for the class `name`.

    Returns an {class}`_AssetClass`, or `None` for an empty pattern
    (a disabled class). Raises {exc}`ValueError` for a malformed
    pattern: an invalid format string (see
    {func}`~bibdeskparser.specifiers.compile_format`, `"asset"`
    context), an absolute path, or an empty path component."""
    if not pattern:
        return None
    is_dir = pattern.endswith("/")
    text = pattern[:-1] if is_dir else pattern
    # Validate the pattern as a whole first, so that an error in it is
    # reported against the full configured string.
    compile_format(text, context="asset")
    parts = text.split("/")
    if any(part == "" for part in parts):
        raise ValueError(
            f"invalid asset pattern for {name!r}: {pattern!r} must be "
            "a relative path without empty components"
        )
    components = tuple(compile_format(part, context="asset") for part in parts)
    referencing = [
        i for i, fmt in enumerate(components) if _references_entry(fmt)
    ]
    per_entry = bool(referencing)
    unit_index = referencing[-1] if referencing else None
    return _AssetClass(
        name=name,
        pattern=pattern,
        is_dir=is_dir,
        components=components,
        per_entry=per_entry,
        unit_index=unit_index,
    )


def _asset_classes(assets_map):
    """The compiled {class}`_AssetClass` list for `assets_map` (the
    `dict` of raw patterns from the configuration), skipping disabled
    (empty-pattern) classes. The patterns were validated when the
    configuration was loaded, so compiling here cannot fail."""
    classes = []
    for name, pattern in assets_map.items():
        cls = _compile_asset_pattern(name, pattern)
        if cls is not None:
            classes.append(cls)
    return classes


def _unresolved_info(cls, info):
    """Whether any `%i{Key}` specifier in `cls` names a document-info
    key that `info` lacks, or holds empty (matched case-insensitively,
    like the specifier itself). Such a class does not resolve at all:
    an empty value would contribute an empty path component, so a
    database that has not filled the key in has no such asset,
    whether the key is absent or blank."""
    values = {key.lower(): value for key, value in info.items()}
    for fmt in cls.components:
        for token in fmt.tokens:
            if isinstance(token, _Spec) and token.char == "i":
                if not values.get(token.field, ""):
                    return True
    return False


def _render_component(fmt, entry, env, current_key):
    """Render one compiled pattern component for `entry` (`None` for a
    component of a library-level class). `env` is the rendering
    environment provided by the library (`Library._asset_env()`)."""
    return render_format(
        fmt,
        entry,
        strings=env["strings"],
        document_info=env["info"],
        initials=env["initials"],
        current_key=current_key,
        document_name=env["document_name"],
    )


def _resolve_asset(cls, entry, env, *, current_key=None, depth=None):
    """Resolve `cls` to a relative POSIX path (a `str`), or `None` if
    a `%i{Key}` the pattern references is missing from the document
    info or holds empty.

    `entry` is the {class}`~bibdeskparser.Entry` for a per-entry class
    (`None` for a library-level one), `current_key` its citation key
    -- passed explicitly so the lifecycle can render the path an entry
    *would* have under a different key. With `depth` (a component
    index), only the components up to and including `depth` are
    rendered: `depth=cls.unit_index` yields the unit sub-path that the
    lifecycle moves or removes as a whole."""
    if _unresolved_info(cls, env["info"]):
        return None
    components = cls.components
    if depth is not None:
        components = components[: depth + 1]
    return "/".join(
        _render_component(fmt, entry, env, current_key) for fmt in components
    )


def _asset_present(cls, rel, base_dir):
    """Whether the asset of class `cls` exists at the relative path
    `rel` below `base_dir`: as a directory for a directory-valued
    class, as a file for any other."""
    path = base_dir / rel
    return path.is_dir() if cls.is_dir else path.is_file()


def _unit_is_dir(cls):
    """Whether the lifecycle unit of `cls` (the sub-path ending at the
    deepest entry-referencing component) is a directory: it is when
    further components follow it, or when the class itself is
    directory-valued (trailing slash)."""
    return cls.unit_index < len(cls.components) - 1 or cls.is_dir


def _glob_escape(text):
    """`text` with glob metacharacters neutralized (`glob.escape`,
    which wraps them in `[...]`); path separators pass through."""
    return _glob_module.escape(text)


def _orphan_glob(cls, env):
    """The glob pattern matching every possible on-disk unit of `cls`:
    the pattern components up to the unit, with entry-referencing
    specifiers wildcarded as `*` and everything else (literal text,
    `%i`/`%b` values) rendered literally.

    Returns `None` if the class does not resolve (`%i{Key}` missing
    from the document info). Only meaningful for a per-entry class."""
    if _unresolved_info(cls, env["info"]):
        return None
    component_globs = []
    for fmt in cls.components[: cls.unit_index + 1]:
        parts = []
        for token in fmt.tokens:
            if isinstance(token, _Literal):
                parts.append(_glob_escape(token.text))
            elif token.char in _ENTRY_SPECIFIERS:
                parts.append("*")
            else:
                sub = dataclasses.replace(fmt, tokens=[token])
                parts.append(
                    _glob_escape(_render_component(sub, None, env, None))
                )
        component = "".join(parts)
        # collapse runs of `*`: `**` would glob recursively
        while "**" in component:
            component = component.replace("**", "*")
        component_globs.append(component)
    return "/".join(component_globs)
