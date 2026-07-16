"""Guard tests for the `Library` and `Entry` class docstrings.

The rendered API page lists class members alphabetically
(`autodoc2_sort_names` in `docs/sources/conf.py`), so the class
docstring is the only place that presents the API in logical order.
It must therefore mention (cross-reference) every public member.
"""

import re

import pytest

from bibdeskparser import Entry, Library


def _public_members(cls):
    """The names defined directly on `cls` that autodoc2 renders."""
    return sorted(name for name in vars(cls) if not name.startswith("_"))


@pytest.mark.parametrize("cls", [Entry, Library])
def test_docstring_mentions_all_public_members(cls):
    """Every public member appears in the class docstring, as
    ``{meth}`name` ``/``{attr}`name` `` or a plain ```name``` /
    ```ClassName.name``` code span."""
    docstring = cls.__doc__
    missing = [
        name
        for name in _public_members(cls)
        if not re.search(rf"`(?:{cls.__name__}\.)?{name}`", docstring)
    ]
    assert not missing, f"{cls.__name__} docstring does not mention: {missing}"
