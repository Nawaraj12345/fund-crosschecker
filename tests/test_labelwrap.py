"""Tests for a charge label whose bracket wraps onto the line below (labelwrap.py)."""

import csv
from datetime import date
from pathlib import Path

import pytest

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
    page = line(100, ("Ongoing", 10, 40), ("chargesD", 42, 75), ("0.50%", 120, 140)) + line(109, ("(fixed)", 10, 30))
    assert labelwrap.wrapped_bracket(page, "Ongoing charges", "0.50") == "(fixed)"


@pytest.mark.parametrize("mark", ["•", "–", ""])
def test_a_bullet_before_the_label_isnt_a_second_place(mark):
    page = line(317.4, (mark, 20.0, 26.0)) + F03
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") == "(fixed)"


@pytest.mark.parametrize("text", ["Fixed", ")ab(", ")(fixed"])
def test_no_bracket_under_the_label(text):
    page = F03[:8] + line(325.9, (text, 31.2, 52.7))
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
    page = (F03[:8] + line(325.9, ("(ab", 31.2, 40)) + line(333, ("cd", 31.2, 40))
            + line(340, ("ef", 31.2, 40)) + line(347, ("gh)", 31.2, 40)))
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") is None
    closes_on_the_third = page[:-2] + line(340, ("ef)", 31.2, 40))
    assert labelwrap.wrapped_bracket(closes_on_the_third, F03_LABEL, "0.12") == "(ab cd ef)"


def test_the_label_must_have_its_figure_beside_it_and_only_once():
    assert labelwrap.wrapped_bracket(F03, F03_LABEL, "0.13") is None  # another figure: not this label's place
    twice = F03 + [dict(word, top=word["top"] + 200, bottom=word["bottom"] + 200) for word in F03]
    assert labelwrap.wrapped_bracket(twice, F03_LABEL, "0.12") is None  # two places: unsure which


@pytest.mark.parametrize("text, ok", [("0.12%", True), ("0.12", True), ("0.12%†", True), ("0.12%*", True),
                                      ("0.12%**", True), ("10.12%", False), ("0.123%", False),
                                      ("0.12%)", False), ("0.12%***", False), ("0.12%1", False)])
def test_is_figure(text, ok):
    assert labelwrap.is_figure(text, "0.12") == ok


# --- from the code review of 1 Nov 2026: layouts that must give nothing (or the right thing) ---

LABEL_ROW = line(100, ("Ongoing", 10, 40), ("charges", 42, 70), ("0.50%", 120, 140))


def test_words_on_one_line_are_read_left_to_right():
    # "12" sits a tenth of a point lower than its neighbours (another font): still one line, in order.
    page = F03[:8] + line(325.9, ("(for", 31.2, 45), ("months):", 60, 90)) + line(326.0, ("12", 47, 55))
    assert labelwrap.wrapped_bracket(page, F03_LABEL, "0.12") == "(for 12 months)"


def test_the_figure_must_be_the_next_word_beside_the_label():
    # "Ongoing charges | Class A | 0.50%": the column between them makes the label's own column unclear.
    page = (line(100, ("Ongoing", 10, 40), ("charges", 42, 70), ("Class", 80, 95), ("A", 97, 100), ("0.50%", 120, 140))
            + line(109, ("(incl.", 10, 30), ("(as", 80, 92)) + line(118, ("fees)", 10, 30), ("at)", 80, 92)))
    assert labelwrap.wrapped_bracket(page, "Ongoing charges", "0.50") is None


def test_a_word_running_past_the_figures_edge_stops_it():
    page = (LABEL_ROW + line(109, ("(year", 10, 30), ("end", 32, 50), ("2025)", 100, 125))
            + line(118, ("Entry", 10, 30), ("charge", 32, 60), ("none)", 62, 80)))
    assert labelwrap.wrapped_bracket(page, "Ongoing charges", "0.50") is None


def test_a_row_with_its_own_figure_isnt_the_labels_wrap():
    page = LABEL_ROW + line(109, ("(incl.", 10, 30), ("performance", 32, 70), ("fee)", 72, 85), ("0.75%", 120, 140))
    assert labelwrap.wrapped_bracket(page, "Ongoing charges", "0.50") is None
    # F24's other class: a figure on a line the bracket only passes through is fine.
    assert labelwrap.wrapped_bracket(F24, "Ongoing charges ratio", "1.36") == "(for 12 months ended 30 June 2026)"


@pytest.mark.parametrize("words", [
    [("(1)", 10, 20), ("Source:", 22, 50), ("Morningstar", 52, 100)],   # a footnote list under the last row
    [("(*)", 10, 20), ("Source:", 22, 50)],
    [("(1)", 10, 20)],                                                  # a footnote mark on its own
])
def test_a_footnote_line_isnt_a_bracket(words):
    assert labelwrap.wrapped_bracket(LABEL_ROW + line(109, *words), "Ongoing charges", "0.50") is None


def test_a_bracket_with_more_of_the_cell_after_it_isnt_cut_short():
    page = LABEL_ROW + line(109, ("(fixed)", 10, 30), ("per", 32, 45), ("annum", 47, 70))
    assert labelwrap.wrapped_bracket(page, "Ongoing charges", "0.50") is None


def test_a_label_quote_printed_earlier_on_the_page_too():
    earlier = "The Ongoing Charges are explained in the glossary. " + "x " * 250
    page = earlier + "Ongoing Charges 0.67% London W1K 4BP (30 April 2026)"
    label = "Ongoing Charges (30 April 2026)"
    assert labelwrap.joining_quote(page, "Ongoing Charges", label) == "Ongoing Charges 0.67% London W1K 4BP (30 April 2026)"


def test_line_grouping_is_done_once_and_scales():
    import time
    page = [w for i in range(60) for w in line(i * 9.0, *[(f"word{i}x{j}", 10 + j * 11, 19 + j * 11) for j in range(50)])]
    page += line(600, ("Ongoing", 10, 40), ("charges", 42, 70), ("0.5%", 300, 320)) + line(608, ("(fixed)", 10, 30))
    start = time.perf_counter()
    assert labelwrap.wrapped_bracket(page, "Ongoing charges", "0.5") == "(fixed)"
    assert time.perf_counter() - start < 1.0  # 3,004 words


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
    f03_fields(label=f"{F03_LABEL} (fixed)"),  # already has it: its words aren't all on one line, so no place
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


# --- confirm_claimed_bracket: a bracket Claude gave but quoted only in part (F04) ------------

F04_WORDS = (line(428.0, ("Ongoing", 650, 680), ("charges", 682, 712)) + line(432.0, ("1.12%", 740, 760))
             + line(437.0, ("(year", 650, 668), ("end", 670, 684), ("31", 686, 695), ("Aug", 697, 711), ("2025)", 713, 732))
             + line(452.0, ("Benchmark", 650, 690), ("-", 740, 744)))
F04_TEXT = "Ongoing charges 1.12%\n(year end 31 Aug 2025)\nBenchmark -"
F04_LABEL = "Ongoing charges (year end 31 Aug 2025)"


def f04_fields(label=F04_LABEL, quote="Ongoing charges", page=1):
    return {"ongoing_charge_pct": Field("1.12", 1, "1.12%"), "charge_label": Field(label, page, quote)}


def confirm_then_check(monkeypatch, fields, page_words=F04_WORDS, text=F04_TEXT):
    monkeypatch.setattr(labelwrap.pdfplumber, "open", lambda path: FakePdf(page_words))
    notes = []
    labelwrap.confirm_claimed_bracket(fields, notes, Path("F04_factsheet.pdf"), [text])
    check_fields(fields, [text], notes, date(2026, 11, 1))
    return notes


def test_a_claimed_bracket_the_layout_shows_is_kept(monkeypatch):
    fields = f04_fields()
    notes = confirm_then_check(monkeypatch, fields)
    assert fields["charge_label"] == Field(F04_LABEL, 1, "Ongoing charges 1.12% (year end 31 Aug 2025)")
    assert notes == ["charge_label: the quote was lengthened to hold '(year end 31 Aug 2025)', which is printed "
                     "under 'Ongoing charges' on page 1 (the label wraps onto the next line)."]


def test_without_it_the_checks_remove_the_label(monkeypatch):
    fields, notes = f04_fields(), []
    check_fields(fields, [F04_TEXT], notes, date(2026, 11, 1))
    assert fields["charge_label"].value == NOT_FOUND


@pytest.mark.parametrize("fields, page_words", [
    (f04_fields(label="Ongoing charges (year end 31 Aug 2024)"), F04_WORDS),   # the layout shows another bracket
    (f04_fields(), F04_WORDS[:3]),                                             # no bracket under the label
    (f04_fields(quote="Charges 1.12%"), F04_WORDS),                            # the quote lacks even "Ongoing"
    (f04_fields(quote="not on the page"), F04_WORDS),                          # the quote isn't on the page
    (f04_fields(page=2), F04_WORDS),                                           # no such page
])
def test_a_claim_the_layout_doesnt_back_is_still_removed(monkeypatch, fields, page_words):
    notes = confirm_then_check(monkeypatch, fields, page_words)
    assert fields["charge_label"].value == NOT_FOUND
    assert not any("lengthened" in note for note in notes)


@pytest.mark.parametrize("fields", [
    f04_fields(label="Ongoing charges"),                                       # no bracket claimed
    f04_fields(quote="Ongoing charges 1.12% (year end 31 Aug 2025)"),          # the quote already holds it all
    f04_fields(label=NOT_FOUND),
    {"ongoing_charge_pct": Field(NOT_FOUND), "charge_label": Field(F04_LABEL, 1, "Ongoing charges")},
    {},
])
def test_confirm_leaves_these_alone(monkeypatch, fields):
    def no_pdf(path):
        raise AssertionError("the layout shouldn't be read")
    monkeypatch.setattr(labelwrap.pdfplumber, "open", no_pdf)
    before, notes = dict(fields), []
    labelwrap.confirm_claimed_bracket(fields, notes, Path("F04_factsheet.pdf"), [F04_TEXT])
    assert fields == before and notes == []


def test_confirm_with_an_unreadable_pdf(monkeypatch):
    def broken(path):
        raise ValueError("not a PDF")
    monkeypatch.setattr(labelwrap.pdfplumber, "open", broken)
    fields, notes = f04_fields(), []
    labelwrap.confirm_claimed_bracket(fields, notes, Path("F04_factsheet.pdf"), [F04_TEXT])
    assert fields == f04_fields() and notes == ["The charge label's layout couldn't be read (ValueError)."]


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
    # Each answer key sits beside the folder of its PDFs: data/ with pdfs/, data/unseen/ with pdfs/unseen/.
    rows = []
    for key, folder in ((PROJECT / "data" / "answer_key.csv", PROJECT / "pdfs"),
                        (PROJECT / "data" / "unseen" / "answer_key.csv", PROJECT / "pdfs" / "unseen")):
        with key.open(encoding="utf-8") as f:
            rows += [(r, folder / f"{r['fund_id']}_factsheet.pdf") for r in csv.DictReader(f)
                     if r["doc_type"] == "factsheet" and r["charge_label"] != NOT_FOUND]
    missing = [pdf.name for _, pdf in rows if not pdf.exists()]
    if missing:  # checked before any assertion, so a skip never hides a result
        pytest.skip(f"{len(missing)} of {len(rows)} factsheet PDFs aren't here (PDFs aren't in the repo)")
    fired = set()
    for row, pdf in rows:
        base = re.sub(r" \([^()]*\)$", "", row["charge_label"])
        with pdfplumber.open(pdf) as document:
            for page in document.pages:
                bracket = labelwrap.wrapped_bracket(page.extract_words(), base, row["ongoing_charge_pct"])
                if bracket:
                    assert f"{base} {bracket}" == row["charge_label"], row["fund_id"]
                    fired.add(row["fund_id"])
    assert fired == {"F03", "F04", "F11", "F24"}


def test_only_a_quote_holding_the_start_of_the_label_is_lengthened(monkeypatch):
    # Claude quoted the heading above the label: the label isn't in its quote at all, so it
    # isn't stretched to reach it, even though the layout shows the bracket.
    text = "Key facts\n" + F04_TEXT
    fields = f04_fields(quote="Key facts")
    notes = confirm_then_check(monkeypatch, fields, text=text)
    assert fields["charge_label"].value == NOT_FOUND
    assert not any("lengthened" in note for note in notes)


def test_a_claim_must_match_the_bracket_under_the_label(monkeypatch):
    # The claimed "(to 2024)" is printed on the page, but not under the label: the layout shows
    # "(year end 31 Aug 2025)" there, so the claim isn't backed and the checks remove it.
    text = F04_TEXT + " Performance (to 2024)"
    fields = f04_fields(label="Ongoing charges (to 2024)")
    notes = confirm_then_check(monkeypatch, fields, text=text)
    assert fields["charge_label"].value == NOT_FOUND
    assert not any("lengthened" in note for note in notes)


def test_a_bracket_the_text_layer_doesnt_hold(monkeypatch):
    # The layout shows the bracket, but the page text has no piece holding the whole label.
    fields = f04_fields()
    notes = confirm_then_check(monkeypatch, fields, text="Ongoing charges 1.12%\nBenchmark -")
    assert fields["charge_label"].value == NOT_FOUND
    assert not any("lengthened" in note for note in notes)
