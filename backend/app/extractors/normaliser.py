"""
Standalone text normalisation pipeline for TeleMonitor.

Public interface
----------------
normalise(text, transliteration_hook=None) -> str
    Apply the 7-step normalisation pipeline.

This module has no database dependency and may be imported anywhere.
"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Step 2 - zero-width / invisible character pattern
# Covers: U+200B ZERO WIDTH SPACE, U+200C ZWNJ, U+200D ZWJ,
#         U+200E LRM, U+200F RLM, U+00AD SOFT HYPHEN,
#         U+2060 WORD JOINER, U+FEFF BOM/ZWNBSP
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u00ad\u2060\ufeff]")

# Step 3 - look-alike character replacement
# Minimum 24 Cyrillic/Greek->ASCII entries.
CONFUSABLE_MAP: dict[str, str] = {
    # Cyrillic lowercase -> ASCII
    "\u0430": "a",  # a -> a
    "\u0435": "e",  # e -> e
    "\u043e": "o",  # o -> o
    "\u0440": "p",  # r -> p
    "\u0441": "c",  # s -> c
    "\u0445": "x",  # x -> x
    "\u0443": "y",  # y -> y
    # Cyrillic uppercase -> ASCII
    "\u0412": "B",  # V -> B
    "\u041d": "H",  # N -> H
    "\u041a": "K",  # K -> K
    "\u041c": "M",  # M -> M
    "\u0422": "T",  # T -> T
    "\u0410": "A",  # A -> A
    "\u0415": "E",  # E -> E
    "\u041e": "O",  # O -> O
    "\u0420": "P",  # R -> P
    "\u0421": "C",  # S -> C
    "\u0425": "X",  # X -> X
    # Greek -> ASCII
    "\u03b1": "a",  # alpha -> a
    "\u03bf": "o",  # omicron -> o
    "\u03c1": "p",  # rho -> p
    "\u03bd": "v",  # nu -> v
    "\u03b5": "e",  # epsilon -> e
    "\u0391": "A",  # Alpha -> A
    "\u0392": "B",  # Beta -> B
    "\u0395": "E",  # Epsilon -> E
    "\u0396": "Z",  # Zeta -> Z
    "\u0397": "H",  # Eta -> H
    "\u0399": "I",  # Iota -> I
    "\u039a": "K",  # Kappa -> K
    "\u039c": "M",  # Mu -> M
    "\u039d": "N",  # Nu -> N
    "\u039f": "O",  # Omicron -> O
    "\u03a1": "P",  # Rho -> P
    "\u03a4": "T",  # Tau -> T
    "\u03a5": "Y",  # Upsilon -> Y
    "\u03a7": "X",  # Chi -> X
}

# Build translation table once at module load.
_TRANS_TABLE = str.maketrans(CONFUSABLE_MAP)

# Step 5 - repeated-punctuation compression
# Three or more consecutive identical punctuation chars -> two.
_REPEATED_PUNCT_RE = re.compile(r"([!?.,:;@#$%^&*\-_=+|~``])\1{2,}")

# Step 5.5 - bullet separators -> space ("Aadhaar • PAN" == "aadhaar pan")
_BULLET_RE = re.compile(r"[\u2022\u00b7\u2023\u2043\u25aa\u25cf\u2219]")

# Step 6 - repeated-whitespace normalisation
_WHITESPACE_RE = re.compile(r"\s+")


def normalise(text: str, transliteration_hook=None) -> str:
    """
    Apply the 7-step normalisation pipeline to *text*.

    Parameters
    ----------
    text : str
        Raw input string.  Never mutated.
    transliteration_hook : callable[[str], str] | None
        Optional function applied after Step 4 (lowercase).

    Returns
    -------
    str
        Normalised output.

    Pipeline
    --------
    1. Unicode NFC normalisation
    2. Zero-width / invisible character removal
    3. Look-alike character replacement (Cyrillic/Greek -> ASCII)
    4. Lowercase conversion
    5. Repeated-punctuation compression (3+ identical chars -> 2)
    6. Repeated-whitespace normalisation and strip
    7. Hyphen -> space interchange + final strip
    """
    if not isinstance(text, str):
        raise TypeError(f"normalise() requires str, got {type(text).__name__}")

    # Step 1 - NFC
    out = unicodedata.normalize("NFC", text)

    # Step 2 - remove zero-width / invisible characters
    out = _ZERO_WIDTH_RE.sub("", out)

    # Step 3 - look-alike replacement
    out = out.translate(_TRANS_TABLE)

    # Step 4 - lowercase
    out = out.lower()

    # Optional transliteration hook applied immediately after lowercase
    if transliteration_hook is not None:
        out = transliteration_hook(out)

    # Step 5 - compress 3+ repeated punctuation to 2
    out = _REPEATED_PUNCT_RE.sub(r"\1\1", out)

    # Step 5.5 - bullet separators become spaces
    out = _BULLET_RE.sub(" ", out)

    # Step 6 - collapse whitespace runs and strip
    out = _WHITESPACE_RE.sub(" ", out).strip()

    # Step 7 - hyphen -> space (treat "drug-sale" == "drug sale")
    out = out.replace("-", " ")

    # Re-collapse whitespace after Step 7: a hyphen adjacent to a space
    # (e.g. "0- 0") would otherwise produce a double space.
    # Also strip leading/trailing whitespace produced by bare hyphens.
    out = _WHITESPACE_RE.sub(" ", out).strip()

    return out


# Convenience alias used by the classifier and test suite.
normalise_text = normalise

__all__ = ["normalise", "normalise_text", "CONFUSABLE_MAP"]