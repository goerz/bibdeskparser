"""Parser for [BibDesk](https://bibdesk.sourceforge.io) `.bib` files.

This package builds on [bibtexparser](
https://bibtexparser.readthedocs.io/en/main/) to read and write BibTeX
databases as maintained by the BibDesk application.
"""

from importlib.metadata import version

from .entry import Entry, Value
from .library import Library, StaleFileError

__version__ = version("bibdeskparser")

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__all__ = [
    "Library",
    "Entry",
    "Value",
    "StaleFileError",
]
__private__ = []
