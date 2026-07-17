"""Cleaning and validating abstract text.

Provides {func}`cleaned_abstract`, which converts a raw abstract (LaTeX,
JATS XML, or OSTI/AIP brace markup) to plain unicode *prose* and
validates it with heuristic garble checks, returning `None` if the
result is empty or does not pass validation.

This is the pure-text layer shared by `bibdeskparser.fetch` (to include
a publisher abstract when fetching a new entry) and
`bibdeskparser.abstracts` (to clean each candidate it gathers). It has
no network dependencies; the only third-party dependency is
`pylatexenc`, used to convert math markup to unicode. All abstract text
handled here is plain unicode prose: math markup is converted to
unicode (not preserved as TeX), and stray braces and a trailing
backslash are removed, so a cleaned abstract is always safe as a
brace-delimited BibTeX value.
"""

import html
import re
import unicodedata

from pylatexenc.latex2text import LatexNodes2Text

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = ["cleaned_abstract"]


# --------------------------------------------------------------------- #
# Markup cleaning (LaTeX / JATS / OSTI math -> unicode)
# --------------------------------------------------------------------- #

_L2T = LatexNodes2Text(keep_comments=False, strict_latex_spaces=False)

_SUP = {
    **{str(i): c for i, c in enumerate("⁰¹²³⁴⁵⁶⁷⁸⁹")},
    "+": "⁺",
    "-": "⁻",
    "−": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
    "n": "ⁿ",
    "i": "ⁱ",
}
_SUB = {
    **{str(i): c for i, c in enumerate("₀₁₂₃₄₅₆₇₈₉")},
    "+": "₊",
    "-": "₋",
    "−": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
    "a": "ₐ",
    "e": "ₑ",
    "o": "ₒ",
    "x": "ₓ",
    "h": "ₕ",
    "k": "ₖ",
    "l": "ₗ",
    "m": "ₘ",
    "n": "ₙ",
    "p": "ₚ",
    "s": "ₛ",
    "t": "ₜ",
    "i": "ᵢ",
    "j": "ⱼ",
    "r": "ᵣ",
    "u": "ᵤ",
    "v": "ᵥ",
}

# bare-brace greek/symbol words used by the OSTI/AIP Crossref source
_BRACEWORD = {
    "lambda": "λ",
    "Lambda": "Λ",
    "gamma": "γ",
    "Gamma": "Γ",
    "delta": "δ",
    "Delta": "Δ",
    "sigma": "σ",
    "Sigma": "Σ",
    "beta": "β",
    "alpha": "α",
    "mu": "µ",
    "nu": "ν",
    "pi": "π",
    "Pi": "Π",
    "phi": "φ",
    "Phi": "Φ",
    "psi": "ψ",
    "Psi": "Ψ",
    "chi": "χ",
    "tau": "τ",
    "theta": "θ",
    "Theta": "Θ",
    "omega": "ω",
    "Omega": "Ω",
    "rho": "ρ",
    "kappa": "κ",
    "epsilon": "ε",
    "eta": "η",
    "xi": "ξ",
    "zeta": "ζ",
    "approx": "≈",
    "radical": "√",
    "copyright": "©",
    "times": "×",
    "pm": "±",
    "rightarrow": "→",
    "sim": "∼",
    "infinity": "∞",
}


def _to_script(content, table):
    """Map `content` through `table` if *every* character maps."""
    content = content.strip()
    if content and all(c in table for c in content):
        return "".join(table[c] for c in content)
    return None


_SUPRUN = "".join(re.escape(c) for c in _SUP)
_SUBRUN = "".join(re.escape(c) for c in _SUB)


def _scripts(s):
    """Convert `^{...}`/`_{...}`/`^x`/`_x` to unicode super/subscripts.

    Fully mappable runs become unicode; anything else is mapped
    char-by-char at the end (e.g. `-1/2` -> `⁻¹/²`).
    """
    sup = lambda m: _to_script(m.group(1), _SUP)  # noqa: E731
    sub = lambda m: _to_script(m.group(1), _SUB)  # noqa: E731
    # fully-mappable braced runs -> unicode (no caret left behind)
    s = re.sub(r"\^\{([" + _SUPRUN + r"]+)\}", sup, s)
    s = re.sub(r"_\{([" + _SUBRUN + r"]+)\}", sub, s)
    # digit followed by a braced number = implicit superscript:
    # 10{4} -> 10⁴
    s = re.sub(r"(?<=\d)\{(\d+)\}", sup, s)
    # unbraced mappable runs / singles
    s = re.sub(r"\^([" + _SUPRUN + r"]+)", sup, s)
    s = re.sub(r"_([" + _SUBRUN + r"]+)", sub, s)
    s = re.sub(r"\^(\S)", lambda m: _SUP.get(m.group(1), "^" + m.group(1)), s)
    s = re.sub(r"_(\w)", lambda m: _SUB.get(m.group(1), "_" + m.group(1)), s)
    # leftover braced scripts: map char-by-char
    s = re.sub(
        r"\^\{([^{}]*)\}",
        lambda m: "".join(_SUP.get(c, c) for c in m.group(1)),
        s,
    )
    s = re.sub(
        r"_\{([^{}]*)\}",
        lambda m: "".join(_SUB.get(c, c) for c in m.group(1)),
        s,
    )
    return s


# Springer deposits each formula twice (unicode + ascii fallback);
# used to drop the ascii duplicate, e.g. "⁴⁰ 40Ca" -> "⁴⁰Ca".
_PLAIN_SUP = {c: str(i) for i, c in enumerate("⁰¹²³⁴⁵⁶⁷⁸⁹")}

# pylatexenc treats % # & ~ as TeX specials (comment, parameter,
# alignment tab, nbsp), but in deposited abstracts they are literal
# text; an unprotected "%" silently truncates everything after it.
# Protect them with private-use sentinels around the pylatexenc call.
_PROTECTED = {
    "%": "\ue000",
    "#": "\ue001",
    "&": "\ue002",
    "~": "\ue003",
}

# Space variants, unicode hyphens, and pdftotext glyph misreads.
_GLYPH_FIXES = str.maketrans(
    {
        "\u2002": " ",  # en space
        "\u2005": " ",  # four-per-em space
        "\u2008": " ",  # punctuation space
        "\u2009": " ",  # thin space
        "\u00a0": " ",  # no-break space
        "\u2003": " ",  # em space
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "⌳": "Λ",  # "slope", pdftotext misread of Lambda
        "\uf0a0": "",  # private-use glyphs from broken PDF fonts
        "⍀": "",  # APL backslash bar
        "⌬": "",  # benzene ring
    }
)


def _clean_markup(s):
    """Convert LaTeX / JATS / OSTI math markup in `s` to clean unicode.

    Also strips *all* braces and backslashes (the result is plain
    prose, safe as a brace-delimited BibTeX value) and trailing
    publisher copyright boilerplate.
    """
    if not s:
        return s
    # --- Springer wraps each formula in a full LaTeX document -------- #
    s = re.sub(r"\\documentclass.*?\\begin\{document\}", " ", s, flags=re.S)
    s = s.replace(r"\end{document}", " ")
    s = re.sub(r"\\usepackage(\[[^\]]*\])?\{[^}]*\}", " ", s)
    s = re.sub(r"\\setlength\{[^}]*\}\{[^}]*\}", " ", s)
    # --- OSTI/AIP brace markup (not real LaTeX) ---------------------- #
    s = re.sub(
        r"\{sup\s+([^}]*)\}",
        lambda m: _to_script(m.group(1), _SUP) or "^(" + m.group(1) + ")",
        s,
    )
    s = re.sub(
        r"\{sub\s+([^}]*)\}",
        lambda m: _to_script(m.group(1), _SUB) or "_(" + m.group(1) + ")",
        s,
    )
    s = re.sub(r"\{(?:ital|em|bf|it)\s+([^}]*)\}", r"\1", s)
    s = re.sub(
        r"\{(" + "|".join(_BRACEWORD) + r")\}",
        lambda m: _BRACEWORD[m.group(1)],
        s,
    )
    # --- unwrap \ensuremath / cosmetic spacing macros ----------------- #
    for _ in range(4):
        new = re.sub(r"\\ensuremath\{((?:[^{}]|\{[^{}]*\})*)\}", r"\1", s)
        if new == s:
            break
        s = new
    s = re.sub(
        r"\\(?:phantom|rule|hspace|vspace)\{[^{}]*\}(\{[^{}]*\})?", " ", s
    )
    s = re.sub(r"\\,|\\;|\\:|\\!|\\ ", " ", s)
    s = s.replace("$$", " ").replace("{}", "")
    # unicode super/subscripts *before* pylatexenc strips the braces
    # (it turns ^{43} into ^43, after which only "4" would convert)
    s = _scripts(s)
    # --- pylatexenc for greek, operators, accents, \mathrm, etc. ------ #
    # Resolve HTML entities (&lt; etc.) first, *then* protect the TeX
    # specials, so entities cannot re-introduce unprotected specials.
    s = html.unescape(s)
    for char, sentinel in _PROTECTED.items():
        s = s.replace(char, sentinel)
    try:
        s = _L2T.latex_to_text(s)
    # pylint: disable-next=broad-except
    except Exception:  # malformed TeX: keep the un-converted text
        pass
    for char, sentinel in _PROTECTED.items():
        s = s.replace(sentinel, char)
    s = _scripts(s)  # second pass for scripts produced by pylatexenc
    s = s.replace("\n", " ")
    # drop the ascii duplicate of a formula Springer deposits twice
    s = re.sub(
        r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s+(\d+)",
        lambda m: (
            m.group(1)
            if "".join(_PLAIN_SUP[c] for c in m.group(1)) == m.group(2)
            else m.group(0)
        ),
        s,
    )
    s = re.sub(r"([⁺⁻])\s*([+\-])", r"\1", s)
    # --- residue cleanup ---------------------------------------------- #
    s = html.unescape(s)
    s = s.replace("$", "").replace("\u200b", "")
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\\[A-Za-z]+", " ", s)  # any leftover latex command
    s = s.replace("\\", "")
    s = s.replace("�", "")  # replacement char
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s+([,.;:%])", r"\1", s)
    s = s.translate(_GLYPH_FIXES)
    # strip trailing publisher copyright / boilerplate ("Ó" is a
    # common PDF misread of "©"); in-abstract URLs and citations are
    # legitimate content and must *not* be stripped
    s = re.sub(r"\s*(Crown Copyright\b.*)$", "", s)
    s = re.sub(r"\s*[©Ó]\s*\d{4}\b.*$", "", s)
    s = re.sub(
        r"\s*\(?[cC]\)?\s*\d{4}\s+(Elsevier|The American|Optical|AIP|"
        r"American Institute|IOP|Springer|Wiley|Published by)\b.*$",
        "",
        s,
    )
    s = re.sub(r"\s*Published by Elsevier\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s*All rights reserved\.?\s*$", "", s, flags=re.I)
    s = re.sub(r"[ \t]+", " ", s)
    s = unicodedata.normalize("NFC", s).strip()
    return s


_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "ft",
    "ﬆ": "st",
}


def _clean_text(s):
    """Clean a raw abstract candidate to a single line of unicode
    prose: ligatures, de-hyphenation, line joining, `_clean_markup`,
    whitespace and unicode normalization."""
    if s is None:
        return None
    for ligature, replacement in _LIGATURES.items():
        s = s.replace(ligature, replacement)
    # de-hyphenate words split across line breaks. This also merges
    # genuinely hyphenated compounds at a line end ("quantum-enhanced"
    # -> "quantumenhanced"); acceptable, improving it needs a
    # dictionary. Online-sourced abstracts have no line breaks.
    s = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", s)
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]*\n[ \t]*", " ", s)
    s = _clean_markup(s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = unicodedata.normalize("NFC", s)
    s = s.strip()
    # strip a leading "Abstract" word if it slipped through
    s = re.sub(r"^(abstract)[.:\s—-]+", "", s, flags=re.I)
    # a brace-delimited BibTeX value may not end in a backslash
    s = s.rstrip("\\").strip()
    return s


def _jats_to_text(jats):
    """Convert a Crossref JATS-XML abstract to plain text (still to be
    cleaned via `_clean_text`)."""
    if not jats:
        return None
    s = jats
    # drop an explicit "Abstract" title
    s = re.sub(r"(?is)<jats:title>\s*abstract\s*</jats:title>", " ", s)
    s = re.sub(r"(?is)<jats:title>.*?</jats:title>", " ", s)
    # unwrap sub/sup (math is rare in deposited abstracts)
    s = re.sub(r"(?is)</?jats:sub>", "", s)
    s = re.sub(r"(?is)</?jats:sup>", "", s)
    # paragraph breaks -> space
    s = re.sub(r"(?is)</jats:p>", " ", s)
    s = re.sub(r"(?is)<jats:p[^>]*>", " ", s)
    # strip all remaining tags (jats:italic, jats:bold, etc.)
    s = re.sub(r"(?is)<[^>]+>", "", s)
    s = html.unescape(s)
    return s


# --------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------- #

_WORD_RE = re.compile(r"[A-Za-z]{2,}")

_COMMON_WORDS = frozenset(
    "the of and to in a is for that with we are this as on by an be "
    "from which can using our results show these such at it".split()
)

# IOP open-access watermarks get interleaved into the PDF text and can
# pass naive validation; reject them so the entry falls through to the
# clean online source.
_WATERMARK = re.compile(
    r"(?i)any further distribution of|maintain attribution to|"
    r"original content from this work|content from this work may be used"
)


def _validate(s):
    """Heuristic garble/format checks; returns `(ok, reason)`."""
    if not s:
        return False, "empty"
    if _WATERMARK.search(s):
        return False, "watermark"
    n = len(s)
    if n < 150:
        return False, f"too-short({n})"
    words = s.split()
    if len(words) > 520:
        return False, f"too-long({len(words)}w)"
    if n > 4000:
        return False, f"too-long-chars({n})"
    # replacement / control chars
    bad = sum(1 for c in s if c == "�" or (ord(c) < 32 and c != "\t"))
    if bad > 2:
        return False, f"control-chars({bad})"
    # must contain enough real words
    realwords = _WORD_RE.findall(s.lower())
    if len(realwords) < 30:
        return False, f"few-words({len(realwords)})"
    # English prose sanity: some common stopwords present
    if len(_COMMON_WORDS.intersection(realwords)) < 4:
        return False, "not-prose"
    # excessive single-letter tokens (broken math), excluding a/I
    singles = [w for w in words if len(w) == 1 and w not in "aAIi"]
    if len(singles) > max(8, 0.18 * len(words)):
        return False, f"too-many-singletons({len(singles)})"
    # ratio of non-alpha-ish characters
    alpha = sum(c.isalpha() or c.isspace() for c in s)
    if alpha / n < 0.72:
        return False, f"low-alpha-ratio({alpha / n:.2f})"
    # OCR digit-substitution garble: "6eld", "modi6cation" (a digit
    # glued inside a lowercase run). Scientific tokens like H2, CO2,
    # T1 are digit-after-letter at a word END, which this avoids.
    garble = len(re.findall(r"\d[a-z]{3,}", s)) + len(
        re.findall(r"[a-z]\d[a-z]", s)
    )
    if garble >= 2:
        return False, f"ocr-garble({garble})"
    return True, "ok"


def _tokens(s):
    return set(_WORD_RE.findall((s or "").lower()))


def _overlap(a, b):
    """Token overlap of two texts, in `[0, 1]`."""
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def cleaned_abstract(text, *, jats=False):
    """Clean the raw abstract `text` (JATS XML with `jats=True`) to
    plain unicode prose; `None` if `text` is empty or the cleaned
    result does not pass validation."""
    if not text:
        return None
    if jats:
        text = _jats_to_text(text)
    text = _clean_text(text)
    if not text:
        return None
    ok, _reason = _validate(text)
    return text if ok else None
