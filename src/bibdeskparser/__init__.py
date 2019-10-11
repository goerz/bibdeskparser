"""
The :mod:`bibdeskparser` module can parse BibTeX files and write them. The API
is similar to the :mod:`json` module. The parsed data is returned as a simple
:class:`~.BibDatabase` object with the main attribute being
:attr:`~.BibDatabase.entries` representing bibliographic sources such as books
and journal articles.

The following functions provide a quick and basic way to manipulate a BibTeX
file.  More advanced features are also available in this module.
"""
__all__ = [
    'loads',
    'load',
    'dumps',
    'dump',
]

__version__ = '2.0.0-dev'

from . import (
    bibdatabase,
    bibtexexpression,
    bparser,
    bwriter,
    latexenc,
    customization,
)


def loads(bibtex_str, parser=None):
    """
    Load :class:`~.BibDatabase` object from a string

    :param bibtex_str: input BibTeX string to be parsed
    :type bibtex_str: str
    :param parser: custom parser to use (optional)
    :type parser: BibTexParser
    :returns: bibliographic database object
    :rtype: BibDatabase
    """
    if parser is None:
        parser = bparser.BibTexParser()
    return parser.parse(bibtex_str)


def load(bibtex_file, parser=None):
    """
    Load :class:`~.BibDatabase` object from a file

    :param bibtex_file: input file handle to be parsed
    :type bibtex_file: typing.IO
    :param parser: custom parser to use (optional)
    :type parser: BibTexParser
    :returns: bibliographic database object
    :rtype: BibDatabase
    """
    if parser is None:
        parser = bparser.BibTexParser()
    return parser.parse_file(bibtex_file)


def dumps(bib_database, writer=None):
    """
    Dump :class:`~.BibDatabase` object to a BibTeX string

    :param bib_database: bibliographic database object
    :type bib_database: BibDatabase
    :param writer: custom writer to use (optional) (not yet implemented)
    :type writer: BibTexWriter
    :returns: BibTeX string
    :rtype: str
    """
    if writer is None:
        writer = bwriter.BibTexWriter()
    return writer.write(bib_database)


def dump(bib_database, bibtex_file, writer=None):
    """
    Dump :class:`~.BibDatabase` object as a BibTeX text file

    :param bib_database: bibliographic database object
    :type bib_database: BibDatabase
    :param bibtex_file: file to write to
    :type bibtex_file: typing.IO
    :param writer: custom writer to use (optional) (not yet implemented)
    :type writer: BibTexWriter
    """
    if writer is None:
        writer = bwriter.BibTexWriter()
    bibtex_file.write(writer.write(bib_database))
