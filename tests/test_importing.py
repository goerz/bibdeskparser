"""Tests for `Library.import_bibtex` (the `importing` module)."""

import shutil
import warnings
from datetime import datetime
from pathlib import Path

import pytest

import bibdeskparser.config as config
from bibdeskparser import Library, MacroString, ValueString


@pytest.fixture(autouse=True)
def _reset_config(tmp_path, monkeypatch):
    """Reset the process-global configuration around every test, and
    make sure no user-level config file is picked up.

    Note that constructing a `Library` re-loads the configuration, so
    in-process overrides (e.g. `config.active.journal_macros = ...`)
    must be applied *after* `Library(...)`.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config.active.reset()
    yield
    config.active.reset()


ARTICLE = """
@article{PhysRevA.89.032334,
    Author = {Goerz, Michael and Reich, Daniel M.},
    Title = {Optimal control theory for a quantum gate},
    Journal = {Phys. Rev. A},
    Year = {2014},
    Doi = {10.1103/PhysRevA.89.032334},
    Pages = {032334},
    Volume = {89},
}
"""


def _library_with_pra():
    bib = Library()
    bib.strings["pra"] = "Phys. Rev. A"
    return bib


# -- journal macro resolution ------------------------------------------ #


def test_journal_from_library_strings():
    bib = _library_with_pra()
    (key,) = bib.import_bibtex(ARTICLE)
    assert key == "GoerzPRA2014"
    assert bib[key]["journal"] == MacroString("pra")


def test_journal_from_refs_bib_strings():
    """A journal name matching the value of an `@string` macro in a
    library loaded from a `.bib` file resolves to that macro, without
    any `[journal_macros]` configuration."""
    bib = Library("tests/Refs/refs.bib")
    text = ARTICLE.replace("{Phys. Rev. A}", "{New J. Phys.}")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        (key,) = bib.import_bibtex(text)
    assert key == "GoerzNJP2014a"  # "GoerzNJP2014" is taken
    assert bib[key]["journal"] == MacroString("njp")
    assert bib.strings["njp"] == "New J. Phys."


def test_journal_from_config_macro():
    bib = Library()
    config.active.journal_macros = {"pra": ("Phys. Rev. A",)}
    (key,) = bib.import_bibtex(ARTICLE)
    assert key == "GoerzPRA2014"
    assert bib[key]["journal"] == MacroString("pra")
    assert bib.strings["pra"] == "Phys. Rev. A"


def test_journal_from_config_alias_uses_canonical_value():
    bib = Library()
    config.active.journal_macros = {
        "jcp": ("J. Chem. Phys.", "The Journal of Chemical Physics")
    }
    text = ARTICLE.replace("Phys. Rev. A", "The Journal of Chemical Physics")
    (key,) = bib.import_bibtex(text)
    assert key == "GoerzJCP2014"
    assert bib[key]["journal"] == MacroString("jcp")
    assert bib.strings["jcp"] == "J. Chem. Phys."


def test_journal_config_alias_resolves_to_existing_macro():
    bib = _library_with_pra()
    config.active.journal_macros = {"pra": ("Phys. Rev. A", "Phys Rev A")}
    text = ARTICLE.replace("{Phys. Rev. A}", "{Phys Rev A}")
    (key,) = bib.import_bibtex(text)
    assert bib[key]["journal"] == MacroString("pra")
    assert bib.strings["pra"] == "Phys. Rev. A"


def test_journal_new_macro_created_with_warning():
    bib = Library()
    with pytest.warns(UserWarning, match="created new @string macro"):
        (key,) = bib.import_bibtex(
            ARTICLE.replace("{Phys. Rev. A}", "{New J. Phys.}")
        )
    assert key == "GoerzNJP2014"
    assert bib[key]["journal"] == MacroString("njp")
    assert bib.strings["njp"] == "New J. Phys."


def test_journal_new_macro_honors_initials_exception():
    bib = Library()
    config.active.initials = {"journal": {"npj Quantum Inf": "NPJQI"}}
    with pytest.warns(UserWarning, match="created new @string macro"):
        (key,) = bib.import_bibtex(
            ARTICLE.replace("{Phys. Rev. A}", "{npj Quantum Inf}")
        )
    assert key == "GoerzNPJQI2014"
    assert bib[key]["journal"] == MacroString("npjqi")
    assert bib.strings["npjqi"] == "npj Quantum Inf"


def test_journal_macro_name_collision_is_an_error():
    bib = Library()
    bib.strings["njp"] = "Nederlands Juristen Podium"
    with pytest.raises(ValueError, match="already defined"):
        bib.import_bibtex(ARTICLE.replace("{Phys. Rev. A}", "{New J. Phys.}"))
    assert len(bib) == 0


def test_journal_underivable_macro_name_is_an_error():
    bib = Library()
    with pytest.raises(ValueError, match="cannot derive"):
        bib.import_bibtex(ARTICLE.replace("{Phys. Rev. A}", "{2D Materials}"))


def test_journal_config_conflicts_with_existing_macro():
    bib = Library()
    bib.strings["pra"] = "Something Else Entirely"
    config.active.journal_macros = {"pra": ("Phys. Rev. A",)}
    with pytest.raises(ValueError, match="already defined as"):
        bib.import_bibtex(ARTICLE)


def test_bare_journal_macro_reference_from_config():
    bib = Library()
    config.active.journal_macros = {"pra": ("Phys. Rev. A",)}
    (key,) = bib.import_bibtex(ARTICLE.replace("{Phys. Rev. A}", "pra"))
    assert bib[key]["journal"] == MacroString("pra")
    assert bib.strings["pra"] == "Phys. Rev. A"


def test_undefined_macro_is_an_error():
    bib = Library()
    with pytest.raises(ValueError, match="undefined macro 'pra'"):
        bib.import_bibtex(ARTICLE.replace("{Phys. Rev. A}", "pra"))


def test_month_macro_is_not_undefined():
    """A bare `month = jan` is a standard macro, not an undefined
    reference (`month` is dropped for `@article` imports, so use
    `@unpublished`)."""
    bib = Library()
    text = (
        "@unpublished{k1,\n"
        "    Author = {Doe, Jane},\n"
        "    Title = {A Title},\n"
        "    Month = jan,\n"
        "    Year = {2024},\n"
        "}\n"
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["month"] == MacroString("jan")
    assert "jan" not in bib.strings


# -- @string handling --------------------------------------------------- #


def test_snippet_strings_define_referenced_macros():
    bib = Library()
    text = "@string{pra = {Phys. Rev. A}}\n" + ARTICLE.replace(
        "{Phys. Rev. A}", "pra"
    )
    (key,) = bib.import_bibtex(text)
    assert bib.strings["pra"] == "Phys. Rev. A"
    assert bib[key]["journal"] == MacroString("pra")


def test_snippet_strings_unreferenced_not_defined():
    bib = _library_with_pra()
    text = "@string{unused = {Unused Journal}}\n" + ARTICLE
    bib.import_bibtex(text)
    assert "unused" not in bib.strings


def test_snippet_string_identical_redefinition_is_noop():
    bib = _library_with_pra()
    text = "@string{pra = {Phys. Rev. A}}\n" + ARTICLE
    (key,) = bib.import_bibtex(text)
    assert bib[key]["journal"] == MacroString("pra")


def test_snippet_string_conflicting_redefinition_is_an_error():
    bib = _library_with_pra()
    text = "@string{pra = {Physical Review A}}\n" + ARTICLE
    with pytest.raises(ValueError, match="conflicts with the existing"):
        bib.import_bibtex(text)


# -- preprints (pseudo-journals) ----------------------------------------- #


ARXIV = """
@article{2205.15044,
    Author = {Goerz, Michael H. and Carrasco, Sebasti{\\'a}n C.},
    Title = {Quantum optimal control via semi-automatic differentiation},
    Journal = {arXiv:2205.15044},
    Year = {2022},
    Url = {https://doi.org/10.48550/arXiv.2205.15044},
}
"""


def test_arxiv_preprint():
    """A pseudo-journal `@article` is normalized to the canonical
    stored form: `@misc`, with derived `eprint`/`archiveprefix`, and
    the DOI extracted from the doi.org resolver URL."""
    bib = Library()
    (key,) = bib.import_bibtex(ARXIV)
    assert key == "Goerz2205.15044"
    entry = bib[key]
    assert entry.entry_type == "unpublished"
    assert entry["journal"] == ValueString("arXiv:2205.15044")
    assert entry["eprint"] == "2205.15044"
    assert entry["archiveprefix"] == "arXiv"
    assert entry["doi"] == "10.48550/arxiv.2205.15044"
    assert entry.get("url") is None


def test_arxiv_own_export():
    """arXiv's own `@misc` BibTeX export (structured eprint fields,
    no journal) is recognized as preprint-only and lands on the full
    canonical stored form: the pseudo-journal is synthesized, the
    arXiv DOI is derived, the redundant abstract-page `url` is
    dropped, and the preprint citation key applies."""
    bib = Library()
    text = """
    @misc{goerz2022quantumoptimalcontrolsemiautomatic,
        title={Quantum optimal control via semi-automatic differentiation},
        author={Michael H. Goerz and Sebasti{\\'a}n C. Carrasco},
        year={2022},
        eprint={2205.15044},
        archivePrefix={arXiv},
        primaryClass={quant-ph},
        url={https://arxiv.org/abs/2205.15044},
    }
    """
    (key,) = bib.import_bibtex(text)
    assert key == "Goerz2205.15044"
    entry = bib[key]
    assert entry.entry_type == "unpublished"
    assert entry["journal"] == ValueString("arXiv:2205.15044")
    assert entry["eprint"] == "2205.15044"
    assert entry["archiveprefix"] == "arXiv"
    assert entry["primaryclass"] == "quant-ph"
    assert entry["doi"] == "10.48550/arxiv.2205.15044"
    assert entry.get("url") is None


def test_arxiv_doi_derived():
    """An arXiv preprint-only entry without any `url` gets the DOI
    `10.48550/arXiv.<id>` that arXiv assigns to every preprint
    (version suffix stripped, lowercased like every DOI)."""
    bib = Library()
    text = ARXIV.replace(
        "    Url = {https://doi.org/10.48550/arXiv.2205.15044},\n", ""
    ).replace("arXiv:2205.15044}", "arXiv:2205.15044v2}")
    (key,) = bib.import_bibtex(text)
    assert bib[key]["doi"] == "10.48550/arxiv.2205.15044"


def test_derivable_url_dropped_only_with_doi():
    """A `url` that merely restates the archive's page for the
    identifier is dropped when the entry carries a `doi` (the
    canonical link); any other `url` is kept."""
    text = """
    @article{Vecheck2022.09.09.507322,
        Author = {Vecheck, Amy M. and Usselman, Robert J.},
        Title = {Quantum Biology in Cellular Migration},
        Doi = {10.1101/2022.09.09.507322},
        Journal = {bioRxiv:2022.09.09.507322},
        Url = {http://www.biorxiv.org/content/10.1101/2022.09.09.507322},
        Year = {2022},
    }
    """
    bib = Library()
    (key,) = bib.import_bibtex(text)
    assert bib[key].get("url") is None
    bib = Library()
    (key,) = bib.import_bibtex(
        text.replace(
            "Url = {http://www.biorxiv.org/content/10.1101/"
            "2022.09.09.507322}",
            "Url = {https://example.com/preprint}",
        )
    )
    assert bib[key]["url"] == "https://example.com/preprint"


def test_arxiv_version_stripped_from_eprint():
    bib = Library()
    text = ARXIV.replace("arXiv:2205.15044}", "arXiv:2205.15044v2}")
    (key,) = bib.import_bibtex(text)
    assert key == "Goerz2205.15044"
    assert bib[key]["eprint"] == "2205.15044"
    assert bib[key]["journal"] == "arXiv:2205.15044v2"


def test_arxiv_old_style_id():
    bib = Library()
    text = ARXIV.replace("arXiv:2205.15044", "arXiv:quant-ph/0106057")
    (key,) = bib.import_bibtex(text)
    assert key == "Goerzquant-ph.0106057"
    entry = bib[key]
    # a macro-shaped literal (`quant-ph/0106057`) must survive a save
    assert entry["eprint"] == ValueString("quant-ph/0106057")


def test_arxiv_existing_eprint_not_overwritten():
    bib = Library()
    text = ARXIV.replace(
        "Year = {2022},", "Year = {2022},\n    Eprint = {2205.15044v1},"
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["eprint"] == "2205.15044v1"


HAL = """
@article{TuriniciHAL00640217,
    Author = {Turinici, Gabriel},
    Title = {Quantum control},
    Journal = {HAL:hal-00640217},
    Url = {https://hal.science/hal-00640217},
    Year = {2012},
}
"""


def test_hal_preprint():
    bib = Library()
    (key,) = bib.import_bibtex(HAL, keep_keys=True)
    entry = bib[key]
    assert entry.entry_type == "unpublished"
    assert entry["journal"] == ValueString("HAL:hal-00640217")
    assert entry["eprint"] == "hal-00640217"
    assert entry["archiveprefix"] == "HAL"
    # no DOI derivation for HAL, and without a `doi` the deposit's
    # stable URL is the canonical link: it is kept
    assert entry.get("doi") is None
    assert entry["url"] == "https://hal.science/hal-00640217"


def test_biorxiv_preprint():
    bib = Library()
    text = """
    @article{Vecheck2022.09.09.507322,
        Author = {Vecheck, Amy M. and Usselman, Robert J.},
        Title = {Quantum Biology in Cellular Migration},
        Doi = {10.1101/2022.09.09.507322},
        Journal = {bioRxiv:2022.09.09.507322},
        Year = {2022},
    }
    """
    (key,) = bib.import_bibtex(text)
    entry = bib[key]
    assert key == "Vecheck2022.09.09.507322"
    assert entry["journal"] == ValueString("bioRxiv:2022.09.09.507322")
    assert entry["eprint"] == "2022.09.09.507322"
    assert entry["archiveprefix"] == "bioRxiv"


def test_derivable_archive_dropped_preprint():
    """An `archive` field that matches the link base derivable from
    `eprint`/`archiveprefix` is dropped on import (exports regenerate
    it); any other value is kept."""
    bib = Library()
    text = HAL.replace(
        "Year = {2012},",
        "Year = {2012},\n    Archive = {https://hal.science},",
    )
    (key,) = bib.import_bibtex(text, keep_keys=True)
    assert bib[key].get("archive") is None
    bib = Library()
    text = HAL.replace(
        "Year = {2012},",
        "Year = {2012},\n    Archive = {https://hal.archives-ouvertes.fr},",
    )
    (key,) = bib.import_bibtex(text, keep_keys=True)
    assert bib[key]["archive"] == "https://hal.archives-ouvertes.fr"


def test_derivable_archive_dropped_published():
    """The derivable-`archive` dropping also applies to a *published*
    article with a non-arXiv `eprint` (whose full export regenerates
    the field), so export/import round trips stay clean."""
    text = """
    @article{SauvagePRXQ2020,
        Author = {Sauvage, Fr{\\'e}d{\\'e}ric and Mintert, Florian},
        Title = {Optimal Quantum Control with Poor Statistics},
        Journal = {PRX Quantum},
        Volume = {1},
        Pages = {020322},
        Doi = {10.1103/prxquantum.1.020322},
        Eprint = {hal-03612955},
        Archiveprefix = {HAL},
        Archive = {https://hal.science},
        Year = {2020},
    }
    """
    bib = Library()
    with pytest.warns(UserWarning, match="created new @string macro"):
        (key,) = bib.import_bibtex(text, keep_keys=True)
    entry = bib[key]
    assert entry.entry_type == "article"
    assert entry["eprint"] == "hal-03612955"
    assert entry.get("archive") is None


def test_archive_prefix_canonicalized():
    """A recognized archive prefix is normalized to its canonical
    spelling (`hal:` -> `HAL:`); the identifier is untouched."""
    bib = Library()
    text = HAL.replace("HAL:hal-00640217", "hal:hal-00640217v3")
    (key,) = bib.import_bibtex(text, keep_keys=True)
    entry = bib[key]
    assert entry["journal"] == ValueString("HAL:hal-00640217v3")
    assert entry["eprint"] == "hal-00640217"  # version stripped


def test_configured_archive():
    bib = Library()
    config.active.preprint_archives = {
        **config.active.preprint_archives,
        "zenodo": config._Archive("Zenodo", "https://zenodo.org/records/{id}"),
    }
    text = HAL.replace("HAL:hal-00640217", "Zenodo:1234567")
    (key,) = bib.import_bibtex(text, keep_keys=True)
    entry = bib[key]
    assert entry["journal"] == ValueString("Zenodo:1234567")
    assert entry["eprint"] == "1234567"
    assert entry["archiveprefix"] == "Zenodo"


def test_unrecognized_archive_is_an_error():
    bib = Library()
    text = HAL.replace("HAL:hal-00640217", "EarthArXiv:X5129")
    with pytest.raises(ValueError, match="archive 'EarthArXiv' is not"):
        bib.import_bibtex(text)
    assert len(bib) == 0


def test_url_journal_is_an_error():
    """A URL pasted into the `journal` field must not become an
    `@string` macro."""
    bib = Library()
    text = HAL.replace("HAL:hal-00640217", "https://example.com/paper")
    with pytest.raises(ValueError, match="archive 'https' is not"):
        bib.import_bibtex(text)


# -- keep_journals ------------------------------------------------------- #


def test_keep_journals_literal_preserved():
    bib = _library_with_pra()
    text = ARTICLE.replace("{Phys. Rev. A}", "{Physical Review A}")
    (key,) = bib.import_bibtex(text, keep_journals=True)
    assert bib[key]["journal"] == ValueString("Physical Review A")
    assert "physical review a" not in {
        value.lower() for value in bib.strings.values()
    }


def test_keep_journals_macro_reference_preserved():
    bib = _library_with_pra()
    (key,) = bib.import_bibtex(ARTICLE, keep_journals=True)
    # macro matched by value is still a conversion; keep_journals
    # keeps the literal value instead
    assert bib[key]["journal"] == ValueString("Phys. Rev. A")
    text = ARTICLE.replace("{Phys. Rev. A}", "pra").replace(
        "{10.1103/PhysRevA.89.032334}", "{10.1103/other}"
    )
    (key2,) = bib.import_bibtex(text, keep_journals=True)
    assert bib[key2]["journal"] == MacroString("pra")


def test_keep_journals_config_macro_still_planned():
    """A bare macro reference still pulls in its `[journal_macros]`
    definition under `keep_journals` (the reference must resolve)."""
    bib = Library()
    config.active.journal_macros = {"pra": ("Phys. Rev. A",)}
    text = ARTICLE.replace("{Phys. Rev. A}", "pra")
    (key,) = bib.import_bibtex(text, keep_journals=True)
    assert bib[key]["journal"] == MacroString("pra")
    assert bib.strings["pra"] == "Phys. Rev. A"


def test_keep_journals_pseudo_journal_as_is():
    """`keep_journals` skips the prefix canonicalization and the
    `@misc` conversion, but keeps the `eprint`/`archiveprefix`
    derivation and the preprint key."""
    bib = Library()
    text = ARXIV.replace("arXiv:2205.15044", "arxiv:2205.15044")
    (key,) = bib.import_bibtex(text, keep_journals=True)
    entry = bib[key]
    assert key == "Goerz2205.15044"
    assert entry.entry_type == "article"
    assert entry["journal"] == ValueString("arxiv:2205.15044")
    assert entry["eprint"] == "2205.15044"
    assert entry["archiveprefix"] == "arXiv"
    assert entry["url"] == "https://doi.org/10.48550/arXiv.2205.15044"


def test_keep_journals_unrecognized_archive_ok():
    bib = Library()
    text = HAL.replace("HAL:hal-00640217", "EarthArXiv:X5129")
    (key,) = bib.import_bibtex(text, keep_keys=True, keep_journals=True)
    assert bib[key]["journal"] == ValueString("EarthArXiv:X5129")
    assert bib[key].get("eprint") is None


# -- sanitization ------------------------------------------------------- #


def test_doi_normalized():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{10.1103/PhysRevA.89.032334}",
        "{https://doi.org/10.1103/PhysRevA.89.032334}",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["doi"] == "10.1103/physreva.89.032334"


def test_article_page_range_collapsed():
    bib = _library_with_pra()
    text = ARTICLE.replace("{032334}", "{1017--1025}")
    (key,) = bib.import_bibtex(text)
    assert bib[key]["pages"] == "1017"


def test_non_article_page_range_normalized():
    bib = Library()
    text = """
    @incollection{Sola2018,
        Author = {Sola, Ignacio R.},
        Title = {Quantum Control in Multilevel Systems},
        Booktitle = {Advances in Atomic Physics},
        Publisher = {Academic Press},
        Year = {2018},
        Pages = {151–256},
    }
    """
    (key,) = bib.import_bibtex(text)
    assert key == "SolaAAP2018"
    assert bib[key]["pages"] == "151--256"
    assert bib[key]["publisher"] == "Academic Press"


def test_article_junk_fields_dropped():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n"
        "    Month = {mar},\n"
        "    Publisher = {American Physical Society},\n"
        "    Numpages = {12},\n"
        "    Issn = {1050-2947},\n"
        "    Url = {https://link.aps.org/doi/10.1103/PhysRevA.89.032334},",
    )
    (key,) = bib.import_bibtex(text)
    entry = bib[key]
    for field in ("month", "publisher", "numpages", "issn", "url"):
        assert field not in entry
    assert entry["volume"] == "89"


def test_article_url_kept_without_doi():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "    Doi = {10.1103/PhysRevA.89.032334},\n", ""
    ).replace(
        "Volume = {89},",
        "Volume = {89},\n    Url = {https://example.com/paper},",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["url"] == "https://example.com/paper"


def test_title_proper_nouns_protected():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{Optimal control theory for a quantum gate}",
        "{Krotov: A Python implementation of Krotov's method}",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["title"] == (
        "Krotov: A {Python} implementation of {Krotov}'s method"
    )


def test_title_case_title_left_alone():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{Optimal control theory for a quantum gate}",
        "{Selective Bond Dissociation and Rearrangement with Optimally "
        "Tailored Laser Pulses}",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["title"] == (
        "Selective Bond Dissociation and Rearrangement with Optimally "
        "Tailored Laser Pulses"
    )


def test_title_protected_words():
    bib = _library_with_pra()
    config.active.protected_words = ["Rydberg"]
    text = ARTICLE.replace(
        "{Optimal control theory for a quantum gate}",
        "{Optimal control of Rydberg atoms}",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["title"] == "Optimal control of {Rydberg} atoms"


def test_title_already_braced_untouched():
    bib = _library_with_pra()
    config.active.protected_words = ["Rydberg"]
    text = ARTICLE.replace(
        "{Optimal control theory for a quantum gate}",
        "{Optimal control of {Rydberg} atoms with {QuTiP}}",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["title"] == (
        "Optimal control of {Rydberg} atoms with {QuTiP}"
    )


def test_multiline_values_collapsed():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{Optimal control theory for a quantum gate}",
        "{Optimal control theory\n        for a quantum gate}",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key]["title"] == "Optimal control theory for a quantum gate"


def test_tex_accents_decoded():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{Goerz, Michael and Reich, Daniel M.}",
        '{M{\\"u}ller, Matthias and S{\\o}rensen, O. W.}',
    )
    (key,) = bib.import_bibtex(text)
    assert key == "MullerPRA2014"
    assert bib[key]["author"] == "Müller, Matthias and Sørensen, O. W."


def test_fix_uppercase():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{Goerz, Michael and Reich, Daniel M.}",
        "{GOERZ, MICHAEL and REICH, DANIEL M.}",
    ).replace(
        "{Optimal control theory for a quantum gate}",
        "{OPTIMAL CONTROL THEORY FOR A QUANTUM GATE}",
    )
    (key,) = bib.import_bibtex(text, fix_uppercase=True)
    assert key == "GoerzPRA2014"
    entry = bib[key]
    assert entry["author"] == "Goerz, Michael and Reich, Daniel M."
    assert entry["title"] == "Optimal control theory for a quantum gate"


def test_fix_uppercase_preserves_mixed_case():
    # `fix_uppercase` must only down-case truly all-uppercase values;
    # correctly-cased names/titles must be left untouched.
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{Goerz, Michael and Reich, Daniel M.}",
        "{van der Waals, Johannes and McDonald, Ronald}",
    )
    (key,) = bib.import_bibtex(text, fix_uppercase=True)
    entry = bib[key]
    assert entry["author"] == "van der Waals, Johannes and McDonald, Ronald"
    assert entry["title"] == "Optimal control theory for a quantum gate"


# -- duplicate detection ------------------------------------------------ #


def test_duplicate_doi_rejected():
    bib = _library_with_pra()
    bib.import_bibtex(ARTICLE)
    text = ARTICLE.replace("PhysRevA.89.032334,", "OtherKey2014,").replace(
        "{10.1103/PhysRevA.89.032334}", "{10.1103/PHYSREVA.89.032334}"
    )
    with pytest.raises(
        ValueError, match="already in the library as entry 'GoerzPRA2014'"
    ):
        bib.import_bibtex(text)


def test_duplicate_eprint_rejected():
    bib = Library()
    bib.import_bibtex(ARXIV)
    text = ARXIV.replace("2205.15044", "2205.15044v3").replace(
        "@article{2205.15044v3,", "@article{other,"
    )
    with pytest.raises(ValueError, match="already in the library"):
        bib.import_bibtex(text)


def test_duplicate_doi_within_batch_rejected():
    bib = _library_with_pra()
    text = (
        ARTICLE
        + "\n"
        + ARTICLE.replace("PhysRevA.89.032334,", "OtherKey2014,")
    )
    with pytest.raises(ValueError, match="already in the library"):
        bib.import_bibtex(text)
    assert len(bib) == 0


# -- citation keys ------------------------------------------------------ #


def test_unique_suffix_within_batch():
    bib = _library_with_pra()
    other = ARTICLE.replace("PhysRevA.89.032334,", "OtherKey,").replace(
        "{10.1103/PhysRevA.89.032334}", "{10.1103/other.doi}"
    )
    keys = bib.import_bibtex(ARTICLE + "\n" + other)
    assert keys == ["GoerzPRA2014", "GoerzPRA2014a"]


def test_matching_incoming_key_kept():
    bib = _library_with_pra()
    text = ARTICLE.replace("PhysRevA.89.032334,", "GoerzPRA2014,")
    (key,) = bib.import_bibtex(text)
    assert key == "GoerzPRA2014"


def test_keep_keys():
    bib = _library_with_pra()
    (key,) = bib.import_bibtex(ARTICLE, keep_keys=True)
    assert key == "PhysRevA.89.032334"


def test_keep_keys_collision_rejected():
    bib = _library_with_pra()
    bib.import_bibtex(ARTICLE, keep_keys=True)
    text = ARTICLE.replace(
        "{10.1103/PhysRevA.89.032334}", "{10.1103/other.doi}"
    )
    with pytest.raises(ValueError, match="already in the library"):
        bib.import_bibtex(text, keep_keys=True)


def test_configured_auto_key_format():
    bib = _library_with_pra()
    config.active.auto_key.format_spec = "%a1:%Y%u0"
    (key,) = bib.import_bibtex(ARTICLE)
    assert key == "Goerz:2014"


def test_configured_auto_key_missing_type_is_an_error():
    bib = _library_with_pra()
    config.active.auto_key.format_spec = {"book": "%a1%Y%u0"}
    with pytest.raises(ValueError, match="no entry for type 'article'"):
        bib.import_bibtex(ARTICLE)


def test_arxiv_key_ignores_configured_format():
    bib = Library()
    config.active.auto_key.format_spec = "%a1:%Y%u0"
    (key,) = bib.import_bibtex(ARXIV)
    assert key == "Goerz2205.15044"


def test_default_key_for_book():
    bib = Library()
    text = """
    @book{someBookKey,
        Author = {Magnus, Jan R. and Neudecker, Heinz},
        Title = {Matrix Differential Calculus},
        Publisher = {Wiley},
        Year = {2019},
    }
    """
    (key,) = bib.import_bibtex(text)
    assert key == "Magnus2019"


def test_default_key_for_editor_only_book():
    bib = Library()
    text = """
    @book{someBookKey,
        Editor = {Magnus, Jan R.},
        Title = {Matrix Differential Calculus},
        Publisher = {Wiley},
        Year = {2019},
    }
    """
    (key,) = bib.import_bibtex(text)
    assert key == "Magnus2019"


def test_key_for_inproceedings_uses_booktitle():
    bib = Library()
    text = """
    @inproceedings{someKey,
        Author = {Goerz, Michael},
        Title = {A Talk},
        Booktitle = {Proceedings of the European Control Conference},
        Year = {2019},
    }
    """
    (key,) = bib.import_bibtex(text)
    assert key == "GoerzPECC2019"


def test_key_generation_missing_fields_is_an_error():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "    Author = {Goerz, Michael and Reich, Daniel M.},\n", ""
    )
    with pytest.raises(ValueError, match="missing field"):
        bib.import_bibtex(text)


# -- bdsk-* and other special fields ------------------------------------ #


def test_keywords_preserved():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Keywords = {quantum control, gates},",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key].keywords == ("quantum control", "gates")


def test_bdsk_urls_preserved():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Bdsk-Url-1 = {https://example.com/paper},",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key].urls == ("https://example.com/paper",)


def test_date_added_preserved():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Date-Added = {2014-03-25 10:00:00 +0000},",
    )
    this_year = datetime.now().year
    (key,) = bib.import_bibtex(text)
    entry = bib[key]
    assert entry.date_added.year == 2014
    assert entry.date_modified.year >= this_year


def test_invalid_date_added_dropped():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Date-Added = {last Tuesday},",
    )
    this_year = datetime.now().year
    with pytest.warns(UserWarning, match="unparseable date-added"):
        (key,) = bib.import_bibtex(text)
    assert bib[key].date_added.year >= this_year


def test_bdsk_file_attached(tmp_path):
    bibfile = tmp_path / "library.bib"
    bibfile.write_text("", encoding="utf-8")
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4")
    bib = Library(str(bibfile))
    bib.strings["pra"] = "Phys. Rev. A"
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Bdsk-File-1 = {paper.pdf},",
    )
    (key,) = bib.import_bibtex(text)
    assert bib[key].files == ["paper.pdf"]
    bib.save()
    assert "bdsk-file-1" in bibfile.read_text(encoding="utf-8")


def test_bdsk_file_missing_is_an_error(tmp_path):
    bibfile = tmp_path / "library.bib"
    bibfile.write_text("", encoding="utf-8")
    bib = Library(str(bibfile))
    bib.strings["pra"] = "Phys. Rev. A"
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Bdsk-File-1 = {missing.pdf},",
    )
    with pytest.raises(ValueError, match="linked file does not exist"):
        bib.import_bibtex(text)


def test_bdsk_file_without_library_path_is_an_error():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Bdsk-File-1 = {paper.pdf},",
    )
    with pytest.raises(ValueError, match="no file path yet"):
        bib.import_bibtex(text)


def test_bdsk_file_blob_is_an_error(tmp_path):
    bibfile = tmp_path / "library.bib"
    bibfile.write_text("", encoding="utf-8")
    bib = Library(str(bibfile))
    bib.strings["pra"] = "Phys. Rev. A"
    text = ARTICLE.replace(
        "Volume = {89},",
        "Volume = {89},\n    Bdsk-File-1 = {YnBsaXN0MDDUAQIDBAUG},",
    )
    with pytest.raises(ValueError, match="binary attachment data"):
        bib.import_bibtex(text)


# -- validation / error behavior ---------------------------------------- #


def test_empty_text_is_an_error():
    bib = Library()
    with pytest.raises(ValueError, match="no entries found"):
        bib.import_bibtex("")


def test_strings_only_text_is_an_error():
    bib = Library()
    with pytest.raises(ValueError, match="no entries found"):
        bib.import_bibtex("@string{pra = {Phys. Rev. A}}")


def test_unparseable_block_is_an_error():
    bib = _library_with_pra()
    with pytest.raises(ValueError, match="could not parse block"):
        bib.import_bibtex(ARTICLE + "\n@article{broken,\n  title = {x,\n")


def test_invalid_entry_type_is_an_error():
    bib = Library()
    with pytest.raises(ValueError, match="invalid entry type"):
        bib.import_bibtex("@nosuchtype{key,\n    Title = {A Title},\n}")


def test_invalid_author_is_an_error():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "{Goerz, Michael and Reich, Daniel M.}",
        "{Goerz, Michael, Jr, X, Y}",
    )
    with pytest.raises(ValueError, match="invalid author field"):
        bib.import_bibtex(text)


def test_inappropriate_field_warns_but_imports():
    bib = _library_with_pra()
    text = ARTICLE.replace(
        "Volume = {89},", "Volume = {89},\n    Frobnicate = {yes},"
    )
    with pytest.warns(UserWarning, match="not appropriate"):
        (key,) = bib.import_bibtex(text)
    assert bib[key]["frobnicate"] == "yes"


def test_all_problems_reported_at_once():
    """Every problem of the batch is reported in a single error."""
    bib = _library_with_pra()
    bad = (
        ARTICLE.replace("PhysRevA.89.032334,", "Other2014,")
        .replace(
            "{Goerz, Michael and Reich, Daniel M.}",
            "{Goerz, Michael, Jr, X, Y}",
        )
        .replace("{Phys. Rev. A}", "undefinedmacro")
        .replace("{10.1103/PhysRevA.89.032334}", "{10.1103/other.doi}")
    )
    with pytest.raises(ValueError) as exc_info:
        bib.import_bibtex(ARTICLE + "\n" + bad)
    message = str(exc_info.value)
    assert "undefined macro 'undefinedmacro'" in message
    assert "invalid author field" in message
    assert len(bib) == 0


def test_failed_import_leaves_library_unmodified(tmp_path):
    bibfile = tmp_path / "library.bib"
    bib = Library()
    bib.strings["pra"] = "Phys. Rev. A"
    bib.import_bibtex(ARTICLE)
    bib.save(bibfile)
    before = bibfile.read_text(encoding="utf-8")
    bib = Library(str(bibfile))
    # one importable entry, one with an invalid author: nothing of the
    # batch may be committed
    text = (
        ARTICLE.replace("PhysRevA.89.032334,", "New2014,").replace(
            "{10.1103/PhysRevA.89.032334}", "{10.1103/other.doi}"
        )
        + "\n"
        + ARTICLE.replace("PhysRevA.89.032334,", "Bad2014,").replace(
            "{Goerz, Michael and Reich, Daniel M.}", "{Goerz, Michael and}"
        )
    )
    with pytest.raises(ValueError):
        bib.import_bibtex(text)
    assert len(bib) == 1
    assert dict(bib.strings) == {"pra": "Phys. Rev. A"}
    bib.save()
    assert bibfile.read_text(encoding="utf-8") == before


def test_export_import_round_trip(tmp_path):
    """An exported entry imports cleanly into another library."""
    bib = _library_with_pra()
    config.active.protected_words = ["Krotov"]
    text = ARTICLE.replace(
        "{Optimal control theory for a quantum gate}",
        "{Beyond Krotov: a {Python} package}",
    )
    (key,) = bib.import_bibtex(text)
    exported = bib.export(key)
    other = Library()
    config.active.protected_words = ["Krotov"]
    (other_key,) = other.import_bibtex(exported)
    assert other_key == key
    assert dict(other[other_key]) == dict(bib[key])
    assert other.strings["pra"] == "Phys. Rev. A"


def test_comments_ignored():
    bib = _library_with_pra()
    text = "%% Comment line\n@comment{BibDesk Static Groups{...}}\n" + ARTICLE
    (key,) = bib.import_bibtex(text)
    assert key == "GoerzPRA2014"


def test_refs_bib_full_round_trip(tmp_path):
    """Exporting all of `tests/Refs/refs.bib` and importing it into a
    fresh library preserves every `journal` field -- including the
    preprint pseudo-journals (`arXiv:...`, `HAL:...`, `bioRxiv:...`)
    and the macro references."""
    refs_dir = Path(__file__).parent / "Refs"
    work = tmp_path / "Refs"
    shutil.copytree(refs_dir, work)
    src = Library(str(work / "refs.bib"))
    exported = src.export(*src.keys())
    target_file = work / "roundtrip.bib"
    target_file.write_text("", encoding="utf-8")
    dst = Library(str(target_file))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        keys = dst.import_bibtex(exported, keep_keys=True)
    # no pseudo-journal may have been turned into an @string macro
    assert not any(
        "created new @string macro" in str(w.message) for w in caught
    )
    assert set(keys) == set(src.keys())
    for key in src.keys():
        assert dst[key].get("journal") == src[key].get("journal"), key
        # the omitted eprint/archiveprefix of preprint-only entries
        # are re-derived on import (and newly derived for entries
        # that did not have them, e.g. `TuriniciHAL00640217`)
        for field in ("eprint", "archiveprefix"):
            src_value = src[key].get(field)
            if src_value is not None:
                assert dst[key].get(field) == src_value, key
        # the synthesized `archive` link base of the export must not
        # round-trip into the library
        assert dst[key].get("archive") == src[key].get("archive"), key
    assert dict(dst.strings) == dict(src.strings)


def test_article_export_round_trip():
    """A `preprint="article"` export (pseudo-journal + DOI-resolver
    URL) imports back into the canonical stored form, with the `doi`
    recovered from the URL."""
    src = Library()
    (key,) = src.import_bibtex(ARXIV)
    exported = src.export(key, fields="minimal", preprint="article")
    assert "@article{" in exported
    assert "Url = {https://doi.org/10.48550/arxiv.2205.15044}" in exported
    dst = Library()
    (new_key,) = dst.import_bibtex(exported, keep_keys=True)
    entry = dst[new_key]
    assert entry.entry_type == "unpublished"
    assert entry["journal"] == ValueString("arXiv:2205.15044")
    assert entry["eprint"] == "2205.15044"
    assert entry["doi"] == "10.48550/arxiv.2205.15044"
    assert entry.get("url") is None


def test_unpublished_preprint_normalized():
    """An `@unpublished` entry with an eprint is preprint-only: the
    pseudo-journal is synthesized and the status `note` is
    preserved."""
    bib = Library()
    text = """
    @unpublished{wilhelm2020,
        Author = {Wilhelm, Frank K. and Kirchhoff, Susanna},
        Title = {An introduction into optimal control},
        Eprint = {2003.10132},
        Archiveprefix = {arXiv},
        Note = {submitted to Phys. Rev. A},
        Year = {2020},
    }
    """
    (key,) = bib.import_bibtex(text)
    entry = bib[key]
    assert key == "Wilhelm2003.10132"
    assert entry.entry_type == "unpublished"
    assert entry["journal"] == ValueString("arXiv:2003.10132")
    assert entry["note"] == "submitted to Phys. Rev. A"
