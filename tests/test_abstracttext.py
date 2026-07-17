"""Tests for the `abstracttext` module (abstract text cleaning and
validation)."""

import pytest

import bibdeskparser.abstracttext as abstracttext

# Two *different* valid abstracts (each long enough to validate; token
# overlap between the two is far below the agreement threshold).
TEXT_A = (
    "We show that optimizing a quantum gate for an open quantum "
    "system requires the time evolution of only three states. This "
    "represents a significant reduction in computational resources "
    "compared to the complete basis of Liouville space that is "
    "commonly believed necessary for this task, and we illustrate "
    "the reduction for a controlled phasegate with trapped atoms."
)

TEXT_B = (
    "The measurement of weak magnetic fields with high spatial "
    "resolution is an outstanding problem in the biological and "
    "physical sciences. For example, at the cellular scale it can "
    "provide a window into the dynamics of neural networks, and in "
    "condensed matter physics it is used to probe spin textures in "
    "unconventional superconductors with great precision."
)


# -- markup cleaning ------------------------------------------------------ #


@pytest.mark.parametrize(
    "raw, expected",
    [
        (r"$^{43}\mathrm{Ca}^{+}$", "⁴³Ca⁺"),
        (
            r"$\ensuremath{\sim}{10}^{\ensuremath{-}12}"
            r"{\ensuremath{\tau}}^{\ensuremath{-}1/2}$",
            "∼10⁻¹²τ⁻¹/²",
        ),
        (r"5x10{4}", "5x10⁴"),
        (r"{sup 111}Cd{sup +}", "¹¹¹Cd⁺"),
        (r"T{sub 2}", "T₂"),
        (r"{lambda}-type", "λ-type"),
        (r"Schr\"odinger", "Schrödinger"),
        (r"$3\times$ faster", "3× faster"),
        (r"10^{7}", "10⁷"),
        # Springer deposits each formula twice (unicode + ascii)
        (r"$${}^{40}$$40Ca$${}^{+}$$+", "⁴⁰Ca ⁺"),
        # TeX specials that are literal text in abstracts survive
        (
            "a 100% pure state & more #1 of ~10",
            "a 100% pure state & more #1 of ~10",
        ),
        ("fidelity &gt; 99%", "fidelity > 99%"),
    ],
)
def test_clean_markup(raw, expected):
    assert abstracttext._clean_markup(raw) == expected


@pytest.mark.parametrize(
    "trailer",
    [
        " © 2013 Elsevier B.V. All rights reserved.",
        " Crown Copyright 2013.",
        " (c) 2014 American Institute of Physics.",
        " Ó 2013 Elsevier B.V.",
    ],
)
def test_copyright_trailer_stripped(trailer):
    assert abstracttext._clean_markup("A result." + trailer) == "A result."


def test_in_abstract_url_survives():
    text = "Code at https://github.com/x/y [arXiv:2205.15044]."
    assert abstracttext._clean_markup(text) == text


def test_clean_text():
    raw = "eﬃcient dis-\ncovery of ﬁelds\nacross lines"
    assert (
        abstracttext._clean_text(raw)
        == "efficient discovery of fields across lines"
    )
    assert abstracttext._clean_text("Abstract: We show X.") == "We show X."
    assert (
        abstracttext._clean_text("ends in backslash\\") == "ends in backslash"
    )
    assert abstracttext._clean_text(None) is None


def test_jats_to_text():
    jats = (
        "<jats:title>Abstract</jats:title>"
        "<jats:p>We consider <jats:italic>strong</jats:italic> "
        "driving of a qubit&#8212;beyond RWA.</jats:p>"
    )
    text = abstracttext._jats_to_text(jats)
    assert "We consider strong driving of a qubit—beyond RWA." in text
    assert "<" not in text
    assert abstracttext._jats_to_text(None) is None


# -- validation ------------------------------------------------------------ #


@pytest.mark.parametrize(
    "text, reason",
    [
        ("", "empty"),
        ("Too short.", "too-short"),
        ("Any further distribution of this work " * 10, "watermark"),
        ("word " * 521, "too-long"),
        ("xy zq wv " * 30, "not-prose"),
        (
            TEXT_A.replace("optimizing", "optimi6ing").replace(
                "significant", "signi6cant"
            ),
            "ocr-garble",
        ),
    ],
)
def test_validate_rejects(text, reason):
    ok, why = abstracttext._validate(text)
    assert not ok
    assert why.startswith(reason)


def test_validate_accepts():
    assert abstracttext._validate(TEXT_A) == (True, "ok")
    assert abstracttext._validate(TEXT_B) == (True, "ok")


def test_overlap():
    assert abstracttext._overlap(TEXT_A, TEXT_A) == 1.0
    assert abstracttext._overlap(TEXT_A, TEXT_B) < 0.5
    assert abstracttext._overlap(TEXT_A, "") == 0.0


def test_cleaned_abstract():
    assert abstracttext.cleaned_abstract(TEXT_A) == TEXT_A
    assert abstracttext.cleaned_abstract("too short") is None
    assert abstracttext.cleaned_abstract(None) is None
    jats = f"<jats:p>{TEXT_A}</jats:p>"
    assert abstracttext.cleaned_abstract(jats, jats=True) == TEXT_A
