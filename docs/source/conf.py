import sys, os
import sphinx_rtd_theme

# -- General configuration ----------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
needs_sphinx = '2.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.doctest',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
]

intersphinx_mapping = {'python': ('https://docs.python.org/3.7', None)}

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# General information about the project.
project = 'BibDeskParser'
author = 'Michael Goerz'
copyright = '2019, ' + author

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
import bibdeskparser

version = bibdeskparser.__version__
release = bibdeskparser.__version__

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns = []

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'friendly'

# Warn about *all* references where the target cannot be found
nitpicky = True

# Apply smart quote and dash transforms
smartquotes = True
smartquotes_action = 'qDd'  # quotes, dashes, ellipes


# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.

html_theme = "sphinx_rtd_theme"
html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
html_theme_options = {
    'collapse_navigation': True,
    'display_version': True,
    'navigation_depth': 4,
}


# Path for custom static files
html_static_path = ['_static']

# JavaScript filenames, relative to html_static_path
html_js_files = ["version-menu.js"]

# If true, links to the reST sources are added to the pages.
html_show_sourcelink = False

# If true, "Created using Sphinx" is shown in the HTML footer. Default is True.
# html_show_sphinx = True

# If true, "(C) Copyright ..." is shown in the HTML footer. Default is True.
# html_show_copyright = True

# If true, an OpenSearch description file will be output, and all pages will
# contain a <link> tag referring to it.  The value of this option must be the
# base URL from which the finished HTML is served.
# html_use_opensearch = ''

# This is the file name suffix for HTML files (e.g. ".xhtml").
# html_file_suffix = None

# Output file base name for HTML help builder.
htmlhelp_basename = project + 'doc'


# -- Options for epub output --------------------------------------------------

# (defaults are taken from HTML)


# -- Options for LaTeX output -------------------------------------------------

latex_engin = 'pdflatex'

# LaTeX customization (see https://www.sphinx-doc.org/en/2.0/latex.html)
latex_elements = {}

# Grouping the document tree
latex_documents = [
    (
        'index',  # startdocname
        project + '.tex',  # targetname (name of latex file in output dir)
        '',  # LaTeX document title (use title of startdoc document)
        author,  # author for the LaTeX document
        'manual',  # documentclass
    )
]
