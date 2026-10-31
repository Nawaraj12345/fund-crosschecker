"""Tests for the trust KID extractor.

The end-to-end test needs pdfs/F16_kid.pdf. The PDFs aren't in the repo
(copyright), so it's skipped when the file isn't there.
"""

import csv
from pathlib import Path

import pytest

from fundcrosscheck import kid
from fundcrosscheck.common import NOT_FOUND

PROJECT = Path(__file__).resolve().parent.parent
F16 = PROJECT / "pdfs" / "F16_kid.pdf"


def answer_key_row(fund_id):
    with (PROJECT / "data" / "answer_key.csv").open(encoding="utf-8") as f:
        return next(r for r in csv.DictReader(f) if r["fund_id"] == fund_id and r["doc_type"] == "kid")


@pytest.mark.skipif(not F16.exists(), reason="pdfs/F16_kid.pdf isn't here (PDFs aren't in the repo)")
def test_f16_matches_the_answer_key():
    from fundcrosscheck.pdftext import read_pages

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


def test_cost_section_carries_over_the_page():  # F19: heading on page 2, table on page 3
    pages = ["page 1", "What are the costs? Costs over time ...", "Composition of costs ... How long should I hold it"]
    notes = []
    costs = kid._costs(pages, notes)
    assert all(field.value == NOT_FOUND for field in costs.values())
    assert notes == ["Cost table not read yet (Story 2.2, step 4): ongoing, transaction and total cost left as not_found."]


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
