#!/usr/bin/env python
"""The setup script."""

import sys

from setuptools import find_packages, setup


def get_version(filename):
    """Extract the package version"""
    with open(filename, encoding='utf8') as in_fh:
        for line in in_fh:
            if line.startswith('__version__'):
                return line.split('=')[1].strip()[1:-1]
    raise ValueError("Cannot extract version from %s" % filename)


with open('README.rst', encoding='utf8') as readme_file:
    readme = readme_file.read()


try:
    with open('CHANGELOG', encoding='utf8') as history_file:
        history = history_file.read()
except OSError:
    history = ''
#
# requirements for use
requirements = ['pyparsing>=2.0.3']

dev_requirements = [
    'coverage',
    'flake8',
    'gitpython',
    'isort',
    'pre-commit',
    'pylint',
    'pytest',
    'pytest-cov<=2.6.1',
    'pytest-xdist',
    'sphinx',
    'sphinx-autobuild',
    'sphinx_rtd_theme',
    'twine',
    'wheel',
    'doctr',
]

version = get_version('./src/bibdeskparser/__init__.py')

setup(
    author="Michael Goerz",
    author_email='mail@michaelgoerz.net',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Education',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Topic :: Scientific/Engineering',
        'Topic :: Scientific/Engineering :: Physics',
    ],
    description=(
        "Parser for BibDesk bib files"
    ),
    python_requires='~=3.6',
    install_requires=requirements,
    extras_require={'dev': dev_requirements},
    license="BSD license",
    long_description=readme + '\n\n' + history,
    long_description_content_type='text/x-rst',
    include_package_data=True,
    name='bibdeskparser',
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    url='https://github.com/goerz/bibdeskparser',
    version=version,
    zip_safe=False,
)
