"""Tests for a charge label whose bracket wraps onto the line below (labelwrap.py)."""

import csv
from datetime import date
from pathlib import Path

import pytest

import fundcrosschecker.__main__ as cli
from fundcrosschecker import labelwrap
from fundcrosschecker.checks import check_fields
from fundcrosschecker.common import NOT_FOUND, Field

PROJECT = Path(__file__).resolve().parent.parent


def line(top, *words, height=7.0):
    """pdfplumber-style words on one line: each given as (text, x0, x1)."""
    return [{"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + height} for text, x0, x1 in words]


# F03 factsheet, page 1, positions as pdfplumber gives them.
F03 = (line(317.4, ("Ongoing", 31.2, 57.9), ("Charges", 60.0, 85.7), ("Figure", 87.8, 106.8),
            ("(OCF)", 108.9, 126.5), ("per", 128.6, 139.0), ("year", 141.1, 154.8))
       + line(321.6, ("0.12%", 173.3, 189.3), ("(28.02.26)", 191.4, 219.4))
       + line(325.9, ("(fixed):", 31.2, 52.7))
       + line(334.5, ("OCF", 31.2, 44.2), ("takes", 46.3, 62.5), ("into", 64.6, 76.1)))
F03_LABEL = "Ongoing Charges Figure (OCF) per year"

# F24 factsheet, page 4: the bracket takes two lines, with another column to each side.
F24 = (line(224.5, ("July", 251.4, 266.0), ("2021", 267.5, 284.9), ("Ongoing", 295.4, 326.1),
            ("charges", 328.0, 357.6), ("ratio", 359.4, 375.7), ("1.36%", 436.9, 459.4),
            ("(ordinary", 460.9, 491.6), ("shares)", 493.1, 518.6), height=8.0)
       + line(236.6, ("May", 249.6, 264.7), ("2026", 266.3, 284.9), ("(for", 295.4, 307.7), ("12", 309.5, 317.5),
              ("months", 319.3, 347.2), ("ended", 349.0, 371.6), ("1.56%", 460.6, 482.6), ("(C", 484.2, 491.6),
              height=8.0)
       + line(248.7, ("30", 295.4, 305.4), ("June", 307.2, 325.2), ("2026)", 327.1, 348.2), height=8.0))


def test_a_bracket_on_the_next_line():
    assert labelwrap.wrapped_bracket(F03, F03_LABEL, "0.12") == "(fixed)"  # the colon after it isn't kept


def test_a_bracket_over_two_lines_between_other_columns():
    assert labelwrap.wrapped_bracket(F24, "Ongoing charges ratio", "1.36") == "(for 12 months ended 30 June 2026)"


def test_a_footnote_letter_on_the_label_still_finds_it():
    page = line(100, ("Ongoing", 10, 40), ("chargesD", 42, 75), ("0.50%", 120, 140)) + line(109, ("(2025)", 10, 30))
    assert labelwrap.wrapped_bracket(page, "Ongoing charges", "0.50") == "(2025)"


@pytest.mark.parametrize("mark", ["•", "–", ""])
def test_a_bullet_before_the_label_isnt_a_second_place(mark):
    page = line(317.4, (mark, 20.0, 26.0)) + F03
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") == "(fixed)"


def test_no_bracket_under_the_label():
    page = F03[:8] + line(325.9, ("Fixed", 31.2, 52.7))
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") is None


@pytest.mark.parametrize("x0, top", [
    (34.5, 325.9),   # starts 3.3 points right of the label's edge: another column
    (29.0, 325.9),   # or left of it
    (31.2, 340.0),   # more than two line heights below: a later row, not a wrapped line
])
def test_a_bracket_away_from_the_label_isnt_taken(x0, top):
    page = F03[:8] + line(top, ("(fixed):", x0, x0 + 21.5))
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") is None


def test_a_bracket_right_of_the_figures_edge_isnt_in_the_labels_column():
    page = F03[:8] + line(325.9, ("(fixed", 31.2, 52.7), ("and", 54, 70), ("more", 160, 180), ("words)", 182, 200))
    # "more words)" reach past the figure's edge (173.3), so the bracket can't close in the label's column
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") is None


def test_a_bracket_that_doesnt_close_within_three_lines():
    page = (F03[:8] + line(325.9, ("(a", 31.2, 40)) + line(333, ("b", 31.2, 40))
            + line(340, ("c", 31.2, 40)) + line(347, ("d)", 31.2, 40)))
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") is None
    closes_on_the_third = page[:-2] + line(340, ("c)", 31.2, 40))
    assert labelwrap.wrapped_bracket(closes_on_the_third, F03_LABEL, "0.12") == "(a b c)"


def test_the_label_must_have_its_figure_beside_it_and_only_once():
    assert labelwrap.wrapped_bracket(F03, F03_LABEL, "0.13") is None  # another figure: not this label's place
    twice = F03 + [dict(word, top=word["top"] + 200, bottom=word["bottom"] + 200) for word in F03]
    assert labelwrap.wrapped_bracket(twice, F03_LABEL, "0.12") is None  # two places: unsure which


@pytest.mark.parametrize("text, ok", [("0.12%", True), ("0.12", True), ("0.12 %", True),
                                      ("10.12%", False), ("0.123%", False), ("0.12%)", False)])
def test_is_figure(text, ok):
    assert labelwrap.is_figure(text, "0.12") == ok


# --- extend_label: the label in the fields ------------------------------------------------

F03_TEXT = ("Ongoing Charges Figure (OCF) per year 0.12% (28.02.26) GBP Index\n"
            "(fixed): >10bn 98.0\nOCF takes into account annual 5-10bn 1.7")


class FakePdf:
    def __init__(self, page_words):
        self.pages = [type("Page", (), {"extract_words": lambda self: page_words})()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def f03_fields(label=F03_LABEL, charge="0.12"):
    return {"ongoing_charge_pct": Field(charge, 1, "0.12%"),
            "charge_label": Field(label, 1, "Ongoing Charges Figure (OCF) per year 0.12% (28.02.26)")}


def test_extend_label(monkeypatch):
    monkeypatch.setattr(labelwrap.pdfplumber, "open", lambda path: FakePdf(F03))
    fields, notes = f03_fields(), []
    labelwrap.extend_label(fields, notes, Path("F03_factsheet.pdf"), [F03_TEXT])
    assert fields["charge_label"] == Field(f"{F03_LABEL} (fixed)", 1,
                                           "Ongoing Charges Figure (OCF) per year 0.12% (28.02.26) GBP Index (fixed):")
    assert notes == [f"charge_label: '(fixed)' added, printed under '{F03_LABEL}' on page 1 (the label wraps onto the next line)."]
    # The longer label passes the checks on its own, as any answer must.
    check_fields(fields, [F03_TEXT], notes := [], date(2026, 11, 1))
    assert fields["charge_label"].value == f"{F03_LABEL} (fixed)" and notes == []


@pytest.mark.parametrize("fields", [
    f03_fields(label=NOT_FOUND),            # no label to add to
    f03_fields(charge=NOT_FOUND),           # no figure, so no label either
    f03_fields(label=f"{F03_LABEL} (fixed)"),  # the answer already has the bracket
    {"ongoing_charge_pct": Field("0.12", 1, "0.12%"), "charge_label": Field(F03_LABEL)},  # no page
    {},                                     # a document type without these fields
])
def test_extend_label_leaves_these_alone(monkeypatch, fields):
    monkeypatch.setattr(labelwrap.pdfplumber, "open", lambda path: FakePdf(F03))
    before, notes = dict(fields), []
    labelwrap.extend_label(fields, notes, Path("F03_factsheet.pdf"), [F03_TEXT])
    assert fields == before and notes == []


def test_a_bracket_with_no_quote_on_the_page_is_left_out(monkeypatch):
    # The layout shows the bracket, but the page text doesn't hold it after the label's quote.
    monkeypatch.setattr(labelwrap.pdfplumber, "open", lambda path: FakePdf(F03))
    text = "Ongoing Charges Figure (OCF) per year 0.12% (28.02.26) GBP Index"
    fields, notes = f03_fields(), []
    labelwrap.extend_label(fields, notes, Path("F03_factsheet.pdf"), [text])
    assert fields["charge_label"].value == F03_LABEL
    assert notes and "left as" in notes[0]


def test_an_unreadable_pdf_leaves_the_label(monkeypatch):
    def broken(path):
        raise ValueError("not a PDF")
    monkeypatch.setattr(labelwrap.pdfplumber, "open", broken)
    fields, notes = f03_fields(), []
    labelwrap.extend_label(fields, notes, Path("F03_factsheet.pdf"), [F03_TEXT])
    assert fields["charge_label"].value == F03_LABEL
    assert notes == ["The charge label's layout couldn't be read (ValueError)."]


def test_joining_quote():
    page = "Ongoing charges ratio 1.36% (ordinary shares) C share issue 12 May 2026 (for 12 months ended 1.56% (C shares) 30 June 2026) Next"
    label = "Ongoing charges ratio (for 12 months ended 30 June 2026)"
    assert labelwrap.joining_quote(page, "Ongoing charges ratio 1.36% (ordinary shares)", label) == page[:-5]
    assert labelwrap.joining_quote(page, "not on the page", label) is None
    assert labelwrap.joining_quote(page, "", label) is None
    assert labelwrap.joining_quote(page, "Ongoing charges ratio", label + " (more)") is None


@pytest.mark.parametrize("doc_type, read", [("factsheet", True), ("kid", False), ("kiid", False)])
def test_which_documents_use_it(tmp_path, monkeypatch, doc_type, read):
    (tmp_path / f"F01_{doc_type}.pdf").write_bytes(b"%PDF fake")
    monkeypatch.setattr(cli, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(cli, "read_pages", lambda path: ["page one"])
    monkeypatch.setattr(cli.riskscale, "fill_from_graphic", lambda fields, notes, path: None)
    calls = []
    monkeypatch.setattr(labelwrap, "extend_label", lambda fields, notes, path, pages: calls.append((path.name, pages)))
    cli.extract_all([tmp_path], doc_type, lambda pages, sha: ({"fund_name": Field(NOT_FOUND)}, []))
    assert calls == ([(f"F01_{doc_type}.pdf", ["page one"])] if read else [])


# --- the real documents ------------------------------------------------------------------

@pytest.mark.parametrize("path, page, label, figure, expected", [
    ("pdfs/F03_factsheet.pdf", 1, F03_LABEL, "0.12", "(fixed)"),
    ("pdfs/F04_factsheet.pdf", 1, "Ongoing charges", "1.12", "(year end 31 Aug 2025)"),
    ("pdfs/F11_factsheet.pdf", 3, "Ongoing Charges", "0.67", "(30 April 2026)"),
    ("pdfs/unseen/F24_factsheet.pdf", 4, "Ongoing charges ratio", "1.36", "(for 12 months ended 30 June 2026)"),
    ("pdfs/unseen/F21_factsheet.pdf", 2, "Ongoing charges", "0.50", None),   # footnote D, nothing wrapped
    ("pdfs/F10_factsheet.pdf", 2, "OCF", "0.73", None),
])
def test_real_documents(path, page, label, figure, expected):
    import pdfplumber
    pdf = PROJECT / path
    if not pdf.exists():
        pytest.skip(f"{path} isn't here (PDFs aren't in the repo)")
    with pdfplumber.open(pdf) as document:
        assert labelwrap.wrapped_bracket(document.pages[page - 1].extract_words(), label, figure) == expected


@pytest.mark.slow
def test_on_every_factsheet_it_only_adds_what_the_answer_key_has():
    """For each factsheet's keyed label, with any bracket taken off, the reader may add
    nothing or exactly the key's bracket, on every page. Pins where it fires: F03, F04,
    F11 and F24, the four keyed with a bracket printed under the label."""
    import re

    import pdfplumber
    rows = []
    for key in (PROJECT / "data" / "answer_key.csv", PROJECT / "data" / "unseen" / "answer_key.csv"):
        with key.open(encoding="utf-8") as f:
            rows += [r for r in csv.DictReader(f) if r["doc_type"] == "factsheet" and r["charge_label"] != NOT_FOUND]
    fired = set()
    for row in rows:
        folder = "unseen/" if int(row["fund_id"][1:]) >= 20 else ""
        pdf = PROJECT / "pdfs" / f"{folder}{row['fund_id']}_factsheet.pdf"
        if not pdf.exists():
            pytest.skip("the PDFs aren't here")
        base = re.sub(r" \([^()]*\)$", "", row["charge_label"])
        with pdfplumber.open(pdf) as document:
            for page in document.pages:
                bracket = labelwrap.wrapped_bracket(page.extract_words(), base, row["ongoing_charge_pct"])
                if bracket:
                    assert f"{base} {bracket}" == row["charge_label"], row["fund_id"]
                    fired.add(row["fund_id"])
    assert fired == {"F03", "F04", "F11", "F24"}
