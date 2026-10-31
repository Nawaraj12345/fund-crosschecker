"""Extract the figures from an investment trust's KID (Story 2.2).

Thin slice: this fully handles F16 (F&C), a KID with no cost table, and every
value goes through the quote check and format checks (checks.py). Still to
come, in Story 2.2's order of work: reading cost tables (ongoing, transaction
and total cost); N/A rows, and noting charge figures given outside the table;
the other name, date and risk wordings; and the two-ISIN rule. Until then those
fields come out as not_found, with a note when a cost table wasn't read.
"""

import re
from datetime import date

from .checks import check_fields
from .common import NOT_FOUND, Field, isin_is_valid, normalise

COST_FIELDS = ("ongoing_charge_pct", "charge_label", "transaction_cost_pct", "total_cost_pct")

# Labels in front of the product name: "Product Name:" (F05), "Name of Product:" (F06), "Name:" (F11, F13).
PRODUCT_LABEL = re.compile(r"^(?:Product Name|Name of Product|Name)\s*:\s*", re.IGNORECASE)
# Every trust here is a company, so a cleanly read name ends like one.
COMPANY_ENDING = re.compile(r"(?:plc|p\.l\.c\.|limited)$", re.IGNORECASE)


def extract(pages: list[str]) -> tuple[dict[str, Field], list[str]]:
    """Return the KID's fields (keyed by answer key column, in its order) and notes."""
    if not pages:
        raise ValueError("the PDF has no pages")
    notes: list[str] = []
    name, share_class = _name_and_share_class(pages[0], notes)
    fields = {
        "fund_name": name,
        "isin": _isin(pages[0]),
        "share_class": share_class,
        **_costs(pages, notes),
        "risk_score": _risk_score(pages),
        "risk_method": _risk_method(pages),
        "doc_date": _doc_date(pages[0], notes),
    }
    check_fields(fields, pages, notes)
    return fields, notes


def _search(pattern: str, pages: list[str], flags: int = re.IGNORECASE) -> tuple[int, re.Match] | None:
    """Find the first match on any page. Pages are normalised first, so the
    match is a quote the quote check can find again."""
    for page_no, text in enumerate(pages, start=1):
        match = re.search(pattern, normalise(text), flags)
        if match:
            return page_no, match
    return None


def _top_of_page1(page1: str) -> str:
    """Page 1 up to "What is this product?": the part with the product's name and codes."""
    text = normalise(page1)
    end = re.search(r"What is this product\?", text, re.IGNORECASE)
    return text[:end.start()] if end else text


def _product_line(page1: str) -> str | None:
    """The first real line after the "Product" heading.

    Repeated headings and short bits of junk are skipped (F11 has "Product",
    "Product", "0B"). KIDs without the heading (F09, F12, F14) return None.
    """
    lines = [line.strip() for line in page1.splitlines()]
    if "Product" not in lines:
        return None
    for line in lines[lines.index("Product") + 1:]:
        if line != "Product" and len(line) >= 4:
            return line
    return None


def _name_and_share_class(page1: str, notes: list[str]) -> tuple[Field, Field]:
    """Name and share class from the product line.

    A label in front ("Product Name:") is dropped, and so is anything from a
    bracket or "ISIN" onwards. A share class can come first ("Ordinary shares
    in ...") or last (", Ordinary Shares" or " - Income Shares"). A name that
    doesn't end like a company name is not used: not_found plus a note.
    """
    line = _product_line(page1)
    if line is None:
        return Field(NOT_FOUND), Field(NOT_FOUND)

    quote = normalise(line)
    text = PRODUCT_LABEL.sub("", quote)
    text = re.split(r"\s+\(|\s+ISIN\b", text)[0].strip()
    share = None
    if match := re.fullmatch(r"(.+? shares) in (.+)", text, re.IGNORECASE):
        share, text = match.group(1), match.group(2)
    elif match := re.fullmatch(r"(.+?)(?:,| -| –)\s+(\w+ shares)", text, re.IGNORECASE):
        text, share = match.group(1), match.group(2)

    if not COMPANY_ENDING.search(text):
        notes.append(f"Product line not understood: {quote}")
        return Field(NOT_FOUND), Field(NOT_FOUND)
    share_class = Field(share, 1, quote) if share else Field(NOT_FOUND)
    return Field(text, 1, quote), share_class


def _isin(page1: str) -> Field:
    """The first 12-character code at the top of page 1 that passes the check digit test.

    The quote includes the label in front of it, if there is one.
    """
    text = _top_of_page1(page1)
    label = r"(?:\b(?:ISIN|Product Code|Identifier)\b:?\s*)?"
    for match in re.finditer(label + r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b", text):
        if isin_is_valid(match.group(1)):
            return Field(match.group(1), 1, match.group(0))
    return Field(NOT_FOUND)


def _cost_section(pages: list[str]) -> list[tuple[int, str]]:
    """The text from "What are the costs?" to the next heading ("How long should
    I hold it ..."), as (page number, text) pieces: the section often carries on
    over the page (F04, F05, F09, F11, F13, F14, F19)."""
    pieces: list[tuple[int, str]] = []
    for page_no, raw in enumerate(pages, start=1):
        text = normalise(raw)
        if not pieces:
            start = re.search(r"What are the costs\?", text, re.IGNORECASE)
            if not start:
                continue
            text = text[start.start():]
        end = re.search(r"How long should I hold", text, re.IGNORECASE)
        if end:
            pieces.append((page_no, text[:end.start()]))
            break
        pieces.append((page_no, text))
    return pieces


def _costs(pages: list[str], notes: list[str]) -> dict[str, Field]:
    """Story 2.2's ongoing charge steps 1-2. For now only the no-cost-table case is read."""
    missing = {name: Field(NOT_FOUND) for name in COST_FIELDS}
    section = _cost_section(pages)
    if not section:
        notes.append("No cost section found.")
        return missing
    if any("Composition of costs" in text for _, text in section):
        notes.append("Cost table not read yet (Story 2.2, step 4): ongoing, transaction "
                     "and total cost left as not_found.")
        return missing

    # No cost table: transaction and total cost are not_found, and the ongoing
    # charge is the one stated in the cost section.
    for page_no, text in section:
        match = re.search(r"latest published (Ongoing Charge)\b[^%]*? was (\d+(?:\.\d+)?)%", text)
        if match:
            notes.append("No cost table: ongoing charge taken from the cost section.")
            quote = match.group(0)
            return missing | {
                "ongoing_charge_pct": Field(match.group(2), page_no, quote),
                "charge_label": Field(match.group(1), page_no, quote),
            }
    notes.append("No cost table, and no stated ongoing charge found.")
    return missing


def _risk_score(pages: list[str]) -> Field:
    """The risk sentence, e.g. "We have classified this product as 4"."""
    found = _search(r"classifie[sd] this product as '?([1-7])\b", pages)
    if not found:
        return Field(NOT_FOUND)
    page_no, match = found
    return Field(match.group(1), page_no, match.group(0))


def _risk_method(pages: list[str]) -> Field:
    """SRI when the KID names it. "SRI" must be in capitals, so "Sri Lanka" doesn't count."""
    found = _search(r"(?i:summary risk indicator)|\bSRI\b", pages, flags=0)
    if not found:
        return Field(NOT_FOUND)
    page_no, match = found
    return Field("SRI", page_no, match.group(0))


def _doc_date(page1: str, notes: list[str]) -> Field:
    """The KID's own date, e.g. "Date of Production: 08/06/2026" (UK day first)."""
    found = _search(r"Date of Production:? (\d{2})/(\d{2})/(\d{4})", [page1])
    if not found:
        return Field(NOT_FOUND)
    _, match = found
    day, month, year = (int(g) for g in match.groups())
    try:
        return Field(date(year, month, day).isoformat(), 1, match.group(0))
    except ValueError:
        notes.append(f"Not a real date: {match.group(0)}")
        return Field(NOT_FOUND)
