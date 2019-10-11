BibDeskParser
=============

.. image:: https://img.shields.io/badge/github-goerz/bibdeskparser-blue.svg
   :alt: Source code on Github
   :target: https://github.com/goerz/bibdeskparser
.. image:: https://img.shields.io/badge/docs-doctr-blue.svg
   :alt: Documentation
   :target: https://goerz.github.io/bibdeskparser
.. image:: https://img.shields.io/travis/goerz/bibdeskparser.svg
   :alt: Travis Continuous Integration
   :target: https://travis-ci.org/goerz/bibdeskparser
.. image:: https://codecov.io/gh/goerz/bibdeskparser/branch/master/graph/badge.svg
   :alt: Codecov
   :target: https://codecov.io/gh/goerz/bibdeskparser
.. image:: https://img.shields.io/badge/License-BSD-green.svg
   :alt: BSD License
   :target: https://opensource.org/licenses/BSD-3-Clause

Python library to parse BibDesk_ files.

This is a fork of https://github.com/sciunto-org/python-bibtexparser


.. contents::


BibDeskParser relies on pyparsing_ and is compatible with Python>=3.6


History and Evolution
---------------------

BibDeskParser is a fork of bibtexparser_ by `François Boulogne`_, modified to work with BibDesk_ database files (which are valid bibtex files with some additional custom data and following slightly different conventions to those assumed by bibtexparser_). Modifications to bibtexparser_ (which was BSD/GPL dual licensed) are provided under a BSD license.

The original source code of bibtexparser_ was part of bibserver from OKFN_. This project is released under the AGPLv3. OKFN_ and the original authors kindly provided the permission to use a subpart of their project (i.e. the bibtex parser) under LGPLv3. Many thanks to them!

The parser evolved to a new core based on pyparsing_.

.. _bibtexparser: https://github.com/sciunto-org/python-bibtexparser
.. _François Boulogne: https://github.com/sciunto
.. _BibDesk: https://bibdesk.sourceforge.io
.. _pyparsing: https://pypi.python.org/pypi/pyparsing
.. _OKFN: http://github.com/okfn/bibserver

