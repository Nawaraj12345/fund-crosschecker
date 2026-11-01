"""Tests for the trust KID extractor.

The end-to-end test needs pdfs/F16_kid.pdf. The PDFs aren't in the repo
(copyright), so it's skipped when the file isn't there.
"""

import csv
from pathlib import Path

import pytest

from fundcrosschecker import kid
from fundcrosschecker.common import NOT_FOUND

PROJECT = Path(__file__).resolve().parent.parent
F16 = PROJECT / "pdfs" / "F16_kid.pdf"


def answer_key_row(fund_id):
    with (PROJECT / "data" / "answer_key.csv").open(encoding="utf-8") as f:
        return next(r for r in csv.DictReader(f) if r["fund_id"] == fund_id and r["doc_type"] == "kid")


@pytest.mark.skipif(not F16.exists(), reason="pdfs/F16_kid.pdf isn't here (PDFs aren't in the repo)")
def test_f16_matches_the_answer_key():
    from fundcrosschecker.pdftext import read_pages

    fields, notes = kid.extract(read_pages(F16))
    key = answer_key_row("F16")
    for name, field in fields.items():
        assert field.value == key[name], name
    assert notes == ["No cost table: ongoing charge taken from the cost section."]


# The product line rules, on the real lines from page 1 of each KID.
@pytest.mark.parametrize("line, name, share_class", [
    ("F&C Investment Trust PLC", "F&C Investment Trust PLC", NOT_FOUND),                                        # F16
    ("Henderson Far East Income Limited ISIN: JE00B1GXH751", "Henderson Far East Income Limited", NOT_FOUND),    # F04
    ("Product Name: AVI Global Trust plc (the “Company”)", "AVI Global Trust plc", NOT_FOUND),                    # F05
    ("Name of Product: Polar Capital Technology Trust plc, Ordinary Shares",
     "Polar Capital Technology Trust plc", "Ordinary Shares"),                                                    # F06
    ("Ordinary shares in RIT Capital Partners plc (RIT or the Company).", "RIT Capital Partners plc", "Ordinary shares"),  # F10
    ("Name: Ordinary Shares in Pantheon International Plc (PIN)", "Pantheon International Plc", "Ordinary Shares"),  # F13
    ("CT Global Managed Portfolio Trust PLC - Income Shares", "CT Global Managed Portfolio Trust PLC", "Income Shares"),  # F17
])
def test_product_line(line, name, share_class):
    notes = []
    name_field, share_field = kid._name_and_share_class(f"Purpose\nProduct\n{line}\nISIN: X", notes)
    assert name_field.value == name
    assert share_field.value == share_class
    assert notes == []


def test_product_heading_repeated_with_junk():  # F11: "Product", "Product", "0B", then the name
    name, share = kid._name_and_share_class("Product\nProduct\n0B\nName: Personal Assets Trust plc ISIN: GB00BM8B5H06", [])
    assert name.value == "Personal Assets Trust plc"
    assert share.value == NOT_FOUND


def test_unclear_product_line_gives_not_found_and_a_note():
    notes = []
    name, share = kid._name_and_share_class("Product\nSomething that isn't a company name", notes)
    assert name.value == NOT_FOUND and share.value == NOT_FOUND
    assert notes == ["Product line not understood: Something that isn't a company name"]


def test_no_product_heading_gives_not_found():  # F09, F12, F14
    name, share = kid._name_and_share_class("KEY INFORMATION DOCUMENT\nPURPOSE\n...", [])
    assert name.value == NOT_FOUND and share.value == NOT_FOUND


def test_cost_section_carries_over_the_page():  # F09: heading and total on page 2, table on page 3
    pages = ["page 1",
             "What are the costs? Total costs £110 £380 £737 Impact on return (RIY) per year 1.0% 1.0% 1.0%",
             "Composition of costs ... Ongoing Portfolio 0.2% The impact\nOther ongoing 0.8% The impact of the costs ...\n"
             "costs investments and running the Company.\nIncidental Performance fees N/A\nHow long should I hold it"]
    notes = []
    costs = kid._costs(pages, notes)
    assert costs["total_cost_pct"].value == "1.0" and costs["total_cost_pct"].page == 2
    assert costs["transaction_cost_pct"].value == "0.2" and costs["transaction_cost_pct"].page == 3
    assert costs["ongoing_charge_pct"].value == "0.8"
    assert notes == []


def test_no_cost_table_uses_the_stated_charge():  # F15 wording
    page = ("What are the costs? ... The latest published Ongoing Charge for the Company (expressed as a "
            "percentage of average net assets) was 0.78% (excluding performance fee). How long should I hold it")
    notes = []
    costs = kid._costs(["page 1", page], notes)
    assert costs["ongoing_charge_pct"].value == "0.78"
    assert costs["ongoing_charge_pct"].page == 2
    assert costs["charge_label"].value == "Ongoing Charge"
    assert costs["transaction_cost_pct"].value == NOT_FOUND
    assert costs["total_cost_pct"].value == NOT_FOUND


def test_empty_pdf_raises():
    with pytest.raises(ValueError, match="no pages"):
        kid.extract([])


def test_impossible_date_gives_not_found_and_a_note():
    notes = []
    assert kid._doc_date("Date of Production: 31/02/2026", notes).value == NOT_FOUND
    assert notes == ["Not a real date: Date of Production: 31/02/2026"]


# --- reading cost tables (Story 2.2, step 4), on each KID's real wording -----------

def costs(*pages):
    notes = []
    return kid._costs(["page 1", *pages], notes), notes


def test_f04_money_figure_with_the_charge_in_its_description():
    fields, notes = costs(
        "What are the costs? Total costs 268 GBP 1,468 GBP\nAnnual cost impact (*) 2.7% 2.7% each year",
        "Composition of costs\nManagement fees and other No fees are payable by you to the Company or its service providers; these are 152 GBP\n"
        "administrative or operating costs incurred by the Company. The OCF for the year to 31 August 2025 was 1.52%.\n"
        "Transaction costs The impact of the costs of the investment manager buying and selling underlying 116 GBP\n"
        "investments for the Company's portfolio.\nIncidental costs taken under specific conditions\nPerformance fees 0 GBP\n"
        "How long should I hold it")
    assert fields["ongoing_charge_pct"].value == "1.52"
    assert fields["ongoing_charge_pct"].quote == "The OCF for the year to 31 August 2025 was 1.52%"
    assert fields["charge_label"].value == "OCF"
    assert fields["transaction_cost_pct"].value == NOT_FOUND  # only 116 GBP: no £ to % sums
    assert fields["total_cost_pct"].value == "2.7"            # the last column
    assert notes == ["Transaction costs: only a £ amount is given (116 GBP), so no percentage."]


def test_f12_description_mixed_into_the_rows():
    fields, notes = costs(
        "What are the costs? Total costs (GBP) 0 0 0 Impact on Return (RIY) per Year (%) 0.00% 0.00% 0.00%\nComposition of costs",
        "Portfolio transaction costs selling underlying investments for the product.\nOngoing costs 0.00% The impact of the costs that we take each\n"
        "Other ongoing costs year for managing your investments. 0.00%\nPerformance fees The impact of the performance fee.\nHow long should I hold it")
    assert fields["transaction_cost_pct"].value == "0.00"
    assert fields["ongoing_charge_pct"].value == "0.00"
    assert fields["ongoing_charge_pct"].quote == "Other ongoing costs year for managing your investments. 0.00%"
    assert fields["charge_label"].value == "Other ongoing costs"
    assert fields["total_cost_pct"].value == "0.00"
    assert notes == []


def test_f05_clean_row_wins_over_a_sentence_about_it():
    fields, _ = costs(
        "What are the costs? Impact on return (RIY) per year 0.70% 0.70% 0.70%\nComposition of costs\n"
        "Other ongoing costs of 0.70% reflects the total fee paid to Asset Value Investors Limited\n"
        "Portfolio transaction costs 0.00% The impact of the costs of buying and selling underlying investments for the product.\n"
        "Other ongoing costs 0.70% The impact of the costs charged each year for managing your investments.\nHow long should I hold it")
    assert fields["ongoing_charge_pct"].value == "0.70"
    assert fields["ongoing_charge_pct"].quote == "Other ongoing costs 0.70%"
    assert fields["transaction_cost_pct"].value == "0.00"


def test_f19_n_a_rows_ignore_a_charge_from_the_next_column():
    fields, notes = costs(
        "What are the costs? For reference, the most recent OCR was 0.74%.",
        "Total costs N/A N/A N/A Impact on return (RIY) per year N/A N/A N/A Composition of costs\n"
        "Portfolio transaction costs N/A are incurred by the Company, as set out in the Company's latest annual report.\n"
        "Other ongoing costs N/A Company, including the OCR (also known as the \"Ongoing Charges Figure\")\n"
        "the most recent OCR was 0.74%.\nPerformance fees N/A\nHow long should I hold it")
    for name in ("ongoing_charge_pct", "charge_label", "transaction_cost_pct", "total_cost_pct"):
        assert fields[name].value == NOT_FOUND, name
    assert fields["ongoing_charge_pct"].quote == "Other ongoing costs N/A"  # shows it looked and found N/A
    assert notes == []


def test_f14_label_split_round_n_a_and_a_zero_total():
    fields, _ = costs(
        "What are the costs? Total costs £0 £0 £0 Impact on return (RIY) per year 0% 0% 0%",
        "Composition of costs\nNo portfolio transaction costs, relating to the buying and selling of\nPortfolio\n"
        "N/A investment manager. You should be aware that portfolio transaction\ntransaction costs\n"
        "Other ongoing\nN/A manager. You should be aware that management, advisory and\ncosts\nHow long should I hold it")
    assert fields["total_cost_pct"].value == "0"  # RIY 0% is printed, so it's recorded
    assert fields["transaction_cost_pct"].value == NOT_FOUND
    assert fields["ongoing_charge_pct"].value == NOT_FOUND


def test_f11_total_split_by_its_figures_is_not_found():
    fields, _ = costs(
        "What are the costs? Total costs N/A N/A Impact on return (RIY) per N/A N/A year Composition of costs\n"
        "Other ongoing costs N/A No other ongoing costs are payable directly by you\nHow long should I hold it")
    assert fields["total_cost_pct"].value == NOT_FOUND
    assert fields["total_cost_pct"].quote is None


def test_f09_label_completed_from_the_next_line():
    page = ("Composition of costs\nOther ongoing 0.8% The impact of the costs that are incurred each year for managing your\n"
            "costs investments and running the Company.\nHow long should I hold it")
    fields, notes = costs("What are the costs?", page)
    assert fields["charge_label"].value == "Other ongoing costs"
    assert fields["charge_label"].quote == ("Other ongoing 0.8% The impact of the costs that are incurred each year "
                                            "for managing your costs")
    assert notes == []


def test_label_that_cant_be_completed_is_not_found():
    page = "Composition of costs\nOther ongoing 0.8% The impact of the charges\ninvestments and running the Company.\nHow long should I hold it"
    fields, notes = costs("What are the costs?", page)
    assert fields["ongoing_charge_pct"].value == "0.8"
    assert fields["charge_label"].value == NOT_FOUND
    assert notes == ["Couldn't read the whole row label starting 'Other ongoing'."]


def test_total_cost_uses_the_last_column():
    # In all 14 KIDs the columns agree, but a new KID might not: the last column
    # is the recommended holding period.
    fields, _ = costs("What are the costs? Impact on return (RIY) per year 1.2% 1.1% 1.0%\nComposition of costs\nHow long should I hold it")
    assert fields["total_cost_pct"].value == "1.0"


def test_a_label_mention_without_a_figure_is_skipped_for_the_real_row():
    fields, _ = costs("What are the costs?",
                      "Composition of costs\nOther ongoing costs are explained below.\nPerformance fees N/A\n"
                      "Other ongoing costs year for managing your investments. 0.50%\nCarried interest N/A\nHow long should I hold it")
    assert fields["ongoing_charge_pct"].value == "0.50"


def test_n_a_wins_over_a_charge_in_the_rows_own_text():
    # data/README.md: if the line prints N/A, write not_found and put any other figure in the notes.
    fields, _ = costs("What are the costs?",
                      "Composition of costs\nOther ongoing costs N/A The OCR for the year to 31 March 2026 was 0.74%.\n"
                      "Performance fees N/A\nHow long should I hold it")
    assert fields["ongoing_charge_pct"].value == NOT_FOUND
    assert fields["charge_label"].value == NOT_FOUND


# --- charges given outside the cost row (Story 2.2, notes) --------------------------

from fundcrosschecker.common import Field  # noqa: E402


def elsewhere(pages, ongoing=Field(NOT_FOUND)):
    return kid._charges_elsewhere(pages, ongoing)


def test_f06_quote_starts_at_the_nearest_charge_word():
    page = ("The Ongoing Charges Ratio (OCR) represents the total operating expenses of the Company. The OCR shows the annual "
            "percentage reduction in the net asset value as a result of the costs of running the Company. "
            "The OCR for the year to 30 April 2025 was 0.77%. Other ongoing costs 0.00% The costs that we take")
    notes = elsewhere(["", "", page], Field("0.00", 3, "Other ongoing costs 0.00%"))
    assert notes == ['Charge given outside the cost row: 0.77% on page 3 ("OCR for the year to 30 April 2025 was 0.77%").']


@pytest.mark.parametrize("text, figure", [
    ("The most recent figure for 2025 was 0.73% with further information", "0.73"),                               # F10
    ("3BThe most recent published ongoing charges figure for the year ended 30 April 2026 was 0.67%.", "0.67"),    # F11
    ("For the year ending 31 May 2025, the annualised OCF was 1.35%. For the avoidance of doubt", "1.35"),         # F13
])
def test_charges_stated_in_a_sentence_are_noted(text, figure):
    notes = elsewhere(["", text])
    assert len(notes) == 1 and f"{figure}% on page 2" in notes[0]


def test_f14_both_operating_expense_ratios_are_noted():
    page = ("Ongoing Operating Expenses (exc. indirect fund management fees) Operating Expense Ratio (exc. indirect fund 1.03% "
            "management fees) Operating Expense Ratio (inc. indirect fund 1.10%")
    notes = elsewhere(["", "", "", page])
    assert [n.split(":")[1].split(" on")[0].strip() for n in notes] == ["1.03%", "1.10%"]


def test_f19_same_figure_on_two_pages_gives_one_note():
    notes = elsewhere(["", "For reference, the most recent OCR was 0.74%.", "the most recent OCR was 0.74%. As noted above"])
    assert notes == ['Charge given outside the cost row: 0.74% on page 2 ("OCR was 0.74%").']


@pytest.mark.parametrize("page, ongoing", [
    # F04: the description sentence is where the charge came from, so it isn't "elsewhere"
    ("incurred by the Company. The OCF for the year to 31 August 2025 was 1.52%.",
     Field("1.52", 1, "The OCF for the year to 31 August 2025 was 1.52%")),
    # F16: the stated charge is the one used
    ("Company Factsheet as an Ongoing Charge. The latest published Ongoing Charge for the Company was 0.45%.",
     Field("0.45", 1, "latest published Ongoing Charge for the Company was 0.45%")),
    # the used figure repeated in another sentence adds nothing
    ("Other ongoing costs 0.70% The impact. The OCF was 0.70% last year.", Field("0.70", 1, "Other ongoing costs 0.70%")),
])
def test_the_charge_already_used_is_not_noted_again(page, ongoing):
    assert elsewhere([page], ongoing) == []


@pytest.mark.parametrize("fund_id, figures", [
    ("F06", ["0.77%"]), ("F10", ["0.73%"]), ("F11", ["0.67%"]),
    ("F13", ["1.35%"]), ("F14", ["1.03%", "1.10%"]), ("F19", ["0.74%"]),
])
def test_real_kids_note_the_charge_given_outside_the_cost_row(fund_id, figures):
    pdf = PROJECT / "pdfs" / f"{fund_id}_kid.pdf"
    if not pdf.exists():
        pytest.skip(f"pdfs/{fund_id}_kid.pdf isn't here (PDFs aren't in the repo)")
    from fundcrosschecker.pdftext import read_pages

    _, notes = kid.extract(read_pages(pdf))
    noted = [note.split(": ")[1].split(" on page")[0] for note in notes if "outside the cost row" in note]
    assert noted == figures


# --- edge and invalid inputs ---------------------------------------------------------

@pytest.mark.parametrize("pages", [[""], ["   \n "], ["!!! ??? 123"], ["\x00\x00"], ["", "", ""]])
def test_pages_with_nothing_useful_give_not_found_without_crashing(pages):
    fields, _ = kid.extract(pages)
    assert {field.value for field in fields.values()} == {NOT_FOUND}


def test_no_pages_is_an_error():
    with pytest.raises(ValueError):
        kid.extract([])


def test_very_large_pages_are_read_quickly():
    import time
    pages = ["What are the costs? " + "Other ongoing costs 0.5% " * 20000] * 3  # about 1.5 MB of text
    start = time.time()
    kid.extract(pages)
    assert time.time() - start < 5  # no runaway pattern matching


# --- wordings added after the unseen-trusts run (1 Nov 2026), on each KID's real text -----

@pytest.mark.parametrize("line, name, share_class", [
    ("HgCapital Trust", "HgCapital Trust", NOT_FOUND),                                          # F20: ends "Trust"
    ("FIDELITY EUROPEAN TRUST PLC.", "FIDELITY EUROPEAN TRUST PLC.", NOT_FOUND),                # F26: full stop
    ("Product: RTW Biotech Opportunities Ltd", "RTW Biotech Opportunities Ltd", NOT_FOUND),     # F28: "Product:", "Ltd"
    ("Name Seraphim Space Investment Trust plc", "Seraphim Space Investment Trust plc", NOT_FOUND),  # F24: no colon
    ("FORESIGHT ENVIRONMENTAL INFRASTRUCTURE LIMITED – ORDINARY SHARES",
     "FORESIGHT ENVIRONMENTAL INFRASTRUCTURE LIMITED", "ORDINARY SHARES"),                      # F27
    ("HICL INFRASTRUCTURE PLC ORDINARY SHARES", "HICL INFRASTRUCTURE PLC", "ORDINARY SHARES"),  # F14: no separator
    ('BlackRock World Mining Trust plc (the "Fund"), Ordinary Shares (the "Shares"), ISIN: GB0005774855, is',
     "BlackRock World Mining Trust plc", "Ordinary Shares"),                                    # F23: after a bracket
    ("Namesake Investment Trust plc", "Namesake Investment Trust plc", NOT_FOUND),              # "Name" only as a whole word
])
def test_more_product_lines(line, name, share_class):
    notes = []
    name_field, share_field = kid._name_and_share_class(f"Purpose\nProduct\n{line}\nISIN: X", notes)
    assert (name_field.value, share_field.value) == (name, share_class)
    assert notes == []


def test_product_heading_in_capitals():  # F28's real order: the manufacturer line sits before the ISIN
    page = ("PURPOSE\nPRODUCT\nProduct: RTW Biotech Opportunities Ltd\nPRIIP Manufacturer: RTW Investments, LP\n"
            "ISIN: GG00BKTRRM22")
    name, _ = kid._name_and_share_class(page, [])
    assert name.value == "RTW Biotech Opportunities Ltd"


def test_share_class_alone_on_a_following_line():  # F25, with a bracket line in between
    page = 'Product\nJPMorgan American Investment Trust plc\n("The Company")\nOrdinary Shares\nGB00BKZGVH64'
    name, share = kid._name_and_share_class(page, [])
    assert name.value == "JPMorgan American Investment Trust plc"
    assert (share.value, share.quote) == ("Ordinary Shares", "Ordinary Shares")


@pytest.mark.parametrize("page", [
    "Product\nJPMorgan American Investment Trust plc\nGB00BKZGVH64\nOrdinary Shares",       # after the ISIN line
    "Product\nJPMorgan American Investment Trust plc\nContact details below\nOrdinary Shares",  # not the next line
    "Product\nJPMorgan American Investment Trust plc\nOrdinary Shares are traded on the LSE\nGB00BKZGVH64",  # a sentence
])
def test_share_class_on_a_later_line_only_when_it_stands_alone_before_the_isin(page):
    _, share = kid._name_and_share_class(page, [])
    assert share.value == NOT_FOUND


@pytest.mark.parametrize("page, name, share_class", [
    ("Purpose text\nFinsbury Growth & Income Trust PLC\nGB0007816068\nmore", "Finsbury Growth & Income Trust PLC", NOT_FOUND),  # F09
    ("The Law Debenture Corporation p.l.c.\nOrdinary shares in The Law Debenture Corporation p.l.c.\nIdentifier: GB0031429219",
     "The Law Debenture Corporation p.l.c.", "Ordinary shares"),                                                              # F12
    ("PURPOSE\nHICL INFRASTRUCTURE PLC ORDINARY SHARES\nISIN: GB00BJLP1Y77", "HICL INFRASTRUCTURE PLC", "ORDINARY SHARES"),     # F14
])
def test_without_the_heading_the_line_before_the_isin_is_used(page, name, share_class):
    name_field, share_field = kid._name_and_share_class(page, [])
    assert (name_field.value, share_field.value) == (name, share_class)


@pytest.mark.parametrize("page", [
    "PURPOSE\nHICL INFRASTRUCTURE PLC\nISIN: GB00BJLP1Y78",   # check digit wrong: not an ISIN
    "GB00BJLP1Y77\nHICL INFRASTRUCTURE PLC",                  # nothing before the ISIN
    "PURPOSE\nab\nGB00BJLP1Y77",                              # too short to be a name
])
def test_without_the_heading_or_a_line_before_a_real_isin_gives_not_found(page):
    name, share = kid._name_and_share_class(page, [])
    assert name.value == NOT_FOUND and share.value == NOT_FOUND


def test_two_columns_run_together_give_not_found_and_a_note():  # F29
    page = ("Purpose Product\nhelp you understand the nature, risks, costs, potential gains and losses of Product Name "
            "Ordinary Shares (EUR) (the \"product\")\nthis product and to help you compare it with other products.\n"
            "ISIN GG00B28C2R28")
    notes = []
    name, share = kid._name_and_share_class(page, notes)
    assert name.value == NOT_FOUND and share.value == NOT_FOUND
    assert notes and notes[0].startswith("Product line not understood")


def test_a_sentence_that_ends_like_a_name_is_too_long_to_be_one():
    # Ends with a real company ending ("Limited") and has no label, so only its length gives it away.
    line = "This document gives you key information about an investment company managed by Foo Fund Managers Limited"
    notes = []
    name, _ = kid._name_and_share_class(f"Product\n{line}", notes)
    assert name.value == NOT_FOUND and notes


@pytest.mark.parametrize("length, ok", [(80, True), (81, False)])
def test_the_longest_name_allowed(length, ok):
    line = "A" * (length - len(" Holdings plc")) + " Holdings plc"
    assert len(line) == length
    name, _ = kid._name_and_share_class(f"Product\n{line}", [])
    assert (name.value == line) == ok


def test_a_long_phrase_before_shares_in_isnt_a_share_class():
    _, share = kid._name_and_share_class("Product\nThis document is about shares in Some Trust plc", [])
    assert share.value == NOT_FOUND


def test_up_to_three_words_before_shares_in_is_a_share_class():
    name, share = kid._name_and_share_class("Product\nClass A Ordinary Shares in Some Trust plc", [])
    assert (name.value, share.value) == ("Some Trust plc", "Class A Ordinary Shares")


@pytest.mark.parametrize("text, iso", [
    ("This document is dated 25 May 2026", "2026-05-25"),                                    # F04
    ("This document is accurate at its production date 30 June 2026", "2026-06-30"),         # F05
    ("This Key Information Document is accurate as at 11 September 2025", "2025-09-11"),     # F06, F22
    ("Date of Production 29/12/2017", "2017-12-29"),                                         # F09: no colon
    ("The version date of this KID is 27 April 2026", "2026-04-27"),                         # F10
    ("Date of document production : 30 June 2026", "2026-06-30"),                            # F11
    ("Date of Publication: 01-04-2025", "2025-04-01"),                                       # F12
    ("Date of production of this document: 20 January 2026", "2026-01-20"),                  # F13, F28
    ("This key information document was produced on 31 July 20261 WHAT IS", "2026-07-31"),   # F14: footnote 1
    ("Date of production of the KID: 04/08/2026", "2026-08-04"),                             # F19
    ("Document published: 23/09/2026", "2026-09-23"),                                        # F21
    ("This Key Information Document is dated 06/03/2026", "2026-03-06"),                     # F24
    ("THIS DOCUMENT WAS PRODUCED ON 8 JANUARY 2026", "2026-01-08"),                          # F25: capitals
    ("Publication Date: 01-05-2026", "2026-05-01"),                                          # F26
    ("This key information document (KID) was produced on found at http://fgen.com 1 September 2025", "2025-09-01"),  # F27
    ("Last Updated On 05.10.2026", "2026-10-05"),                                            # F29
])
def test_each_kids_date_wording(text, iso):
    notes = []
    field = kid._doc_date(f"Product\nSome Trust plc\n{text}\nmore", notes)
    assert field.value == iso and notes == []
    assert field.quote in kid.normalise(text)  # the quote is printed text the quote check can find


@pytest.mark.parametrize("text", [
    "statement on forbearance in relation to investment trust disclosure requirements dated 19 September 2024",  # F14: not the KID's date
    "Date of Production: see our website, where every document we publish is listed 1 September 2025",  # more than 40 characters in between
    "This key information document was produced on page 2 1 September 2025",  # a number in between
    "This key information document was produced on 31 July 202612",  # two digits after the year
    "Date of Production: 2026-06-08",                                 # year first isn't how KIDs print it
    "Our document is dated soon",                                      # no date at all
])
def test_dates_that_arent_the_kids_own_give_not_found(text):
    assert kid._doc_date(text, []).value == NOT_FOUND


def test_a_space_before_the_percent_sign():  # F27, F28
    fields, _ = costs("What are the costs? Composition of costs Portfolio transaction costs 0 % underlying "
                      "investments. Other ongoing costs 0.00 % The impact. How long should I hold it")
    assert fields["transaction_cost_pct"].value == "0"
    assert fields["ongoing_charge_pct"].value == "0.00"


@pytest.mark.parametrize("row, value", [
    ("Impact on return each year 1.79% 1.79% 1.79%", "1.79"),            # F24
    ("Reduction in Yield (RIY) per year 0.00 % 0.00 %", "0.00"),         # F28
    ("Impact on return (RIY) per year 0% 0% N/A", NOT_FOUND),            # the last column decides
])
def test_more_total_cost_wordings(row, value):
    fields, _ = costs(f"What are the costs? Total costs £0 £0 {row} Composition of costs Entry costs 0% "
                      "How long should I hold it")
    assert fields["total_cost_pct"].value == value


def test_composition_heading_in_any_case():  # F28: "Composition of Costs"
    # Only a transaction row, so it's the heading alone that marks this as a cost table.
    fields, notes = costs("What are the costs? Composition of Costs Portfolio transaction costs 0.10 % The impact. "
                          "How long should I hold it")
    assert fields["transaction_cost_pct"].value == "0.10"
    assert "No cost table" not in " ".join(notes)


def test_a_cost_table_without_its_heading():  # F20
    fields, notes = costs("What are the costs? Total costs £0 £0 £0 Impact on return (RIY) per year 0% 0% 0% "
                          "Entry costs N/A There is no charge. Portfolio transaction costs N/A investments. "
                          "Other ongoing costs N/A investments. How long should I hold it")
    assert fields["total_cost_pct"].value == "0"
    assert fields["transaction_cost_pct"].value == NOT_FOUND
    assert fields["ongoing_charge_pct"].value == NOT_FOUND
    assert notes == []


def test_rows_without_the_heading_are_read_with_their_figures():
    fields, _ = costs("What are the costs? Entry costs 0% None. Portfolio transaction costs 0.10% investments. "
                      "Other ongoing costs 0.50% The impact. How long should I hold it")
    assert fields["transaction_cost_pct"].value == "0.10"
    assert (fields["ongoing_charge_pct"].value, fields["charge_label"].value) == ("0.50", "Other ongoing costs")


def test_no_table_ongoing_charges_figure_with_the_description_mixed_in():  # F26
    fields, notes = costs("What are the costs? The Ongoing Charges figure stated below is taken from the Company's most "
                          "recent Annual Report and represents the total of investment management fees and other expenses "
                          "of the Company. Ongoing Charges figure for the year to 31 These are expenses incurred by the "
                          "Company and no 0.73% December 2025 additional charge. Ongoing Charges figure including fee "
                          "waived These are expenses 0.59% for the year. How long should I hold it")
    assert fields["ongoing_charge_pct"].value == "0.73"
    assert fields["charge_label"].value == "Ongoing Charges figure"
    assert fields["ongoing_charge_pct"].quote.startswith("Ongoing Charges figure for the year to 31")
    assert notes == ["No cost table: ongoing charge taken from the cost section."]


@pytest.mark.parametrize("text", [
    "Ongoing Charges figure, see the annual report. Ongoing Charge history is on the website. 0.73%",  # runs into another charge
    "Ongoing Charges figure, see the annual report, Ongoing Charge history on the website 0.73%",  # the same, no sentence end
    "Ongoing Charges figure " + "and more words " * 10 + "0.73%",                                       # too far away
])
def test_no_table_charge_too_far_away_or_past_another_charge_is_not_used(text):
    fields, _ = costs(f"What are the costs? {text} How long should I hold it")
    assert fields["ongoing_charge_pct"].value == NOT_FOUND


def test_label_completed_two_lines_down():  # F28: the figure and description sit in between
    page = ("What are the costs?\nComposition of Costs\nOngoing costs\nOther ongoing\n"
            "0.00 % The impact of the costs for managing your investment.\ncosts\nHow long should I hold it")
    fields, notes = costs(page)
    assert fields["charge_label"].value == "Other ongoing costs"
    assert fields["charge_label"].quote == "Other ongoing 0.00 % The impact of the costs for managing your investment. costs"
    assert fields["charge_label"].quote in kid.normalise(page)


def test_label_not_completed_three_lines_down():
    page = ("What are the costs?\nComposition of costs\nOther ongoing\n0.00 % The impact\nof the costs\ncosts\n"
            "How long should I hold it")
    fields, notes = costs(page)
    assert fields["charge_label"].value == NOT_FOUND
    assert any("Couldn't read the whole row label" in note for note in notes)


# --- from the code review of 1 Nov 2026 --------------------------------------------------

@pytest.mark.parametrize("page, name", [
    ("Key Information Document\nPRIIP Manufacturer: Foo Fund Managers Limited\nFoo Growth Trust plc ISIN: GB00BS88V647",
     "Foo Growth Trust plc"),                                   # the name is on the ISIN line itself
    ("Key Information Document\nPRIIP Manufacturer: Foo Fund Managers Limited\nISIN: GB00BS88V647", NOT_FOUND),
    ("Key Information Document\nManufacturer Foo Fund Managers Limited\nGB00BS88V647", NOT_FOUND),
    ("Key Information Document\nWhat is this product?\nThe Company invests in Bar Holdings plc\nGB00BS88V647", NOT_FOUND),
])
def test_without_the_heading_a_manufacturer_or_a_later_sentence_isnt_the_name(page, name):
    assert kid._name_and_share_class(page, [])[0].value == name


@pytest.mark.parametrize("line", [
    "The Company is an investment trust",   # "trust" without its capital
    "Antitrust",                            # the same, inside a word
    "Holding period unlimited",             # "limited" not as a whole word
    "Shares: Foo Growth Trust plc",         # still a labelled detail
])
def test_lines_that_only_seem_to_end_like_a_company(line):
    notes = []
    assert kid._name_and_share_class(f"Product\n{line}", notes)[0].value == NOT_FOUND
    assert notes


@pytest.mark.parametrize("line, name, share_class", [
    ("Foo Growth Trust ORDINARY SHARES", "Foo Growth Trust", "ORDINARY SHARES"),
    ("Foo Growth p.l.c ORDINARY SHARES", "Foo Growth p.l.c", "ORDINARY SHARES"),
])
def test_share_class_after_every_kind_of_company_ending(line, name, share_class):
    name_field, share_field = kid._name_and_share_class(f"Product\n{line}", [])
    assert (name_field.value, share_field.value) == (name, share_class)


@pytest.mark.parametrize("text", [
    "The latest published Ongoing Charge for the Company was 0.74%. Details of the composition of costs are in "
    "the annual report.",                                       # "composition of costs" in a sentence
    "The latest published Ongoing Charge for the Company was 0.74%. Entry costs 0% apply.",  # one row alone
])
def test_a_mention_of_a_table_doesnt_hide_the_stated_charge(text):
    # The yearly total is there too, as in every KID: if the text were taken for a table,
    # the total alone would be read and the stated charge never looked for.
    fields, notes = costs(f"What are the costs? Annual cost impact (*) 1.0% 1.0% each year. {text} "
                          "How long should I hold it")
    assert fields["ongoing_charge_pct"].value == "0.74"
    assert notes == ["No cost table: ongoing charge taken from the cost section."]


def test_without_the_heading_the_table_starts_at_its_first_row():
    fields, _ = costs("What are the costs? Impact on return (RIY) per year 1.2% 1.2% Portfolio managers are paid from "
                      "the fund. 1.2% Entry costs 0% None. Other ongoing costs 0.50% x. How long should I hold it")
    assert fields["transaction_cost_pct"].value == NOT_FOUND   # the sentence before the table isn't a row
    assert fields["ongoing_charge_pct"].value == "0.50"


def test_without_the_heading_or_an_entry_or_exit_row_nothing_is_read_as_a_row():
    # Rows of two kinds make it a table, but with no heading and no entry or exit row there's
    # no safe place to start it, so a sentence ("Portfolio managers ... 1.2%") isn't read as
    # the transaction row. Missing rather than wrong: the other rows are lost too.
    fields, _ = costs("What are the costs? Portfolio managers are paid from the fund. 1.2% a year. "
                      "Performance fees 0% Other ongoing costs 0.50% x. How long should I hold it")
    assert fields["transaction_cost_pct"].value == NOT_FOUND


@pytest.mark.parametrize("text", [
    "Date of Production: 8/6/2026",      # one-digit day and month: not a form the checks know
    "Last Updated On 5.10.2026",
    "Date of Production: 08/06-2026",     # two kinds of separator
])
def test_dates_the_checks_wouldnt_accept_arent_read(text):
    assert kid._doc_date(text, []).value == NOT_FOUND


@pytest.mark.parametrize("text, value", [
    ("Ongoing Charges figure for the year to 31 December 2025 is shown on page 2; 3 % of the fund.", NOT_FOUND),
    ("Ongoing Charges figure for 2025 is in the report. Fees 0.73%", NOT_FOUND),   # past a sentence end
    ("ONGOING CHARGES FIGURE 0.73%", "0.73"),                                      # capitals
])
def test_no_table_charge_stays_in_its_sentence_and_ignores_case(text, value):
    fields, _ = costs(f"What are the costs? {text} How long should I hold it")
    assert fields["ongoing_charge_pct"].value == value


def test_charges_with_a_space_before_the_percent_sign_are_read_and_noted():
    assert kid._charges_elsewhere(["The OCF was 1.74 % for 2025"], kid.Field(NOT_FOUND)) == [
        'Charge given outside the cost row: 1.74% on page 1 ("OCF was 1.74 %").']
    fields, _ = costs("What are the costs? The latest published Ongoing Charge for the Company was 0.74 %. "
                      "How long should I hold it")
    assert fields["ongoing_charge_pct"].value == "0.74"


def test_label_not_completed_from_a_sentence_two_lines_down():
    page = "Other ongoing\n0.40% Fees for the year\ncosts of running the company are high"
    notes = []
    assert kid._full_label("Other ongoing", page, 1, notes).value == NOT_FOUND
    assert notes


def test_described_charge_with_a_space_before_the_percent_sign():  # F04's layout, "1.52 %"
    fields, _ = costs("What are the costs? Composition of costs\nManagement fees and other No fees are payable; these "
                      "are 152 GBP\nadministrative or operating costs. The OCF for the year to 31 August 2025 was 1.52 %.\n"
                      "How long should I hold it")
    assert (fields["ongoing_charge_pct"].value, fields["charge_label"].value) == ("1.52", "OCF")


def test_a_heading_with_no_readable_rows_falls_back_to_the_stated_charge():
    fields, notes = costs("What are the costs? Composition of costs: see the annual report. The latest published "
                          "Ongoing Charge for the Company was 0.74%. How long should I hold it")
    assert fields["ongoing_charge_pct"].value == "0.74"
    assert notes == ["No cost table: ongoing charge taken from the cost section."]
