"""Telling an absent optional-dependency extra from a broken one.

An optional feature reaches its dependencies through an import that may
fail two ways, and the two want opposite treatment. A package the extra
was supposed to install and did not is a one-line instruction: install
the extra. A package that is installed but raises while importing --
most often a compiled dependency built against something that is no
longer there -- is a damaged installation, and the traceback naming the
import that actually failed is the only thing that identifies it.

This module has no dependencies of its own, so the code that raises
{class}`_MissingExtraError` and the code that catches it can both reach
it without either importing the other.
"""

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = []


class _MissingExtraError(ImportError):
    """An optional-dependency extra of the package is not installed.

    Its own type, so that the command line can report it as a line
    naming what to install while every other `ImportError` keeps the
    traceback that identifies a damaged installation.
    """


def _is_missing(exc, module):
    """Whether `exc` reports `module` itself as absent, rather than
    something that failed while `module` was being imported.

    `ImportError.name` is the module Python could not find, so it is
    `"numpy"` when `numpy` is not installed and `"onnxruntime"` when an
    installed `fastembed` cannot load its own backend.
    """
    name = getattr(exc, "name", None)
    return name == module or (name or "").startswith(f"{module}.")
