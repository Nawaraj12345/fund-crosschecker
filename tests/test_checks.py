"""Tests for the quote check and format checks (Story 2.2, step 2)."""

from datetime import date

import pytest

from fundcrosschecker.checks import check_fields, format_problem, printed_dates, same_word, to_number, value_in_quote
from fundcrosschecker.common import NOT_FOUND, Field

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
    assert printed_dates("2026-06-08") == ["08/06/2026", "08-06-2026", "08.06.2026", "08.06.26",
                                           "8 June 2026", "08 June 2026", "8 Jun 2026", "08 Jun 2026",
                                           "08-Jun-2026"]


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


@pytest.mark.parametrize("value, quote, ok", [
    ("Other ongoing costs", "Other ongoing 0.8% The impact of the costs that are incurred each year for managing your costs", True),  # F09 wraps
    ("Other ongoing costs", "Other ongoing costs 0.00%", True),
    ("OCF", "The OCF for the year to 31 August 2025 was 1.52%.", True),                                 # F04
    ("Other ongoing costs", "costs Other ongoing 0.8%", False),     # words out of order
    ("Ongoing Charge", "The latest published OCR was 0.74%", False),  # words not there
    ("OCF", "The OCFs for the year", False),                        # whole words only
])
def test_charge_label_words_must_appear_in_order(value, quote, ok):
    # The label needs a charge beside it, or the "label goes with its charge" rule removes it.
    fields = {"ongoing_charge_pct": Field("1", 1, "1%"), "charge_label": Field(value, 1, quote)}
    run(fields, [quote + " 1%"])
    assert (fields["charge_label"].value == value) == ok


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


# --- edge cases just past the limits ------------------------------------------------

@pytest.mark.parametrize("name, value, problem", [
    ("ongoing_charge_pct", "5.01", "not a percentage from 0 to 5"),   # just over the top
    ("ongoing_charge_pct", "-0.1", "not a percentage from 0 to 5"),   # below zero
    ("ongoing_charge_pct", "", "not a percentage from 0 to 5"),       # empty
    ("risk_score", "0", "not a whole number from 1 to 7"),            # just under the bottom
    ("risk_score", "07", "not a whole number from 1 to 7"),
    ("risk_score", " 7", "not a whole number from 1 to 7"),
    ("doc_date", "2026-9-30", "not a YYYY-MM-DD date"),
    ("doc_date", "", "not a YYYY-MM-DD date"),
    ("isin", "", "not a valid ISIN"),
])
def test_format_problems_at_the_edges(name, value, problem):
    assert format_problem(name, value, TODAY) == problem


@pytest.mark.parametrize("page, quote, reason", [
    (3, "Ongoing charges 0.45%", "page 3 doesn't exist"),     # past the last page
    (-1, "Ongoing charges 0.45%", "page -1 doesn't exist"),
    (0, "Ongoing charges 0.45%", "no page or quote"),
    (1, "", "no page or quote"),
    (1, "   ", "value not in its quote"),
])
def test_bad_pages_and_quotes_are_removed(page, quote, reason):
    fields, notes = {"ongoing_charge_pct": Field("0.45", page, quote)}, []
    check_fields(fields, ["Ongoing charges 0.45%", "page two"], notes, TODAY)
    assert fields["ongoing_charge_pct"].value == NOT_FOUND
    assert reason in notes[0]


@pytest.mark.parametrize("value, number", [(".5", None), ("5.", None), ("-0.5", None), ("1e3", None), (" 1", None)])
def test_to_number_rejects_other_forms(value, number):
    assert to_number(value) == number


# --- weaknesses found on 2026-10-31, fixed after the unseen-trusts KID run --------------

@pytest.mark.parametrize("value, quote", [
    ("1", "Ongoing charges 1.5%"),      # a whole number inside a decimal
    ("1", "Total costs £1,000"),        # inside a number with a thousands comma
    ("0.5", "Performance -0.5%"),       # a minus sign in front
    ("0.5", "Performance −0.5%"),       # the minus character (U+2212)
    ("0", "Other ongoing costs 0.00%"), # the start of a decimal
    ("1", "1 .03%"),                    # the start of a split decimal (joined first)
    ("1", "SRRI1 4"),                   # a footnote number stuck to a word (F01 factsheet)
    ("4", "ratio4 0.6%"),
])
def test_a_number_inside_another_number_is_not_accepted(value, quote):
    fields, notes = {"ongoing_charge_pct": Field(value, 1, quote)}, []
    check_fields(fields, [quote], notes, TODAY)
    assert fields["ongoing_charge_pct"].value == NOT_FOUND


@pytest.mark.parametrize("value, quote", [
    ("1.03", "1 .03%"),                                         # F14 factsheet: the text layer splits it
    ("4", "We have classified this product as 4, which is"),    # a comma after it isn't a decimal
    ("4", "classified this product as 4."),                     # nor a full stop at the end
    ("5", "5 out of 7"),
    ("0", "Impact on return (RIY) per year 0% 0% 0%"),
    ("4", "SRRI1 4"),                                            # the real score next to a footnote
    ("0.73", "OCF6 0.73%"),
])
def test_a_number_on_its_own_is_accepted(value, quote):
    fields, notes = {"ongoing_charge_pct": Field(value, 1, quote)}, []
    check_fields(fields, [quote], notes, TODAY)
    assert fields["ongoing_charge_pct"].value == value, notes


@pytest.mark.parametrize("name, value", [
    ("fund_name", ""), ("fund_name", "   "), ("share_class", ""), ("charge_label", " "),
])
def test_an_empty_text_value_is_not_accepted(name, value):
    fields = {"ongoing_charge_pct": Field("1", 1, "1%"), name: Field(value, 1, "F&C Investment Trust PLC")}
    run(fields, ["F&C Investment Trust PLC 1%"])
    assert fields[name].value == NOT_FOUND
    assert format_problem(name, value, TODAY) == "empty"


# --- what factsheet text needs (found on the 19 development factsheets) -------------------

@pytest.mark.parametrize("value, quote", [
    ("2026-09-30", "Net Asset information as at: 30-Sep-2026"),          # F02 factsheet
    ("2026-09-30", "30.09.26 Monthly Factsheet Marketing Communication"),  # F03 factsheet
    ("2026-09-30", "Factsheetasof30September2026"),                      # F19 factsheet: no spaces
    ("2026-10-05", "Last Updated On 05.10.2026"),                        # F29 KID
    ("2026-01-08", "THIS DOCUMENT WAS PRODUCED ON 8 JANUARY 2026"),      # F25 KID: capitals
    ("2026-09-30", "as at 30 Sep 2026"),
])
def test_more_date_formats_are_found(value, quote):
    fields = {"doc_date": Field(value, 1, quote)}
    assert run(fields, [quote]) == []


@pytest.mark.parametrize("value, quote", [
    ("2026-06-08", "Produced 18 June 2026"),          # 8 June isn't in 18 June
    ("2026-06-08", "Produced 18/06/2026"),
    ("2026-06-08", "Produced18June2026"),             # nor with the spaces gone
    ("2026-07-31", "produced on 31 July 202612"),     # two digits after the year: a longer number
    ("2026-09-30", "30.09.25 Monthly Factsheet"),     # a different year
    ("2026-09-30", "30-Oct-2026"),                    # a different month
])
def test_a_date_inside_another_number_or_a_different_date_is_removed(value, quote):
    fields = {"doc_date": Field(value, 1, quote)}
    run(fields, [quote])
    assert fields["doc_date"].value == NOT_FOUND


@pytest.mark.parametrize("value, quote, ok", [
    ("Ongoing Charges Figure (OCF)", "Ongoing Charges Figure (OCF2) 0.20%", True),  # F01: bracket and footnote 2
    ("Ongoing Charges Ratio (‘OCR’)", "Ongoing Charges Ratio (‘OCR’)* 0.6%", True),  # F09: bracket and quote marks
    ("OCF", "OCF6 0.73%", True),                                                   # F10: footnote 6
    ("AIC operating expenses ratio", "AIC operating expenses ratio4", True),       # F14: footnote 4
    ("Ongoing charges (year end 31 Aug 2025)", "Ongoing charges", False),          # F04: words missing from the quote
    ("OCF", "OCF2026 0.73%", False),     # four digits aren't a footnote
    ("OCF", "OCFS 0.73%", False),        # nor letters
    ("()", "Ongoing charges () 0.5%", False),  # a label with no words
])
def test_labels_ignore_brackets_and_footnote_numbers(value, quote, ok):
    fields = {"ongoing_charge_pct": Field("1", 1, "1%"), "charge_label": Field(value, 1, quote)}
    run(fields, [quote + " 1%"])
    assert (fields["charge_label"].value == value) == ok


@pytest.mark.parametrize("quote, ok", [
    ("SRRI1 4", True),     # F01 factsheet: footnote 1
    ("SRRI 4", True),
    ("SRRIs 4", False),    # not the name on its own
    ("SRRI123 4", False),  # three digits aren't a footnote
])
def test_risk_method_short_name_with_a_footnote(quote, ok):
    fields = {"risk_method": Field("SRRI", 1, quote)}
    run(fields, [quote])
    assert (fields["risk_method"].value == "SRRI") == ok


# --- from the code review of 1 Nov 2026 --------------------------------------------------

@pytest.mark.parametrize("value, quote", [
    ("2026-06-18", "Data as at1 8 June 2026"),   # a footnote ¹ (NFKC makes it 1) mustn't join the day
    ("2026-06-28", "Page 2 8 June 2026"),        # nor a page number
])
def test_a_separate_number_in_front_doesnt_join_the_day(value, quote):
    fields = {"doc_date": Field(value, 1, quote)}
    run(fields, [quote])
    assert fields["doc_date"].value == NOT_FOUND


@pytest.mark.parametrize("value, quote, ok", [
    ("0.73", "OngoingCharges0.73%", True),    # text that lost its spaces: a figure, not a footnote
    ("0.65", "OCF0.65 %", True),
    ("0.73", "Charges10.73%", False),         # still not the end of a longer number
    ("1", "SRRI1 4", False),                  # no % after it: a footnote mark
])
def test_a_number_stuck_to_a_word_counts_only_with_a_percent_sign(value, quote, ok):
    fields = {"ongoing_charge_pct": Field(value, 1, quote)}
    run(fields, [quote])
    assert (fields["ongoing_charge_pct"].value == value) == ok


@pytest.mark.parametrize("value, quote, ok", [
    ("Ongoing charges FY25", "Ongoing charges FY25 0.5%", True),   # digits in the label itself
    ("OCF (Dec24)", "OCF (Dec24) 0.5%", True),
    ("Ongoing charges FY24", "Ongoing charges FY25 0.5%", False),  # different digits aren't a footnote
])
def test_label_words_with_digits_match_exactly(value, quote, ok):
    fields = {"ongoing_charge_pct": Field("1", 1, "1%"), "charge_label": Field(value, 1, quote)}
    run(fields, [quote + " 1%"])
    assert (fields["charge_label"].value == value) == ok


@pytest.mark.parametrize("name, value, quote", [
    ("share_class", "-", "Share class: -"),
    ("fund_name", ".", "Fund facts."),
    ("charge_label", "()", "Ongoing charges () 1%"),
])
def test_a_value_with_no_letters_or_digits_is_removed(name, value, quote):
    fields = {"ongoing_charge_pct": Field("1", 1, "1%"), name: Field(value, 1, quote)}
    run(fields, [quote + " 1%"])
    assert fields[name].value == NOT_FOUND
    assert format_problem(name, value, TODAY) == "no letters or digits"


@pytest.mark.parametrize("value", ["", "()", "‘ ’"])
def test_a_label_with_no_words_is_never_in_a_quote(value):
    # check_fields stops these earlier ("empty", "no letters or digits"), but the quote check
    # must hold on its own too: "every one of no words is in the quote" would be true.
    assert not value_in_quote("charge_label", value, "Ongoing charges 0.5%")


@pytest.mark.parametrize("value, quote, ok", [
    ("5", "The Fund is rated five", True),     # F02 KIID
    ("5", "The Fund is rated Five", True),
    ("4", "The Fund is rated five", False),    # the wrong word
    ("5", "The Fund is rated fivefold", False),
    ("7", "seventy", False),
])
def test_a_risk_score_written_as_a_word(value, quote, ok):
    fields = {"risk_score": Field(value, 1, quote)}
    run(fields, [quote])
    assert (fields["risk_score"].value == value) == ok


def test_number_words_count_only_for_the_risk_score():
    assert not value_in_quote("ongoing_charge_pct", "1", "one per cent")
    assert not value_in_quote("transaction_cost_pct", "2", "two")


# --- after the unseen factsheet run of 1 Nov 2026 ------------------------------------------

@pytest.mark.parametrize("value, quote, ok", [
    ("Ongoing charges", "Ongoing chargesD 0.50%", True),     # F21 factsheet: footnote D
    ("Ongoing charges", "Ongoing Charges 0.50%", True),      # case alone never mattered
    ("Ongoing charges", "Ongoing chargesDE 0.50%", False),   # two capitals aren't a footnote mark
    ("Ongoing charge", "Ongoing chargesD 0.50%", False),     # without its mark the word is still "charges"
    ("Ongoing charges", "Ongoing charges5D 0.50%", False),   # a digit and a letter
    ("OCF", "OCFS 0.73%", False),                            # a capital after a capital isn't one
])
def test_a_label_word_may_carry_one_capital_footnote_letter(value, quote, ok):
    fields = {"ongoing_charge_pct": Field("1", 1, "1%"), "charge_label": Field(value, 1, quote)}
    run(fields, [quote + " 1%"])
    assert (fields["charge_label"].value == value) == ok


@pytest.mark.parametrize("label_word, quote_word, same", [
    ("charges", "chargesD", True),
    ("charges", "CHARGES", True),
    ("ocf", "OCF6", True),
    ("ocf", "OCFS", False),
    ("charges", "chargesDE", False),
    ("a", "aB", False),          # the word left over must have two letters, as for footnote numbers
    ("charge", "chargeS", True),  # the rule can't tell this from a plural printed oddly; the quote still has to be on the page
])
def test_same_word(label_word, quote_word, same):
    assert same_word(label_word, quote_word) == same


@pytest.mark.parametrize("value, quote, ok", [
    ("Ordinary shares", "Ordinary shares in Issue: 484,494,150", False),         # F26: a count of shares
    ("Ordinary shares", "Ordinary shares in issue* 623,475,335", False),         # F27
    ("Ordinary shares", "Ordinary shares held in treasury: 6,102,806", False),   # F23
    ("Ordinary shares", "Ordinary shares IN ISSUE 5", False),
    ("Ordinary shares", "Ordinary shares 197,864,151", True),                    # F22: kept (its key facts name the class)
    ("Ordinary shares", "Ordinary shares in RIT Capital Partners plc", True),    # F10 KID: "in", but not "in issue"
    ("Ordinary shares", "Ordinary shares in issuers' markets", True),            # "issuers" isn't "issue"
    ("Ordinary shares", "Ordinary shares in issue: 9. Ordinary shares 1.2p", True),  # also printed as a name
    ("Class A (Acc)", "Class A (Acc) shares in issue 5", False),                 # a count, with "shares" between
    ("Class A (Acc)", "Class A (Acc) in issue 5", False),                        # brackets in the value are matched as text
    ("Class A (Acc)", "Class A (Acc) GBP", True),
    ("Ordinary", "Ordinary shares in issue: 484,494,150", False),                # a shorter value from the same count
    ("Ordinary shares", "Ordinary shares outstanding 484,494,150", False),       # another wording of a count
    ("Ordinary shares", "Number of Ordinary shares 484,494,150", False),         # the count named in front
    ("Ordinary shares", "Number of the Ordinary shares: 5", False),
    ("Ordinary shares", "Ordinary shares number of votes", True),                # "number of" after it isn't a count of it
    ("Ordinary shares", "Ordinary shares outstandingly cheap", True),            # "outstandingly" isn't "outstanding"
    ("C shares", "C shares in issue: 50,000,000", False),                        # chosen trade-off: a miss for a trust with more than one class
])
def test_a_share_class_from_a_count_of_shares_is_removed(value, quote, ok):
    fields = {"share_class": Field(value, 1, quote)}
    run(fields, [quote])
    assert (fields["share_class"].value == value) == ok


@pytest.mark.parametrize("quote, reason", [
    ("Ordinary shares in Issue: 484,494,150", "quoted only as a count of shares, not as a class"),  # F26
    ("Income shares 1.2p", "value not in its quote"),   # not in the quote at all
])
def test_the_note_says_why_a_share_class_was_removed(quote, reason):
    notes = run({"share_class": Field("Ordinary shares", 1, quote)}, [quote])
    assert notes == [f"share_class 'Ordinary shares' removed: {reason}."]
