"""Tests for the quote check and format checks (Story 2.2, step 2)."""

from datetime import date

import pytest

from fundcrosscheck.checks import check_fields, format_problem, printed_dates, to_number
from fundcrosscheck.common import NOT_FOUND, Field

TODAY = date(2026, 10, 31)


def run(fields, pages):
    """Run the checks the way kid.extract does, returning the notes."""
    notes = []
    check_fields(fields, pages, notes, today=TODAY)
    return notes


# --- the quote check ---------------------------------------------------------

def test_good_values_pass_unchanged():
    page = ("Product\nF&C Investment Trust PLC\nISIN: GB00BS88V647\nDate of Production: 08/06/2026\n"
            "We have classified this product as 4, which is a medium risk class. "
            "The summary risk indicator is a guide")
    fields = {
        "fund_name": Field("F&C Investment Trust PLC", 1, "F&C Investment Trust PLC"),
        "isin": Field("GB00BS88V647", 1, "ISIN: GB00BS88V647"),
        "risk_score": Field("4", 1, "classified this product as 4"),
        "risk_method": Field("SRI", 1, "summary risk indicator"),
        "doc_date": Field("2026-06-08", 1, "Date of Production: 08/06/2026"),
    }
    before = {name: field.value for name, field in fields.items()}
    assert run(fields, [page]) == []
    assert {name: field.value for name, field in fields.items()} == before


def test_quote_not_on_its_page_is_removed():
    fields = {"isin": Field("GB00BS88V647", 1, "ISIN: GB00BS88V647")}
    notes = run(fields, ["page one", "ISIN: GB00BS88V647"])  # it's on page 2, not 1
    assert fields["isin"].value == NOT_FOUND
    assert notes == ["isin 'GB00BS88V647' removed: quote not found on page 1."]


def test_value_not_in_its_quote_is_removed_and_its_label_goes_too():
    # A made-up number: the quote is real, but it doesn't say 0.54. The label passes
    # its own check, so only the "label goes with its charge" rule removes it.
    quote = "The latest published Ongoing Charge ... was 0.45%"
    fields = {"ongoing_charge_pct": Field("0.54", 2, quote), "charge_label": Field("Ongoing Charge", 2, quote)}
    notes = run(fields, ["", quote])
    assert fields["ongoing_charge_pct"].value == NOT_FOUND
    assert fields["charge_label"].value == NOT_FOUND
    assert notes == ["ongoing_charge_pct '0.54' removed: value not in its quote."]


def test_missing_page_or_quote_is_removed():
    fields = {"risk_score": Field("4"), "isin": Field("GB00BS88V647", 3, "ISIN: GB00BS88V647")}
    notes = run(fields, ["ISIN: GB00BS88V647"])
    assert fields["risk_score"].value == NOT_FOUND
    assert fields["isin"].value == NOT_FOUND
    assert "no page or quote" in notes[0]
    assert "page 3 doesn't exist" in notes[1]


def test_not_found_values_are_left_alone():
    fields = {"total_cost_pct": Field(NOT_FOUND, 3, "Impact on return (RIY) per year N/A N/A N/A")}
    assert run(fields, ["", "", "something else"]) == []
    assert fields["total_cost_pct"].quote == "Impact on return (RIY) per year N/A N/A N/A"


@pytest.mark.parametrize("quote, page", [
    ("We have classiﬁed this product as 5", "We have classified this product as 5"),  # F12: ligature in the quote
    ("We have classified this product as 5", "We have classiﬁed this product as 5"),  # ... or on the page
    ("classifies this product as '4'", "classifies this product as ‘4’ out of ‘7’"),  # F10: curly quotes
    ("classified this product as 4", "classified   this\nproduct as 4"),              # spacing and line breaks
])
def test_quote_check_matches_after_normalising(quote, page):
    fields = {"risk_score": Field(quote.split()[-1].strip("'"), 1, quote)}
    assert run(fields, [page]) == []


def test_text_values_are_normalised_too():
    # A curly apostrophe in the value must still match the straightened quote and page.
    fields = {"fund_name": Field("Baillie Gifford’s Trust plc", 1, "Product: Baillie Gifford’s Trust plc")}
    assert run(fields, ["Product: Baillie Gifford's Trust plc"]) == []


@pytest.mark.parametrize("value, quote, ok", [
    ("0.8", "Other ongoing costs 0.8%", True),
    ("0.8", "Other ongoing costs 10.8%", False),   # not the number on its own
    ("0.8", "Other ongoing costs 0.85%", False),
    ("0.00", "Other ongoing costs 0.00%", True),
    ("0", "Impact on return (RIY) per year 0%", True),
])
def test_numbers_must_stand_alone_in_the_quote(value, quote, ok):
    fields = {"ongoing_charge_pct": Field(value, 1, quote)}
    run(fields, [quote])
    assert (fields["ongoing_charge_pct"].value == value) == ok


# --- the two exceptions: dates and risk methods ------------------------------

@pytest.mark.parametrize("value, quote", [
    ("2026-06-08", "Date of Production: 08/06/2026"),                                # F16
    ("2025-04-01", "Date of Publication: 01-04-2025"),                               # F12
    ("2026-05-25", "This document is dated 25 May 2026."),                           # F04
    ("2026-01-20", "Date of production of this document: 20 January 2026"),          # F13
    ("2026-07-31", "This key information document was produced on 31 July 20261"),   # F14, footnote 1
])
def test_dates_are_found_as_printed(value, quote):
    fields = {"doc_date": Field(value, 1, quote)}
    assert run(fields, [quote]) == []


def test_a_different_date_in_the_quote_is_removed():
    fields = {"doc_date": Field("2026-08-06", 1, "Date of Production: 08/06/2026")}  # day and month swapped
    run(fields, ["Date of Production: 08/06/2026"])
    assert fields["doc_date"].value == NOT_FOUND


def test_printed_dates():
    assert printed_dates("2026-06-08") == ["08/06/2026", "08-06-2026", "8 June 2026", "08 June 2026"]


@pytest.mark.parametrize("quote, ok", [
    ("summary risk indicator", True),
    ("The Summary Risk Indicator is a guide", True),
    ("SRI generated as at 31 Mar 2026", True),    # F14
    ("This KID covers Sri Lanka", False),         # not the indicator
])
def test_risk_method_needs_the_indicators_name(quote, ok):
    fields = {"risk_method": Field("SRI", 1, quote)}
    run(fields, [quote])
    assert (fields["risk_method"].value == "SRI") == ok


# --- the format checks -------------------------------------------------------

@pytest.mark.parametrize("name, value, problem", [
    ("isin", "GB00BS88V646", "not a valid ISIN"),
    ("ongoing_charge_pct", "7.5", "not a percentage from 0 to 5"),
    ("total_cost_pct", "N/A", "not a percentage from 0 to 5"),
    ("transaction_cost_pct", "1,5", "not a percentage from 0 to 5"),
    ("risk_score", "8", "not a whole number from 1 to 7"),
    ("risk_score", "4.0", "not a whole number from 1 to 7"),
    ("risk_method", "sri", "not SRI, SRRI or other"),
    ("doc_date", "08/06/2026", "not a YYYY-MM-DD date"),
    ("doc_date", "2026-02-31", "not a real date"),
    ("doc_date", "2016-12-31", "not between 2017-01-01 and today"),
    ("doc_date", "2026-11-01", "not between 2017-01-01 and today"),
])
def test_format_problems(name, value, problem):
    assert format_problem(name, value, TODAY) == problem


@pytest.mark.parametrize("name, value", [
    ("isin", "JE00B1GXH751"), ("ongoing_charge_pct", "0"), ("total_cost_pct", "5"),
    ("risk_score", "1"), ("risk_score", "7"), ("risk_method", "other"),
    ("doc_date", "2017-12-29"), ("doc_date", "2026-10-31"),
    ("fund_name", "anything"),  # no format rule for names
])
def test_good_formats_pass(name, value):
    assert format_problem(name, value, TODAY) is None


@pytest.mark.parametrize("value, number", [("0.8", 0.8), ("0.00", 0.0), ("0", 0.0), ("1.52", 1.52), ("N/A", None), ("1,5", None), ("", None)])
def test_to_number(value, number):
    assert to_number(value) == number
