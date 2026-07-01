"""Top-level package for BibDeskParser."""

from importlib.metadata import version

__version__ = version("bibdeskparser")

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__all__ = ['hello_world']
__private__ = []


def hello_world(name="World"):
    """Return a friendly greeting.

    This example function demonstrates how a [MyST] docstring is rendered on
    the auto-generated **API** page. Replace it with your own public API, and
    keep every public name listed in `__all__`.

    Arguments:

    - `name`: the name to greet. Defaults to `"World"`.

    Returns the greeting `"Hello, {name}!"`:

    ```python
    >>> hello_world("Alice")
    'Hello, Alice!'

    ```

    [MyST]: https://mystmd.org/guide/typography
    """
    return f"Hello, {name}!"
