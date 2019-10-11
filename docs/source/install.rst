========================
How to install and test?
========================

How to install?
===============

Requirements
------------

* python **3.6** or newer
* pyparsing **2.0.3** or newer


.. pip
   ---
   
   To install with pip:
   
   .. code-block:: sh
   
       pip install bibdeskparser


Tox
---

The advantage of `Tox <https://pypi.python.org/pypi/tox>`_ is that you can build and test the code against several versions of python.
Of course, you need tox to be installed on your system.
The configuration file is tox.ini, in the root of the project. There, you can change the python versions.

.. code-block:: sh

    tox # and nothing more :)
