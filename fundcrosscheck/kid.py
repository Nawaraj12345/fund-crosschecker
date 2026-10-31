"""Extract the figures from an investment trust's KID (Story 2.2).

It reads KIDs with and without a cost table, and every value goes through the
quote check and format checks (checks.py). Still to come, in Story 2.2's order
of work: noting charge figures given outside the cost row; the other name, date
and risk wordings; and the two-ISIN rule. Until then those fields come out as
not_found.
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
    """Story 2.2's ongoing charge steps 1-2: find the cost section and see whether it has a cost table."""
    missing = {name: Field(NOT_FOUND) for name in COST_FIELDS}
    section = _cost_section(pages)
    if not section:
        notes.append("No cost section found.")
        return missing
    if any("Composition of costs" in text for _, text in section):
        return _cost_table(section, pages, notes)

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


# --- reading a cost table (Story 2.2, step 4) -------------------------------------

# A figure in a cost table: a percentage, N/A, or a £ amount.
FIGURE = r"(?<![\w.])(?:\d+(?:\.\d+)?%|N/A|n/a|£\s?[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)? GBP)"
# The rows of the "Composition of costs" table, in capitals as printed, so the
# same words inside a description ("No portfolio transaction costs ...") don't count.
ROW_LABELS = {
    "entry": r"Entry costs",
    "exit": r"Exit costs",
    "transaction": r"Portfolio(?: transaction)?(?: costs)?|Transaction costs",
    "ongoing": r"Other on-?going(?: costs)?|Management fees and other(?: administrative or operating costs)?",
    "performance": r"Performance fees?",
    "carried": r"Carried interests?",
}
ANY_ROW = "|".join(f"(?:{pattern})" for pattern in ROW_LABELS.values())
# The yearly total in the "Costs over time" table, followed by one figure per holding period.
TOTAL_ROW = r"(?i:Annual cost impact(?: \(\*\))?|Impact on return \(RIY\) per year(?: \(%\))?)"
# A charge given in the ongoing row's own description: "The OCF for the year to 31 August 2025 was 1.52%".
DESCRIBED_CHARGE = r"The (OCF|OCR)\b[^%]{0,80}? was (\d+(?:\.\d+)?)%"


def _cost_table(section: list[tuple[int, str]], pages: list[str], notes: list[str]) -> dict[str, Field]:
    """Story 2.2's ongoing charge steps 3-5, plus transaction and total cost, from a cost table.

    A percentage is used as printed. N/A becomes not_found (keeping the row as
    its quote). A £ amount alone becomes not_found with a note, except that a
    percentage in the ongoing row's own description counts (F04).
    """
    fields = {name: Field(NOT_FOUND) for name in COST_FIELDS}
    fields["total_cost_pct"] = _total_cost(section)
    table = _composition(section)

    row = _row(table, "transaction")
    if row:
        page_no, label, figure, quote, _ = row
        fields["transaction_cost_pct"] = _figure_field(figure, page_no, quote, label, notes)

    row = _row(table, "ongoing")
    if row:
        page_no, label, figure, quote, span = row
        described = re.search(DESCRIBED_CHARGE, span) if _is_money(figure) else None
        if described:
            fields["ongoing_charge_pct"] = Field(described.group(2), page_no, described.group(0))
            fields["charge_label"] = Field(described.group(1), page_no, described.group(0))
        else:
            fields["ongoing_charge_pct"] = _figure_field(figure, page_no, quote, label, notes)
            if fields["ongoing_charge_pct"].value != NOT_FOUND:
                fields["charge_label"] = _full_label(label, pages[page_no - 1], page_no, notes)
    return fields


def _composition(section: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The cost section from "Composition of costs" onwards."""
    for i, (page_no, text) in enumerate(section):
        start = text.find("Composition of costs")
        if start >= 0:
            return [(page_no, text[start:])] + section[i + 1:]
    return []


def _row(table: list[tuple[int, str]], kind: str) -> tuple[int, str, str, str, str] | None:
    """Find a row of the composition table: (page, label, figure, quote, row text).

    First a clean row, where the figure comes straight after the label
    ("Other ongoing costs 0.70%"). If there isn't one, the description column
    has been mixed into the row (F04, F12), so take the first figure before the
    next row's label. The quote runs from the label to the figure.
    """
    label = ROW_LABELS[kind]
    for page_no, text in table:
        match = re.search(rf"({label})\s+({FIGURE})", text)
        if match:
            return page_no, match.group(1), match.group(2), match.group(0), _row_text(text, match.start())
    for page_no, text in table:
        for match in re.finditer(label, text):
            span = _row_text(text, match.start())
            figure = re.search(FIGURE, span[match.end() - match.start():])
            if figure:
                end = match.end() - match.start() + figure.end()
                return page_no, match.group(0), figure.group(0), span[:end], span
    return None


def _row_text(text: str, start: int) -> str:
    """From a row's label up to the next row's label."""
    label = re.match(ANY_ROW, text[start:])
    after = start + (label.end() if label else 0)
    following = re.search(ANY_ROW, text[after:])
    return text[start:after + following.start()] if following else text[start:]


def _figure_field(figure: str, page_no: int, quote: str, label: str, notes: list[str]) -> Field:
    if figure.endswith("%"):
        return Field(figure[:-1], page_no, quote)
    if _is_money(figure):
        notes.append(f"{label}: only a £ amount is given ({figure}), so no percentage.")
        return Field(NOT_FOUND)
    return Field(NOT_FOUND, page_no, quote)  # N/A


def _is_money(figure: str) -> bool:
    return figure.startswith("£") or figure.endswith("GBP")


def _full_label(label: str, page: str, page_no: int, notes: list[str]) -> Field:
    """The row label as printed. If it wraps onto the next line ("Other ongoing" then
    "costs" on F09), it's completed only when that line really starts with the rest."""
    if label.endswith("costs"):
        return Field(label, page_no, label)
    lines = [normalise(line) for line in page.splitlines()]
    for i, line in enumerate(lines[:-1]):
        if label in line and lines[i + 1].startswith("costs"):
            quote = line[line.index(label):] + " costs"
            return Field(f"{label} costs", page_no, quote)
    notes.append(f"Couldn't read the whole row label starting {label!r}.")
    return Field(NOT_FOUND)


def _total_cost(section: list[tuple[int, str]]) -> Field:
    """The yearly total cost, from the column for the recommended holding period:
    usually the last one ("Impact on return (RIY) per year 1.0% 1.0% 1.0%")."""
    for page_no, text in section:
        match = re.search(rf"{TOTAL_ROW}((?:\s+(?:\d+(?:\.\d+)?%|N/A|n/a))+)", text)
        if match:
            last = match.group(1).split()[-1]
            if last.endswith("%"):
                return Field(last[:-1], page_no, match.group(0))
            return Field(NOT_FOUND, page_no, match.group(0))
    return Field(NOT_FOUND)


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
