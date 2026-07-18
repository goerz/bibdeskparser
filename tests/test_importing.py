"""Tests for `Library.import_bibtex` (the `importing` module)."""

import warnings
from datetime import datetime

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


# -- arXiv preprints ----------------------------------------------------- #


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
    bib = Library()
    (key,) = bib.import_bibtex(ARXIV)
    assert key == "Goerz2205.15044"
    entry = bib[key]
    assert entry["journal"] == ValueString("arXiv:2205.15044")
    assert entry["eprint"] == "2205.15044"
    assert entry["archiveprefix"] == "arXiv"
    assert entry["url"] == "https://doi.org/10.48550/arXiv.2205.15044"


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
