"""Extract the figures from an ordinary (open-ended) fund's KIID (Story 2.3).

The five KIIDs here (F01-F03, F07, F08) are the controls for the comparison. They
follow the UCITS layout: a name block with the ISIN, a risk and reward profile, a
charges table with an "Ongoing charges" row, and "This key investor information
is accurate as at ...". The rules come from those five, so their score is a
development score. The ISIN rule, the date pattern and the checks are shared with
the trust KIDs (kid.py, checks.py). A KIID has no transaction or total cost, so
those two are always not_found.
"""

import re

from .checks import check_fields
from .common import NOT_FOUND, Field, isin_is_valid, normalise
from .kid import DATE_AFTER_WORDS, ISIN_SHAPE, LONGEST_NAME, _date_field, _isin, _search

# --- name and share class ----------------------------------------------------------

# A fund's name ends with the word "Fund", sometimes with a short bracketed suffix:
# "iShares UK Equity Index Fund (UK)" (F02). Whatever follows on the line may be the share class.
NAME_AND_REST = re.compile(r"(.+?\bFund(?: \([A-Z]{2,3}\))?)(?:\s+(.+))?")
# An aside after the name: (the "Fund") F01, (the 'Fund') F07, (the "fund") F08.
ASIDE = re.compile(r"""\s*\(the ["']?[Ff]und["']?\),?""")
# An umbrella company in front of the name: "Jupiter Asset Management Series PLC - " (F07).
UMBRELLA = re.compile(r"^.+?\b(?:PLC|plc|ICVC|SICAV|OEIC)\s+[-–]\s+")
# A sentence about the fund, not its name: "The fund is managed by Artemis Fund Managers Limited." (F08).
NOT_A_NAME = re.compile(r"^(?:The|This|A|An)\b", re.IGNORECASE)
# Words that show a text is a share class: "A GBP Accumulation Shares", "Class D Accumulating GBP",
# "I GBP Acc", "I accumulation units, GBP".
CLASS_WORDS = re.compile(r"\b(?:shares?|units?|acc|accumulation|accumulating|inc|income|distribution|class)\b",
                         re.IGNORECASE)
# How far above the ISIN line the name can be (F07's is two lines up).
LINES_ABOVE_ISIN = 3


def _name_and_share_class(page1: str, notes: list[str]) -> tuple[Field, Field]:
    """The fund's name and share class from the name block at the top of page 1.

    The name is on the line nearest above the ISIN that holds one, or on the ISIN
    line itself. The share class is taken from the first of: the rest of the name's
    line (F01, F03), the ISIN line in front of the code (F07), a "Class:" line just
    after the ISIN (F08), or a line starting "Class" just above the name (F02).
    """
    lines = [normalise(line) for line in page1.splitlines()]
    lines = [line for line in lines if line]
    isin_at = next((i for i, line in enumerate(lines)
                    if any(isin_is_valid(code) for code in re.findall(ISIN_SHAPE, line))), None)
    if isin_at is None:
        notes.append("No ISIN on page 1, so the name block wasn't found.")
        return Field(NOT_FOUND), Field(NOT_FOUND)

    for at in range(isin_at, max(isin_at - LINES_ABOVE_ISIN, 0) - 1, -1):
        found = _name_on(lines[at])
        if found:
            break
    else:
        notes.append(f"No fund name found near the ISIN: {lines[isin_at]}")
        return Field(NOT_FOUND), Field(NOT_FOUND)
    name, rest = found
    name_field = Field(name, 1, lines[at])

    if rest:
        return name_field, Field(rest, 1, lines[at])
    before_code = _before_isin(lines[isin_at])
    if CLASS_WORDS.search(before_code):
        return name_field, Field(before_code, 1, lines[isin_at])
    for line in lines[isin_at + 1:isin_at + 3]:
        labelled = re.match(r"(?:Share )?Class\s*:\s*(.+)", line, re.IGNORECASE)
        if labelled:
            return name_field, Field(labelled.group(1), 1, line)
    if at > 0 and re.match(r"Class\b", lines[at - 1]):
        return name_field, Field(lines[at - 1], 1, lines[at - 1])
    notes.append(f"No share class found next to the name: {lines[at]}")
    return name_field, Field(NOT_FOUND)


def _name_on(line: str) -> tuple[str, str | None] | None:
    """(name, rest of the line) if the line holds a fund's name, else None."""
    text = UMBRELLA.sub("", _before_isin(ASIDE.sub("", line)))
    match = NAME_AND_REST.fullmatch(text)
    if not match or NOT_A_NAME.match(text) or len(match.group(1)) > LONGEST_NAME:
        return None
    name, rest = match.group(1), match.group(2)
    if rest and not CLASS_WORDS.search(rest):
        return None  # "... Fund Managers Limited": the word Fund inside something else
    return name, rest


def _before_isin(line: str) -> str:
    """The part of a line in front of its ISIN and any label or bracket: "I GBP Acc" in
    "I GBP Acc (ISIN - IE00BYVJRH94)" (F07)."""
    return re.split(rf"\(?\bISIN\b|{ISIN_SHAPE}", line)[0].strip(" :-(")


# --- ongoing charge ------------------------------------------------------------------

# The row in the charges table: "Ongoing charges 0.20%" (F01), "Ongoing Charges 0.05%**" (F02),
# "Ongoing charges 0.825%" (F08). A capital O and a figure straight after, so the sentence
# "The ongoing charges figure is based on ..." doesn't count.
CHARGE_ROW = r"\b(Ongoing [Cc]harges)\s+(\d+(?:\.\d+)?) ?%"


def _charge(pages: list[str], notes: list[str]) -> dict[str, Field]:
    found = _search(CHARGE_ROW, pages, flags=0)
    if not found:
        notes.append("No ongoing charges row found.")
        return {"ongoing_charge_pct": Field(NOT_FOUND), "charge_label": Field(NOT_FOUND)}
    page_no, match = found
    return {"ongoing_charge_pct": Field(match.group(2), page_no, match.group(0)),
            "charge_label": Field(match.group(1), page_no, match.group(0))}


# --- risk ----------------------------------------------------------------------------

NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7"}
# The sentences that give the fund's own risk category, in order of preference.
RISK_SENTENCES = (
    rf"\b[Ff]und is rated ([1-7]|(?i:{'|'.join(NUMBER_WORDS)}))\b",  # "The Fund is rated 4" (F01), "rated five" (F02)
    r"\bcategori[sz]ed in risk class ([1-7])\b",                # F03
    r"\bFunds in category ([1-7]) have\b",                      # F07, under "The Fund is in this category"
)


def _risk_score(pages: list[str]) -> Field:
    """The fund's risk category from a sentence, or else the number the text layer
    lifts out of the 1-7 scale because it's printed larger (F08)."""
    for pattern in RISK_SENTENCES:
        found = _search(pattern, pages, flags=0)
        if found:
            page_no, match = found
            word = match.group(1).lower()
            return Field(NUMBER_WORDS.get(word, word), page_no, match.group(0))
    return _lifted_risk_number(pages)


def _lifted_risk_number(pages: list[str]) -> Field:
    """A line that is just one number from 1 to 7, followed by a line that starts with
    the other six in order: F08 prints its 5 larger, so the text layer gives "5", then
    "1 2 3 4 6 7". Exactly one number missing from the scale, and that number alone above it."""
    for page_no, page in enumerate(pages, start=1):
        lines = [line.strip() for line in page.splitlines()]
        for line, next_line in zip(lines, lines[1:]):
            if not re.fullmatch(r"[1-7]", line):
                continue
            others = " ".join(str(n) for n in range(1, 8) if str(n) != line)
            if re.match(rf"{others}(?!\s*\d)", next_line):
                return Field(line, page_no, f"{line} {others}")
    return Field(NOT_FOUND)


def _risk_method(pages: list[str]) -> Field:
    """SRRI only when the KIID names it. "Risk and reward indicator" alone doesn't
    (answer key rule of 30 Oct): none of the five names it."""
    found = _search(r"(?i:synthetic risk and reward indicator)|\bSRRI\b", pages, flags=0)
    if not found:
        return Field(NOT_FOUND)
    page_no, match = found
    return Field("SRRI", page_no, match.group(0))


# --- date ----------------------------------------------------------------------------

# "This key investor information is accurate as at 26/06/2026." (F01, F03, F07; page 2),
# "... accurate as at 09 February 2026" (F02), "This key investor information document is
# accurate as at 18 February 2026." (F08, page 1). F08's other dates ("Risk indicator number
# is accurate as at: ...", "Charges are accurate as at: ...") have other words in front.
KIID_DATE = rf"key investor information(?: document)? is accurate as at{DATE_AFTER_WORDS}"


def _doc_date(pages: list[str], notes: list[str]) -> Field:
    """The KIID's own date, on whichever page it's printed (page 2 on four of the five)."""
    return _date_field(_search(KIID_DATE, pages), notes)


def extract(pages: list[str]) -> tuple[dict[str, Field], list[str]]:
    """Return the KIID's fields (keyed by answer key column, in its order) and notes."""
    if not pages:
        raise ValueError("the PDF has no pages")
    notes: list[str] = []
    name, share_class = _name_and_share_class(pages[0], notes)
    fields = {
        "fund_name": name,
        "isin": _isin(pages[0]),
        "share_class": share_class,
        **_charge(pages, notes),
        "transaction_cost_pct": Field(NOT_FOUND),  # a KIID doesn't have one
        "total_cost_pct": Field(NOT_FOUND),        # nor this
        "risk_score": _risk_score(pages),
        "risk_method": _risk_method(pages),
        "doc_date": _doc_date(pages, notes),
    }
    check_fields(fields, pages, notes)
    return fields, notes
