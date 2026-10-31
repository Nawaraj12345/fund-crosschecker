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
