"""Checks every extracted value before it's written (Story 2.2, step 2).

A value that fails a check becomes not_found, with the reason in the notes.
This is what stops a made-up number (from a bug, or later an LLM) reaching
the output.
"""

import re
from datetime import date

from .common import NOT_FOUND, Field, isin_is_valid, normalise

PERCENT_FIELDS = ("ongoing_charge_pct", "transaction_cost_pct", "total_cost_pct")
NUMBER_FIELDS = PERCENT_FIELDS + ("risk_score",)
RISK_METHODS = {"SRI", "SRRI", "other"}
# How each named risk indicator can appear in a quote: its full name, or its short form in capitals.
RISK_NAMES = {
    "SRI": ("summary risk indicator", "SRI"),
    "SRRI": ("synthetic risk and reward indicator", "SRRI"),
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
EARLIEST_DATE = date(2017, 1, 1)


def check_fields(fields: dict[str, Field], pages: list[str], notes: list[str],
                 today: date | None = None) -> None:
    """Format checks, then the quote check, on every value that isn't not_found.

    Changes `fields` in place. If the ongoing charge is removed, its label goes too.
    """
    today = today or date.today()
    page_texts = [normalise(page) for page in pages]
    for name, field in list(fields.items()):
        if field.value == NOT_FOUND:
            continue
        problem = format_problem(name, field.value, today) or quote_problem(name, field, page_texts)
        if problem:
            notes.append(f"{name} {field.value!r} removed: {problem}.")
            fields[name] = Field(NOT_FOUND)

    if "charge_label" in fields and fields.get("ongoing_charge_pct", Field(NOT_FOUND)).value == NOT_FOUND:
        fields["charge_label"] = Field(NOT_FOUND)


def format_problem(name: str, value: str, today: date) -> str | None:
    """What's wrong with the value's format, or None if nothing is."""
    if name == "isin" and not isin_is_valid(value):
        return "not a valid ISIN"
    if name in PERCENT_FIELDS:
        number = to_number(value)
        if number is None or not 0 <= number <= 5:
            return "not a percentage from 0 to 5"
    if name == "risk_score" and value not in {"1", "2", "3", "4", "5", "6", "7"}:
        return "not a whole number from 1 to 7"
    if name == "risk_method" and value not in RISK_METHODS:
        return "not SRI, SRRI or other"
    if name == "doc_date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return "not a YYYY-MM-DD date"
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return "not a real date"
        if not EARLIEST_DATE <= day <= today:
            return f"not between {EARLIEST_DATE} and today"
    if not value.strip():
        return "empty"  # an empty text is in every quote, so it would pass the quote check
    return None


def quote_problem(name: str, field: Field, page_texts: list[str]) -> str | None:
    """Story 2.2's quote check: the quote must be on its page and contain the value.

    `page_texts` must already be normalised. Three exceptions: a date is looked
    for as printed, a risk method by the indicator's name, and a charge label's
    words only have to appear in order (labels can wrap onto a second line).
    """
    if not field.page or not field.quote:
        return "no page or quote"
    if not 1 <= field.page <= len(page_texts):
        return f"page {field.page} doesn't exist"
    quote = normalise(field.quote)
    if quote not in page_texts[field.page - 1]:
        return f"quote not found on page {field.page}"
    if not value_in_quote(name, field.value, quote):
        return "value not in its quote"
    return None


def value_in_quote(name: str, value: str, quote: str) -> bool:
    if name == "doc_date":
        return any(date_in_quote(printed, quote) for printed in printed_dates(value))
    if name == "risk_method":
        if value not in RISK_NAMES:
            return True  # "other": any named scale, so there's no fixed name to look for
        full_name, short_name = RISK_NAMES[value]
        # The short form may carry a footnote number: "SRRI1 4" (F01 factsheet).
        return full_name in quote.lower() or re.search(rf"\b{short_name}\d{{0,2}}\b", quote) is not None
    if name in NUMBER_FIELDS:
        # The number on its own: "0.8" is in "0.8%", but not in "10.8%", "0.85%" or "-0.8%",
        # "1" is not in "1.5%" or "£1,000", and a footnote number stuck to a word isn't a
        # number at all ("1" in "SRRI1 4"). A figure the text layer splits ("1 .03%", F14
        # factsheet) is joined up first.
        joined = re.sub(r"(?<=\d) +(?=\.\d)", "", quote)
        return re.search(rf"(?<![\w.,\-−–]){re.escape(value)}(?!\d|[.,]\d)", joined) is not None
    if name == "charge_label":
        # The label's words must appear in the quote in order, but not side by side: a label
        # can wrap onto the next line of its table cell ("Other ongoing", then "costs" on F09).
        # Brackets and quote marks don't count ("Ratio ('OCR')"), and a footnote number stuck
        # to a word is allowed ("OCF6", "ratio4" on factsheets).
        wanted = words(value)
        in_quote = iter(words(quote, footnotes=True))
        return bool(wanted) and all(word in in_quote for word in wanted)  # `in` moves along the quote
    return normalise(value) in quote


def words(text: str, footnotes: bool = False) -> list[str]:
    """The words of a text, in lower case and without punctuation. With footnotes=True,
    a footnote number stuck to the end of a word is dropped: "OCF6" becomes "ocf"."""
    found = re.findall(r"[^\W_]+", normalise(text).casefold())
    if footnotes:
        found = [re.sub(r"^([^\W\d_]{2,})\d{1,2}$", r"\1", word) for word in found]
    return found


def printed_dates(iso: str) -> list[str]:
    """Ways a date is printed in the KIDs and factsheets: 08/06/2026, 08-06-2026, 08.06.2026,
    08.06.26, 8 June 2026, 08 June 2026, 8 Jun 2026, 08 Jun 2026 and 08-Jun-2026."""
    day = date.fromisoformat(iso)
    dd, mm, yy = f"{day.day:02d}", f"{day.month:02d}", f"{day.year % 100:02d}"
    month = MONTHS[day.month - 1]
    short = month[:3]
    return [f"{dd}/{mm}/{day.year}", f"{dd}-{mm}-{day.year}", f"{dd}.{mm}.{day.year}", f"{dd}.{mm}.{yy}",
            f"{day.day} {month} {day.year}", f"{dd} {month} {day.year}",
            f"{day.day} {short} {day.year}", f"{dd} {short} {day.year}", f"{dd}-{short}-{day.year}"]


def date_in_quote(printed: str, quote: str) -> bool:
    """Whether a printed date is in the quote, ignoring case (F25 KID: "8 JANUARY 2026").

    It mustn't be the end of a longer number: 8 June 2026 isn't in "18 June 2026". After
    the year, one footnote digit is allowed (F14 KID: "31 July 20261"), but not two.
    If the text layer lost its spaces ("Factsheetasof30September2026", F19 factsheet),
    the date is also looked for with every space removed.
    """
    def found(date_text: str, text: str) -> bool:
        return re.search(rf"(?<!\d){re.escape(date_text)}(?!\d\d)", text, re.IGNORECASE) is not None
    return found(printed, quote) or found(printed.replace(" ", ""), quote.replace(" ", ""))


def to_number(value: str) -> float | None:
    """"0.8", "0.00" and "0" become numbers; anything else (e.g. "1,5" or "N/A") is None."""
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    return float(value)
