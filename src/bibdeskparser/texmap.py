"""BibDesk's TeX <-> Unicode string conversion.

BibDesk converts between TeX markup and Unicode when reading and writing
`.bib` files:

- `detexify`: TeX -> Unicode (BibDesk applies this on *read*, for display)
- `texify`: Unicode -> TeX (BibDesk applies this on *write*, to the `.bib`
  file)

This module replicates that conversion. The tables are transcribed
byte-for-byte from BibDesk's `CharacterConversion.plist`, and the
functions mirror the algorithms in BibDesk's `BDSKConverter.m`, so the
conversion matches BibDesk exactly: for a `.bib` file written by BibDesk,
`detexify` (read) followed by `texify` (write) reproduces the original
file. Characters that BibDesk cannot express in TeX (e.g., `π`, `ℏ`, `₂`)
pass through untouched in both directions.
"""

import unicodedata

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__all__ = []
__private__ = ["detexify", "texify", "skip_texify"]


# Roman to TeX + One-Way Conversions from `CharacterConversion.plist`
# (used by texify; the One-Way entries convert forward only)
_TEXIFY = {
    "¡": "{!'}",
    "§": "{\\S}",
    "©": "{\\copyright}",
    "®": "{\\textregistered}",
    "Á": "{\\'A}",
    "Â": "{\\^A}",
    "Ã": "{\\~A}",
    "Ä": '{\\"A}',
    "Å": "{\\AA}",
    "Æ": "{\\AE}",
    "Ç": "{\\c C}",
    "É": "{\\'E}",
    "Ê": "{\\^E}",
    "Ë": '{\\"E}',
    "Ì": "{\\`I}",
    "Í": "{\\'I}",
    "Î": "{\\^I}",
    "Ï": '{\\"I}',
    "Ó": "{\\'O}",
    "Ô": "{\\^O}",
    "Ö": '{\\"O}',
    "Ø": "{\\O}",
    "Ú": "{\\'U}",
    "Û": "{\\^U}",
    "Ü": '{\\"U}',
    "ß": "{\\ss}",
    "à": "{\\`a}",
    "á": "{\\'a}",
    "â": "{\\^a}",
    "ã": "{\\~a}",
    "ä": '{\\"a}',
    "å": "{\\aa}",
    "æ": "{\\ae}",
    "ç": "{\\c c}",
    "è": "{\\`e}",
    "é": "{\\'e}",
    "ê": "{\\^e}",
    "ë": '{\\"e}',
    "ì": "{\\`\\i}",
    "í": "{\\'\\i}",
    "î": "{\\^\\i}",
    "ï": '{\\"\\i}',
    "ñ": "{\\~n}",
    "ò": "{\\`o}",
    "ó": "{\\'o}",
    "ô": "{\\^o}",
    "õ": "{\\~o}",
    "ö": '{\\"o}',
    "ø": "{\\o}",
    "ù": "{\\`u}",
    "ú": "{\\'u}",
    "û": "{\\^u}",
    "ü": '{\\"u}',
    "ÿ": '{\\"y}',
    "Ā": "{\\=A}",
    "ā": "{\\=a}",
    "ć": "{\\'c}",
    "Č": "{\\v C}",
    "č": "{\\v c}",
    "ě": "{\\v e}",
    "Ī": "{\\=I}",
    "ī": "{\\=\\i}",
    "Ł": "{\\L}",
    "ł": "{\\l}",
    "ő": "{\\H o}",
    "Œ": "{\\OE}",
    "œ": "{\\oe}",
    "ş": "{\\c s}",
    "š": "{\\v s}",
    "Ū": "{\\=U}",
    "ū": "{\\=u}",
    "Ÿ": '{\\"Y}',
    "Ž": "{\\v Z}",
    "ž": "{\\v z}",
    "Ḍ": "{\\d D}",
    "ḍ": "{\\d d}",
    "Ḥ": "{\\d H}",
    "ḥ": "{\\d h}",
    "Ṣ": "{\\d S}",
    "ṣ": "{\\d s}",
    "Ṭ": "{\\d T}",
    "ṭ": "{\\d t}",
    "Ẓ": "{\\d Z}",
    "ẓ": "{\\d z}",
    "…": "{\\ldots}",
    "™": "{\\texttrademark}",
    "\u00a0": " ",
    "\u00ad": "-",
    "°": "$\\,^{\\circ}$",
    "±": "$\\pm$",
    "–": "--",
    "—": "---",
    "‘": "`",
    "’": "'",
    "‛": "`",
    "“": "``",
    "”": "''",
    "‟": "``",
    "•": "*",
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

# TeX to Roman from `CharacterConversion.plist` (used by detexify)
_DETEXIFY = {
    "{!'}": "¡",
    '{\\"A}': "Ä",
    '{\\"E}': "Ë",
    '{\\"I}': "Ï",
    '{\\"O}': "Ö",
    '{\\"U}': "Ü",
    '{\\"Y}': "Ÿ",
    '{\\"\\i}': "ï",
    '{\\"a}': "ä",
    '{\\"e}': "ë",
    '{\\"o}': "ö",
    '{\\"u}': "ü",
    '{\\"y}': "ÿ",
    "{\\'A}": "Á",
    "{\\'E}": "É",
    "{\\'I}": "Í",
    "{\\'O}": "Ó",
    "{\\'U}": "Ú",
    "{\\'\\i}": "í",
    "{\\'a}": "á",
    "{\\'c}": "ć",
    "{\\'e}": "é",
    "{\\'o}": "ó",
    "{\\'u}": "ú",
    "{\\=A}": "Ā",
    "{\\=I}": "Ī",
    "{\\=U}": "Ū",
    "{\\=\\i}": "ī",
    "{\\=a}": "ā",
    "{\\=u}": "ū",
    "{\\AA}": "Å",
    "{\\AE}": "Æ",
    "{\\H o}": "ő",
    "{\\OE}": "Œ",
    "{\\O}": "Ø",
    "{\\S}": "§",
    "{\\^A}": "Â",
    "{\\^E}": "Ê",
    "{\\^I}": "Î",
    "{\\^O}": "Ô",
    "{\\^U}": "Û",
    "{\\^\\i}": "î",
    "{\\^a}": "â",
    "{\\^e}": "ê",
    "{\\^o}": "ô",
    "{\\^u}": "û",
    "{\\`I}": "Ì",
    "{\\`\\i}": "ì",
    "{\\`a}": "à",
    "{\\`e}": "è",
    "{\\`o}": "ò",
    "{\\`u}": "ù",
    "{\\aa}": "å",
    "{\\ae}": "æ",
    "{\\c C}": "Ç",
    "{\\c c}": "ç",
    "{\\c s}": "ş",
    "{\\cc}": "ç",
    "{\\copyright}": "©",
    "{\\d D}": "Ḍ",
    "{\\d H}": "Ḥ",
    "{\\d S}": "Ṣ",
    "{\\d T}": "Ṭ",
    "{\\d Z}": "Ẓ",
    "{\\d d}": "ḍ",
    "{\\d h}": "ḥ",
    "{\\d s}": "ṣ",
    "{\\d t}": "ṭ",
    "{\\d z}": "ẓ",
    "{\\ldots}": "…",
    "{\\L}": "Ł",
    "{\\l}": "ł",
    "{\\oe}": "œ",
    "{\\o}": "ø",
    "{\\ss}": "ß",
    "{\\textregistered}": "®",
    "{\\texttrademark}": "™",
    "{\\v C}": "Č",
    "{\\v Z}": "Ž",
    "{\\v c}": "č",
    "{\\v e}": "ě",
    "{\\v s}": "š",
    "{\\v z}": "ž",
    "{\\~A}": "Ã",
    "{\\~a}": "ã",
    "{\\~n}": "ñ",
    "{\\~o}": "õ",
}

# accent letter/symbol -> combining mark (detexify accent algorithm)
_DETEX_ACCENTS = {
    '"': "\u0308",  # combining diaeresis
    "'": "\u0301",  # combining acute accent
    ".": "\u0307",  # combining dot above
    "=": "\u0304",  # combining macron
    "H": "\u030b",  # combining double acute accent
    "^": "\u0302",  # combining circumflex accent
    "`": "\u0300",  # combining grave accent
    "b": "\u0331",  # combining macron below
    "c": "\u0327",  # combining cedilla
    "d": "\u0323",  # combining dot below
    "k": "\u0328",  # combining ogonek
    "r": "\u030a",  # combining ring above
    "u": "\u0306",  # combining breve
    "v": "\u030c",  # combining caron
    "~": "\u0303",  # combining tilde
}

# combining mark -> accent letter/symbol, with a trailing space
# for letter accents (texify accent algorithm)
_TEX_ACCENTS = {
    "\u0300": "`",  # combining grave accent
    "\u0301": "'",  # combining acute accent
    "\u0302": "^",  # combining circumflex accent
    "\u0303": "~",  # combining tilde
    "\u0304": "=",  # combining macron
    "\u0306": "u ",  # combining breve
    "\u0307": ".",  # combining dot above
    "\u0308": '"',  # combining diaeresis
    "\u030a": "r ",  # combining ring above
    "\u030b": "H ",  # combining double acute accent
    "\u030c": "v ",  # combining caron
    "\u0331": "b ",  # combining macron below
    "\u0323": "d ",  # combining dot below
    "\u0327": "c ",  # combining cedilla
    "\u0328": "k ",  # combining ogonek
}

# BibDesk's finalCharacterSet: the codepoints that texify will
# attempt to convert
# fmt: off
_FINAL = frozenset([
    160, 161, 167, 169, 173, 174, 176, 177, 192, 193, 194, 195, 196, 197,
    198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 209, 210, 211, 212,
    213, 214, 216, 217, 218, 219, 220, 221, 223, 224, 225, 226, 227, 228,
    229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 241, 242, 243,
    244, 245, 246, 248, 249, 250, 251, 252, 253, 255, 256, 257, 258, 259,
    260, 261, 262, 263, 264, 265, 266, 267, 268, 269, 270, 271, 274, 275,
    276, 277, 278, 279, 280, 281, 282, 283, 284, 285, 286, 287, 288, 289,
    290, 291, 292, 293, 296, 297, 298, 299, 300, 301, 302, 303, 304, 308,
    309, 310, 311, 313, 314, 315, 316, 317, 318, 321, 322, 323, 324, 325,
    326, 327, 328, 332, 333, 334, 335, 336, 337, 338, 339, 340, 341, 342,
    343, 344, 345, 346, 347, 348, 349, 350, 351, 352, 353, 354, 355, 356,
    357, 360, 361, 362, 363, 364, 365, 366, 367, 368, 369, 370, 371, 372,
    373, 374, 375, 376, 377, 378, 379, 380, 381, 382, 416, 417, 431, 432,
    461, 462, 463, 464, 465, 466, 467, 468, 469, 470, 471, 472, 473, 474,
    475, 476, 478, 479, 480, 481, 482, 483, 486, 487, 488, 489, 490, 491,
    492, 493, 494, 495, 496, 500, 501, 504, 505, 506, 507, 508, 509, 510,
    511, 512, 513, 514, 515, 516, 517, 518, 519, 520, 521, 522, 523, 524,
    525, 526, 527, 528, 529, 530, 531, 532, 533, 534, 535, 536, 537, 538,
    539, 542, 543, 550, 551, 552, 553, 554, 555, 556, 557, 558, 559, 560,
    561, 562, 563, 7680, 7681, 7682, 7683, 7684, 7685, 7686, 7687, 7688,
    7689, 7690, 7691, 7692, 7693, 7694, 7695, 7696, 7697, 7698, 7699,
    7700, 7701, 7702, 7703, 7704, 7705, 7706, 7707, 7708, 7709, 7710,
    7711, 7712, 7713, 7714, 7715, 7716, 7717, 7718, 7719, 7720, 7721,
    7722, 7723, 7724, 7725, 7726, 7727, 7728, 7729, 7730, 7731, 7732,
    7733, 7734, 7735, 7736, 7737, 7738, 7739, 7740, 7741, 7742, 7743,
    7744, 7745, 7746, 7747, 7748, 7749, 7750, 7751, 7752, 7753, 7754,
    7755, 7756, 7757, 7758, 7759, 7760, 7761, 7762, 7763, 7764, 7765,
    7766, 7767, 7768, 7769, 7770, 7771, 7772, 7773, 7774, 7775, 7776,
    7777, 7778, 7779, 7780, 7781, 7782, 7783, 7784, 7785, 7786, 7787,
    7788, 7789, 7790, 7791, 7792, 7793, 7794, 7795, 7796, 7797, 7798,
    7799, 7800, 7801, 7802, 7803, 7804, 7805, 7806, 7807, 7808, 7809,
    7810, 7811, 7812, 7813, 7814, 7815, 7816, 7817, 7818, 7819, 7820,
    7821, 7822, 7823, 7824, 7825, 7826, 7827, 7828, 7829, 7830, 7831,
    7832, 7833, 7835, 7840, 7841, 7842, 7843, 7844, 7845, 7846, 7847,
    7848, 7849, 7850, 7851, 7852, 7853, 7854, 7855, 7856, 7857, 7858,
    7859, 7860, 7861, 7862, 7863, 7864, 7865, 7866, 7867, 7868, 7869,
    7870, 7871, 7872, 7873, 7874, 7875, 7876, 7877, 7878, 7879, 7880,
    7881, 7882, 7883, 7884, 7885, 7886, 7887, 7888, 7889, 7890, 7891,
    7892, 7893, 7894, 7895, 7896, 7897, 7898, 7899, 7900, 7901, 7902,
    7903, 7904, 7905, 7906, 7907, 7908, 7909, 7910, 7911, 7912, 7913,
    7914, 7915, 7916, 7917, 7918, 7919, 7920, 7921, 7922, 7923, 7924,
    7925, 7926, 7927, 7928, 7929, 8211, 8212, 8216, 8217, 8219, 8220,
    8221, 8223, 8226, 8230, 8482, 64256, 64257, 64258, 64259, 64260
])
# fmt: on

# base letters that may carry a TeX accent
_BASE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _tex_accent_to_char(tmp):
    r"""Convert a `{\<accent><letter>}` token to a composed character.

    Mirrors `convertTeXStringToComposedCharacter()` in BibDesk's
    `BDSKConverter.m`. Returns the single composed Unicode character for
    `tmp`, or `None` if `tmp` is not a valid accent token.
    """
    if len(tmp) < 4 or tmp[0] != "{" or tmp[1] != "\\":
        return None
    accent_ch = tmp[2]
    accent = _DETEX_ACCENTS.get(accent_ch)
    if accent is None:
        return None
    ch = tmp[3]
    if accent_ch.isalpha() and ch not in (" ", "\\"):
        # letter accents (e.g. {\v S}) must be followed by space/backslash
        return None
    letter_start = 4 if ch == " " else 3
    end = tmp.find("}", letter_start)
    if end == -1:
        return None
    character = tmp[letter_start:end]
    if character in ("\\i", "\\j"):
        character = character[1:]  # dotless i/j -> plain i/j
    if len(character) != 1:
        return None
    composed = unicodedata.normalize("NFC", character + accent)
    return composed if len(composed) == 1 else None


def detexify(s):
    r"""Convert TeX markup in `s` to Unicode.

    ```python
    >>> from bibdeskparser.texmap import detexify
    >>> detexify('Universit{\\"a}t T{\\"u}bingen')
    'Universität Tübingen'

    ```

    Mirrors `copyStringByDeTeXifyingString:` in BibDesk's
    `BDSKConverter.m`; BibDesk applies this conversion to every field
    value when reading a `.bib` file.

    # Arguments

    * `s`: The string to convert.

    Only `{\...}` sequences are converted; the function is a no-op
    unless `s` contains `{\`.
    """
    if not s or "{\\" not in s:
        return s
    out = s
    i = out.find("{\\")
    converted = False
    while i != -1:
        close = out.find("}", i + 2)
        if close == -1:
            break
        tmp = out[i : close + 1]
        repl = _DETEXIFY.get(tmp) or _tex_accent_to_char(tmp)
        if repl is not None:
            out = out[:i] + repl + out[close + 1 :]
            converted = True
        # advance one char past the current '{' (matches BibDesk's
        # search reset)
        i = out.find("{\\", i + 1)
    return out if converted else s


def _char_to_tex_accent(ch):
    r"""Convert a composed character to a `{\<accent><letter>}` token.

    Mirrors `convertComposedCharacterToTeX()` in BibDesk's
    `BDSKConverter.m`. Returns the TeX form of the single character `ch`
    (or `ch` itself for a plain base letter), or `None` if `ch` cannot be
    expressed as a TeX accent.
    """
    d = unicodedata.normalize("NFD", ch)
    if len(d) == 0 or d[0] not in _BASE:
        return None
    if len(d) == 1:
        return ch  # base letter, nothing to do
    if len(d) > 2 or d[1] not in _TEX_ACCENTS:
        return None
    accent = _TEX_ACCENTS[d[1]]
    character = d[0]
    if character in ("i", "j") and accent not in ("c ", "d ", "b ", "k "):
        character = "\\" + character  # dotless \i / \j
    return "{\\" + accent + character + "}"


def texify(s):
    r"""Convert Unicode characters in `s` to TeX markup.

    ```python
    >>> from bibdeskparser.texmap import texify
    >>> texify("Universität Tübingen")
    'Universit{\\"a}t T{\\"u}bingen'

    ```

    Mirrors `copyStringByTeXifyingString:` in BibDesk's
    `BDSKConverter.m`; BibDesk applies this conversion to every field
    value when writing a `.bib` file.

    # Arguments

    * `s`: The string to convert.

    The string is first NFC-normalized; only characters whose codepoint
    is in BibDesk's "final character set" are converted, and any other
    character (e.g., `π`, `ℏ`, `₂`) passes through untouched.
    """
    if not s:
        return s
    s = unicodedata.normalize("NFC", s)
    out = []
    changed = False
    for ch in s:
        if ord(ch) in _FINAL:
            repl = _TEXIFY.get(ch)
            if repl is None:
                repl = _char_to_tex_accent(ch)
            if repl is not None and repl != ch:
                out.append(repl)
                changed = True
                continue
        out.append(ch)
    return "".join(out) if changed else s


def skip_texify(key):
    r"""Whether the field `key` is excluded from TeX conversion.

    # Arguments

    * `key`: The field key, e.g. `"url"` or `"bdsk-file-1"`. Matching is
      case-insensitive.

    Returns `True` if the (lowercased) `key` contains `"url"` or starts
    with `"bdsk-file"`. BibDesk does not TeXify URL fields, and
    `bdsk-file` fields hold base64 data. Both are pure ASCII without
    `{\` sequences, so this only matters as a safety guard.
    """
    k = key.lower()
    return "url" in k or k.startswith("bdsk-file")
