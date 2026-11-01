"""Extract the figures from an investment trust's KID (Story 2.2).

It reads KIDs with and without a cost table, and every value goes through the
quote check and format checks (checks.py), and the notes record any charge the
KID gives outside its cost row. The name, share class, date and cost wordings
come from the 24 trust KIDs seen so far (the 14 development ones and, after
their one honest run, the 10 unseen ones). Not handled yet: a risk score shown
only in the graphic, product details split over two text columns (F29), and
the two-ISIN rule. Those fields come out as not_found.
"""

import re
from datetime import date

from .checks import MONTHS, check_fields
from .common import NOT_FOUND, Field, isin_is_valid, normalise

COST_FIELDS = ("ongoing_charge_pct", "charge_label", "transaction_cost_pct", "total_cost_pct")

# Labels in front of the product name: "Product Name:" (F05), "Name of Product:" (F06), "Name:" (F11, F13),
# "Name" without a colon (F24) and "Product:" (F28).
PRODUCT_LABEL = re.compile(r"^(?:(?:Product Name|Name of Product|Name)\b\s*:?|Product\s*:)\s*", re.IGNORECASE)
# Every trust here is a company, so a cleanly read name ends like one: plc, p.l.c., Limited,
# Ltd (F28) or Trust (F20), with or without a full stop after it (F26: "PLC.").
COMPANY_ENDING = re.compile(r"(?:plc|p\.l\.c|limited|ltd|trust)\.?$", re.IGNORECASE)
# A longer "name" is a sentence that happens to end like one, not a name.
LONGEST_NAME = 80
# A 12-character code shaped like an ISIN (its check digit is tested separately).
ISIN_SHAPE = r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b"


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
    notes.extend(_charges_elsewhere(pages, fields["ongoing_charge_pct"]))
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


def _product_lines(page1: str) -> list[str]:
    """The product line first, then the lines after it, up to the line with the ISIN.

    The product line is the first real line after the "Product" heading, in any case
    ("PRODUCT" on F27, F28); repeated headings and short bits of junk are skipped (F11
    has "Product", "Product", "0B"). Without the heading (F09, F12, F14), it's the line
    just before the first line with a valid ISIN. Empty if there's neither.
    """
    lines = [line.strip() for line in page1.splitlines()]
    isin_at = next((i for i, line in enumerate(lines)
                    if any(isin_is_valid(code) for code in re.findall(ISIN_SHAPE, line))), len(lines))
    headings = [i for i, line in enumerate(lines) if line.casefold() == "product"]
    if headings:
        after = [line for line in lines[headings[0] + 1:] if line.casefold() != "product" and len(line) >= 4]
        if not after:
            return []
        start = lines.index(after[0], headings[0] + 1)
        return [after[0]] + [line for line in lines[start + 1:isin_at] if len(line) >= 4]
    if 0 < isin_at < len(lines) and len(lines[isin_at - 1]) >= 4:
        return [lines[isin_at - 1]]
    return []


def _name_and_share_class(page1: str, notes: list[str]) -> tuple[Field, Field]:
    """Name and share class from the product line.

    A label in front ("Product Name:") is dropped, and so is anything from a
    bracket or "ISIN" onwards. A share class can come first ("Ordinary shares
    in ..."), last (", Ordinary Shares", " - Income Shares" or just " ORDINARY
    SHARES" after the company ending, F14), straight after a bracket (F23: 'plc
    (the "Fund"), Ordinary Shares'), or alone on one of the next lines before the
    ISIN (F25). A name that doesn't end like a company name, or is too long to be
    one, is not used: not_found plus a note.
    """
    lines = _product_lines(page1)
    if not lines:
        return Field(NOT_FOUND), Field(NOT_FOUND)

    quote = normalise(lines[0])
    text = PRODUCT_LABEL.sub("", quote)
    head = re.split(r"\s+\(|\s+ISIN\b", text)[0].strip()
    after_head = text[len(head):]
    text = head
    share, share_quote = None, quote
    # A share class is one to three words then "shares" ("Ordinary shares", "Class A Ordinary
    # Shares"), so a sentence like "This document is about shares in ..." isn't taken for one.
    if match := re.fullmatch(r"((?:[\w-]+ ){1,3}shares) in (.+)", text, re.IGNORECASE):
        share, text = match.group(1), match.group(2)
    elif match := re.fullmatch(r"(.+?)(?:,| -| –)\s+(\w+ shares)", text, re.IGNORECASE):
        text, share = match.group(1), match.group(2)
    elif match := re.fullmatch(r"(.+?(?:plc|p\.l\.c\.|limited|ltd))\s+(\w+ shares)", text, re.IGNORECASE):
        text, share = match.group(1), match.group(2)
    elif match := re.match(r"\s*\([^)]*\)\s*(?:,| -| –)\s*(\w+ shares)\b", after_head, re.IGNORECASE):
        share = match.group(1)
    else:
        for line in lines[1:3]:
            line = normalise(line)
            if re.fullmatch(r"\(.*\)", line):
                continue  # a bracket on its own line, e.g. ("The Company") on F25
            if re.fullmatch(r"\w+ shares", line, re.IGNORECASE):
                share, share_quote = line, line
            break

    if not COMPANY_ENDING.search(text) or len(text) > LONGEST_NAME:
        notes.append(f"Product line not understood: {quote}")
        return Field(NOT_FOUND), Field(NOT_FOUND)
    share_class = Field(share, 1, share_quote) if share else Field(NOT_FOUND)
    return Field(text, 1, quote), share_class


def _isin(page1: str) -> Field:
    """The first 12-character code at the top of page 1 that passes the check digit test.

    The quote includes the label in front of it, if there is one.
    """
    text = _top_of_page1(page1)
    label = r"(?:\b(?:ISIN|Product Code|Identifier)\b:?\s*)?"
    for match in re.finditer(label + ISIN_SHAPE, text):
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
    if any(re.search(COST_TABLE, text) for _, text in section):
        return _cost_table(section, pages, notes)

    # No cost table: transaction and total cost are not_found, and the ongoing
    # charge is the one stated in the cost section.
    for pattern in NO_TABLE_CHARGES:
        for page_no, text in section:
            match = re.search(pattern, text)
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

# A figure in a cost table: a percentage (sometimes with a space before the %: "0 %" on F27,
# "0.00 %" on F28), N/A, or a £ amount.
FIGURE = r"(?<![\w.])(?:\d+(?:\.\d+)? ?%|N/A|n/a|£\s?[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)? GBP)"
PERCENT = r"\d+(?:\.\d+)? ?%"
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
# A KID has a cost table if it has the "Composition of costs" heading (any case: F28 has
# "Composition of Costs"), or, without the heading (F20), an entry or ongoing row with its figure.
COST_TABLE = (rf"(?i:Composition of costs)|(?:{ROW_LABELS['entry']}|{ROW_LABELS['ongoing']})\s+{FIGURE}")
# The yearly total in the "Costs over time" table, followed by one figure per holding period:
# "Annual cost impact", "Impact on return (RIY) per year", "Impact on return each year" (F24) or
# "Reduction in Yield (RIY) per year" (F28).
TOTAL_ROW = (r"(?i:Annual cost impact(?: \(\*\))?"
             r"|(?:Impact on return|Reduction in Yield)(?: \(RIY\))? (?:per|each) year(?: \(%\))?)")
# With no cost table, the ongoing charge the cost section states: "latest published Ongoing
# Charge ... was 0.74%" (F15-F18), or "Ongoing Charges figure for the year to 31 ... 0.73%" (F26,
# whose description column is mixed in), but not running on into the next charge's line.
NO_TABLE_CHARGES = (
    r"latest published (Ongoing Charge)\b[^%]*? was (\d+(?:\.\d+)?)%",
    r"(Ongoing Charges? figure)\b(?:(?!Ongoing Charge)[^%]){0,120}?(?<![\d.])(\d+(?:\.\d+)?) ?%",
)
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
    """The cost section from "Composition of costs" onwards (any case), or the whole
    section if it has no such heading (F20)."""
    for i, (page_no, text) in enumerate(section):
        start = re.search(r"Composition of costs", text, re.IGNORECASE)
        if start:
            return [(page_no, text[start.start():])] + section[i + 1:]
    return section


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
        return Field(figure[:-1].strip(), page_no, quote)
    if _is_money(figure):
        notes.append(f"{label}: only a £ amount is given ({figure}), so no percentage.")
        return Field(NOT_FOUND)
    return Field(NOT_FOUND, page_no, quote)  # N/A


def _is_money(figure: str) -> bool:
    return figure.startswith("£") or figure.endswith("GBP")


def _full_label(label: str, page: str, page_no: int, notes: list[str]) -> Field:
    """The row label as printed. If it wraps ("Other ongoing" then "costs" on the next
    line, F09), it's completed only when a line really starts with the rest: the next
    line, or failing that the one after (F28 has the figure and description in between).
    The quote then runs over those lines, so it's a piece of the page as printed."""
    if label.endswith("costs"):
        return Field(label, page_no, label)
    lines = [normalise(line) for line in page.splitlines()]
    for gap in (1, 2):
        for i, line in enumerate(lines[:-gap]):
            if label in line and lines[i + gap].startswith("costs"):
                quote = " ".join([line[line.index(label):]] + lines[i + 1:i + gap] + ["costs"])
                return Field(f"{label} costs", page_no, quote)
    notes.append(f"Couldn't read the whole row label starting {label!r}.")
    return Field(NOT_FOUND)


def _total_cost(section: list[tuple[int, str]]) -> Field:
    """The yearly total cost, from the column for the recommended holding period:
    usually the last one ("Impact on return (RIY) per year 1.0% 1.0% 1.0%")."""
    for page_no, text in section:
        match = re.search(rf"{TOTAL_ROW}((?:\s+(?:{PERCENT}|N/A|n/a))+)", text)
        if match:
            last = re.findall(rf"{PERCENT}|N/A|n/a", match.group(1))[-1]
            if last.endswith("%"):
                return Field(last[:-1].strip(), page_no, match.group(0))
            return Field(NOT_FOUND, page_no, match.group(0))
    return Field(NOT_FOUND)


# A charge stated in words: "The OCR for the year to 30 April 2025 was 0.77%" (F06), "the most
# recent figure for 2025 was 0.73%" (F10), "Operating Expense Ratio (exc. indirect fund costs) 1.03%" (F14).
CHARGE_WORDS = (r"(?:OCF|OCR|[Oo]ngoing [Cc]harges?(?: [Ff]igure| [Rr]atio)?|most recent figure"
                r"|Operating Expense Ratio)")
# From the nearest charge word to the figure: the match can't run over another charge word.
STATED_CHARGE = rf"{CHARGE_WORDS}(?:(?!{CHARGE_WORDS})[^%]){{0,160}}?(?<![\d.])(\d+(?:\.\d+)?)%"


def _charges_elsewhere(pages: list[str], ongoing: Field) -> list[str]:
    """Story 2.2's notes: charge figures the KID gives outside the row used for
    the ongoing charge, with their page, for Sprint 3 to explain differences.
    The sentence the ongoing charge came from, and repeats of a figure already
    noted or used, are left out."""
    used_page, used_span = None, None
    if ongoing.value != NOT_FOUND and ongoing.page and ongoing.quote:
        text = normalise(pages[ongoing.page - 1])
        start = text.find(normalise(ongoing.quote))
        if start >= 0:
            used_page, used_span = ongoing.page, (start, start + len(normalise(ongoing.quote)))
    seen = {ongoing.value}
    notes = []
    for page_no, raw in enumerate(pages, start=1):
        for match in re.finditer(STATED_CHARGE, normalise(raw)):
            overlaps_used = (page_no == used_page and match.start() < used_span[1] and used_span[0] < match.end())
            if overlaps_used or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            notes.append(f'Charge given outside the cost row: {match.group(1)}% on page {page_no} ("{match.group(0)}").')
    return notes


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


# The words in front of the KID's own date (case is ignored): "Date of Production" (F09, F15-F18,
# F20), "Date of production of this document" (F13, F28), "... of the KID" (F19), "Date of document
# production" (F11), "Date of Publication" (F12), "Publication Date" (F26), "Document published"
# (F21), "Last Updated On" (F29), "The version date of this KID is" (F10), and "This (Key
# Information) document (KID) is/was dated, produced on, accurate as at, or accurate at its
# production date" (F04-F06, F14, F22-F25, F27). Not "dated" alone: "statement ... dated 19
# September 2024" (F14) is the FCA's date, not the KID's.
DATE_WORDS = (r"Date of (?:document )?production(?: of (?:this document|the KID))?|Date of Publication"
              r"|Publication Date|Document published|Last Updated On|version date of this KID is"
              r"|(?:document|KID)(?: \(KID\))? (?:is |was )?(?:dated|produced on|accurate as at"
              r"|accurate at its production date)")
# The date after them, UK day first: 08/06/2026, 01-04-2025, 05.10.2026 or 8 June 2026. Up to 40
# characters without digits can come in between (F27's columns put "found at http://fgen.com"
# there), and one footnote digit can follow the year (F14: "31 July 20261").
DOC_DATE = (rf"(?:{DATE_WORDS})\D{{0,40}}?(?<!\d)(?:(\d{{1,2}})[/.-](\d{{1,2}})[/.-](\d{{4}})"
            rf"|(\d{{1,2}}) ({'|'.join(MONTHS)}) (\d{{4}}))\d?(?!\d)")


def _doc_date(page1: str, notes: list[str]) -> Field:
    """The KID's own date, from page 1, e.g. "Date of Production: 08/06/2026"."""
    found = _search(DOC_DATE, [page1])
    if not found:
        return Field(NOT_FOUND)
    _, match = found
    if match.group(1):
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        month_names = [name.casefold() for name in MONTHS]
        day, month, year = int(match.group(4)), month_names.index(match.group(5).casefold()) + 1, int(match.group(6))
    try:
        return Field(date(year, month, day).isoformat(), 1, match.group(0))
    except ValueError:
        notes.append(f"Not a real date: {match.group(0)}")
        return Field(NOT_FOUND)
