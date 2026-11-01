"""Tests for the KIID reader (Story 2.3), using the real wordings of the five KIIDs."""

import csv
from pathlib import Path

import pytest

from fundcrosschecker import kiid
from fundcrosschecker.common import NOT_FOUND

PROJECT = Path(__file__).resolve().parent.parent

# The name blocks at the top of page 1, as the text layer gives them.
NAME_BLOCKS = {
    "F01": ("Vanguard LifeStrategy 60% Equity Fund A GBP Accumulation Shares\n"
            '(the "Fund") ISIN: GB00B3TYHH97\n'
            "A sub-fund of Vanguard LifeStrategy Funds ICVC Authorised Corporate Director: Vanguard Investments UK, Limited",
            "Vanguard LifeStrategy 60% Equity Fund", "A GBP Accumulation Shares"),
    "F02": ("KEY INVESTOR INFORMATION\nThis document provides you with key investor information about this Fund. It is "
            "not marketing material. The\nClass D Accumulating GBP\niShares UK Equity Index Fund (UK)\n"
            "ISIN: GB00B7C44X99\nA sub-fund of BlackRock Collective Investment Funds\nManager: BlackRock Fund Managers Limited",
            "iShares UK Equity Index Fund (UK)", "Class D Accumulating GBP"),
    "F03": ("Fidelity Index World Fund\nKey Investor Information\nFidelity Index World Fund\n"
            "a sub-fund of Fidelity Investment Funds\nFidelity Index World Fund P Accumulation Shares\n"
            "(ISIN:GB00BJS8SJ34)\nThis fund is managed by FIL Investment Services (UK) Limited",
            "Fidelity Index World Fund", "P Accumulation Shares"),
    "F07": ("Key Investor Information\nare advised to read it so you can make an informed decision about whether to invest.\n"
            "Jupiter Asset Management Series PLC - Jupiter Gold & Silver Fund\n"
            "(the 'Fund'), a sub-fund of Jupiter Asset Management Series PLC\nI GBP Acc (ISIN - IE00BYVJRH94)\n"
            'The Manager is Jupiter Asset Management (Europe) Limited (the "Manager")',
            "Jupiter Gold & Silver Fund", "I GBP Acc"),
    "F08": ("Key Investor Information\nArtemis Global Income Fund (the “fund”)\n"
            "The fund is managed by Artemis Fund Managers Limited.\nISIN: GB00B5ZX1M70\n"
            "Class: I accumulation units, GBP\nThis key investor information document is accurate as at 18 February 2026.",
            "Artemis Global Income Fund", "I accumulation units, GBP"),
}


@pytest.mark.parametrize("fund_id", sorted(NAME_BLOCKS))
def test_name_and_share_class_in_each_layout(fund_id):
    page, name, share_class = NAME_BLOCKS[fund_id]
    notes = []
    name_field, share_field = kiid._name_and_share_class(page, notes)
    assert (name_field.value, share_field.value) == (name, share_class)
    assert notes == []


@pytest.mark.parametrize("page, note", [
    ("", "No ISIN on page 1"),
    ("Some Fund A Accumulation Shares\nISIN: GB00B3TYHH98", "No ISIN on page 1"),  # wrong check digit
    ("Key Investor Information\nISIN: GB00B3TYHH97", "No fund name found"),
    ("The fund is managed by Artemis Fund Managers Limited.\nISIN: GB00B5ZX1M70", "No fund name found"),
    ("This Fund A Accumulation Shares\nISIN: GB00B5ZX1M70", "No fund name found"),  # a reference, not a name
    ("Foo Fund Managers Limited\nISIN: GB00B5ZX1M70", "No fund name found"),        # "Fund" inside a company name
    ("Foo Fund\nline\nline\nline\nISIN: GB00B5ZX1M70", "No fund name found"),        # too far above the ISIN
])
def test_no_name_without_a_name_line_near_a_valid_isin(page, note):
    notes = []
    name, share_class = kiid._name_and_share_class(page, notes)
    assert (name.value, share_class.value) == (NOT_FOUND, NOT_FOUND)
    assert notes and notes[0].startswith(note)


def test_the_name_can_be_three_lines_above_the_isin():  # the most allowed
    name, _ = kiid._name_and_share_class("Foo Fund\nline\nline\nISIN: GB00B5ZX1M70", [])
    assert name.value == "Foo Fund"


def test_a_name_too_long_to_be_one():
    line = "A" * (kiid.LONGEST_NAME - len(" Fund")) + " Fund"
    assert kiid._name_and_share_class(f"{line}\nISIN: GB00B5ZX1M70", [])[0].value == line   # 80: kept
    assert kiid._name_and_share_class(f"B{line}\nISIN: GB00B5ZX1M70", [])[0].value == NOT_FOUND  # 81: not


def test_a_name_without_a_share_class_is_kept_with_a_note():
    notes = []
    name, share_class = kiid._name_and_share_class("Foo Global Fund\nISIN: GB00B5ZX1M70\nManager: Foo Ltd", notes)
    assert (name.value, share_class.value) == ("Foo Global Fund", NOT_FOUND)
    assert notes == ["No share class found next to the name: Foo Global Fund"]


@pytest.mark.parametrize("page", [
    "Line above\nFoo Global Fund\nISIN: GB00B5ZX1M70",             # no "Class" line above the name
    "Classic investing\nFoo Global Fund\nISIN: GB00B5ZX1M70",      # "Classic" isn't "Class"
    "Foo Global Fund\nISIN: GB00B5ZX1M70\nline\nline\nClass: B",   # the Class line is too far below
])
def test_share_class_lines_that_dont_count(page):
    assert kiid._name_and_share_class(page, [])[1].value == NOT_FOUND


# --- ongoing charge ------------------------------------------------------------------

@pytest.mark.parametrize("text, value, label", [
    ("Charges taken from the Fund over a year\nOngoing charges 0.20%", "0.20", "Ongoing charges"),  # F01
    ("Ongoing Charges 0.05%**", "0.05", "Ongoing Charges"),                                        # F02
    ("Ongoing charges 0.825% -10%", "0.825", "Ongoing charges"),                                   # F08
    ("Ongoing charges 0.92 %", "0.92", "Ongoing charges"),                                         # a space before %
    ("Ongoing charges 0%", "0", "Ongoing charges"),                                                # zero
])
def test_the_ongoing_charges_row(text, value, label):
    fields = kiid._charge(["page 1", text], [])
    assert (fields["ongoing_charge_pct"].value, fields["charge_label"].value) == (value, label)
    assert fields["ongoing_charge_pct"].page == 2


@pytest.mark.parametrize("text", [
    "The ongoing charges figure is based on expenses for the year ended 31 December 2025.",  # sentence, no figure
    "Ongoing charges are shown in the prospectus.",
    "ongoing charges 0.20%",                                                                 # not the row's capital
    "",
])
def test_no_ongoing_charges_row(text):
    notes = []
    fields = kiid._charge([text], notes)
    assert fields["ongoing_charge_pct"].value == fields["charge_label"].value == NOT_FOUND
    assert notes == ["No ongoing charges row found."]


# --- risk ----------------------------------------------------------------------------

@pytest.mark.parametrize("text, value, quote", [
    ("The Fund is rated 4 due to the nature of its investments", "4", "Fund is rated 4"),              # F01
    ("The Fund is rated five due to the nature of its investments", "5", "Fund is rated five"),        # F02
    ("This fund is categorised in risk class 5 because", "5", "categorised in risk class 5"),          # F03
    ("◼ Funds in category 7 have in the past shown very high volatility.", "7", "Funds in category 7 have"),  # F07
    ("The Fund is rated Seven", "7", "Fund is rated Seven"),                                           # a capital
    ("The fund is rated 1", "1", "fund is rated 1"),                                                   # lowest
])
def test_risk_sentences(text, value, quote):
    field = kiid._risk_score([text])
    assert (field.value, field.quote) == (value, quote)


@pytest.mark.parametrize("text", [
    "The Fund is rated 8 due to",            # not on the scale
    "The Fund is rated 0",
    "The Fund is rated 45 by Morningstar",   # a bigger number
    "The Fund is rated fivefold",            # not the word five
    "Funds in category 7 are",               # not the sentence F07 uses
    "The bond is rated 4 by Moody's",        # not the fund
])
def test_sentences_that_arent_a_risk_category(text):
    assert kiid._risk_score([text]).value == NOT_FOUND


def test_the_number_lifted_out_of_the_scale():  # F08's larger 5
    page = "Potentially lower reward Potentially higher reward\nlitical and economic events.\n5\n1 2 3 4 6 7 base currency."
    field = kiid._risk_score([page])
    assert (field.value, field.page, field.quote) == ("5", 1, "5 1 2 3 4 6 7")


@pytest.mark.parametrize("page", [
    "2\n1 2 3 4 5 6 7",       # a page number above the full scale
    "5\n1 2 3 4 6",           # two numbers missing
    "5\n1 2 3 4 6 7 8",       # the scale runs on
    "5\nother\n1 2 3 4 6 7",  # not straight above
    "8\n1 2 3 4 5 6 7",       # not a scale number
    "5",                      # last line, nothing after it
    "",
])
def test_lines_that_arent_a_lifted_number(page):
    assert kiid._risk_score([page]).value == NOT_FOUND


def test_a_sentence_wins_over_a_lifted_number():
    assert kiid._risk_score(["5\n1 2 3 4 6 7\nThe Fund is rated 4 due to"]).value == "4"


@pytest.mark.parametrize("text, value", [
    ("This is the synthetic risk and reward indicator (SRRI).", "SRRI"),
    ("The SRRI is 5.", "SRRI"),
    ("The risk and reward indicator does not take account of the following risks", NOT_FOUND),  # F01: not named
    ("Srri", NOT_FOUND),   # the short form must be in capitals
])
def test_risk_method_only_when_named(text, value):
    assert kiid._risk_method([text]).value == value


# --- date ----------------------------------------------------------------------------

@pytest.mark.parametrize("pages, value, page", [
    (["p1", "This key investor information is accurate as at 26/06/2026."], "2026-06-26", 2),       # F01
    (["p1", "This Key Investor Information is accurate as at 09 February 2026"], "2026-02-09", 2),  # F02
    (["This key investor information document is accurate as at 18 February 2026.\n"
      "Risk indicator number is accurate as at: 31 January 2026."], "2026-02-18", 1),               # F08
])
def test_the_kiids_own_date(pages, value, page):
    field = kiid._doc_date(pages, [])
    assert (field.value, field.page) == (value, page)


@pytest.mark.parametrize("text", [
    "Risk indicator number is accurate as at: 31 January 2026.",   # F08's other dates
    "Charges are accurate as at: 31 July 2025, unless specified.",
    "Past performance is accurate as at: 31 December 2025.",
    "This key investor information is accurate as at 6/2/2026.",   # a form the checks don't know
    "",
])
def test_other_dates_arent_the_kiids_date(text):
    assert kiid._doc_date([text], []).value == NOT_FOUND


def test_an_impossible_date_is_noted():
    notes = []
    assert kiid._doc_date(["This key investor information is accurate as at 31/02/2026."], notes).value == NOT_FOUND
    assert notes == ["Not a real date: key investor information is accurate as at 31/02/2026"]


# --- the whole document ----------------------------------------------------------------

def test_no_pages_is_an_error():
    with pytest.raises(ValueError):
        kiid.extract([])


def test_transaction_and_total_cost_are_never_read():
    page = "Foo Fund A Acc\nISIN: GB00B5ZX1M70\nTransaction costs 0.10% Total costs 1.00% Ongoing charges 0.50%"
    fields, _ = kiid.extract([page])
    assert fields["transaction_cost_pct"].value == fields["total_cost_pct"].value == NOT_FOUND
    assert fields["ongoing_charge_pct"].value == "0.50"


def test_fields_come_in_the_answer_key_order():
    fields, _ = kiid.extract(["nothing here"])
    assert list(fields) == ["fund_name", "isin", "share_class", "ongoing_charge_pct", "charge_label",
                            "transaction_cost_pct", "total_cost_pct", "risk_score", "risk_method", "doc_date"]
    assert all(field.value == NOT_FOUND for field in fields.values())


def answer_key_rows():
    with (PROJECT / "data" / "answer_key.csv").open(encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row["doc_type"] == "kiid"]


@pytest.mark.parametrize("row", answer_key_rows(), ids=lambda row: row["fund_id"])
def test_real_kiids_match_the_answer_key(row):
    pdf = PROJECT / "pdfs" / f"{row['fund_id']}_kiid.pdf"
    if not pdf.exists():
        pytest.skip(f"pdfs/{pdf.name} isn't here (PDFs aren't in the repo)")
    from fundcrosschecker.pdftext import read_pages

    fields, notes = kiid.extract(read_pages(pdf))
    assert {name: field.value for name, field in fields.items()} == {name: row[name] for name in fields}
    assert notes == []


def test_values_go_through_the_checks():
    # 9.50% is outside the 0-5% a charge can be, so the checks remove it, and its label with it.
    fields, notes = kiid.extract(["Foo Fund A Acc\nISIN: GB00B5ZX1M70\nOngoing charges 9.50%"])
    assert fields["ongoing_charge_pct"].value == fields["charge_label"].value == NOT_FOUND
    assert any("ongoing_charge_pct '9.50' removed" in note for note in notes)
    assert fields["fund_name"].value == "Foo Fund"   # the rest is kept
