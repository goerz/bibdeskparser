"""Parser for [BibDesk](https://bibdesk.sourceforge.io) `.bib` files.

This package builds on [bibtexparser](
https://bibtexparser.readthedocs.io/en/main/) to read and write BibTeX
databases as maintained by the BibDesk application.
"""

from importlib.metadata import version

from . import config as _config
from .entry import Entry
from .library import Library, StaleFileError
from .macros import MacroString, ValueString

__version__ = version("bibdeskparser")

# Load any bibdeskparser.toml from the current working directory or the
# XDG location once, at import. Wrapped so that a malformed config file
# can never prevent `import bibdeskparser`; it surfaces as a warning and
# the built-in defaults are used instead. A `Library` re-applies the
# configuration for its own directory when constructed.
try:
    _config.active.load()
# pylint: disable-next=broad-except
except Exception as _exc:  # pragma: no cover - config must not break import
    import warnings as _warnings

    _warnings.warn(f"failed to load bibdeskparser.toml: {_exc}", UserWarning)
    del _warnings

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__all__ = [
    "Library",
    "Entry",
    "ValueString",
    "MacroString",
    "StaleFileError",
]
__private__ = []
