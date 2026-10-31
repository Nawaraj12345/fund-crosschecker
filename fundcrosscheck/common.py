"""Pieces shared by the KID extractor (Story 2.2) and the factsheet extractor (Story 2.1)."""

import re
import unicodedata
from dataclasses import dataclass

NOT_FOUND = "not_found"


@dataclass
class Field:
    """One extracted value and where it came from.

    `value` is NOT_FOUND when the document doesn't show it. `page` (1 = first
    page) and `quote` (the text it was read from) can still be set then, for
    example when a cost row prints N/A.
    """

    value: str
    page: int | None = None
    quote: str | None = None


def normalise(text: str) -> str:
    """Make text comparable, as the quote check in Story 2.2 describes.

    NFKC turns ligatures such as "ﬁ" into "fi"; curly quotes become straight;
    the U+2010 hyphen becomes "-"; runs of whitespace become one space.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "‐": "-"}))
    return re.sub(r"\s+", " ", text).strip()


def isin_is_valid(code: str) -> bool:
    """Check an ISIN's format and check digit.

    Letters become numbers (A=10 ... Z=35), then the Luhn check runs over the
    digits: starting with the rightmost, every second digit is doubled.
    """
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", code):
        return False
    digits = "".join(str(int(char, 36)) for char in code[:-1])
    total = 0
    for position, digit in enumerate(reversed(digits)):
        n = int(digit)
        if position % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(code[-1])
