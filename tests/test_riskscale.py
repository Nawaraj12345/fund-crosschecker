"""Tests for reading a risk score from the scale graphic (riskscale.py)."""

from datetime import date
from pathlib import Path

import pytest

import fundcrosschecker.__main__ as cli
from fundcrosschecker import riskscale
from fundcrosschecker.checks import check_fields
from fundcrosschecker.common import NOT_FOUND, Field

PROJECT = Path(__file__).resolve().parent.parent
BLACK, GREEN, WHITE = (0.0, 0.0, 0.0), (0.45, 0.79, 0.2), (1.0, 1.0, 1.0)


class FakePage:
    def __init__(self, rects=(), curves=(), chars=(), text="Lower risk Higher risk"):
        self.rects, self.curves, self.chars, self.text = list(rects), list(curves), list(chars), text

    def extract_text(self):
        return self.text


class FakePdf:
    def __init__(self, *pages):
        self.pages = list(pages)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def box(x, colour, width=47, top=376, height=14):
    return {"fill": True, "x0": x, "x1": x + width, "top": top, "bottom": top + height,
            "width": width, "height": height, "non_stroking_color": colour}


def scale(highlighted=(5,), colour=GREEN, others=BLACK, step=50, widths=None):
    """Seven boxes like F02's, the highlighted ones in another colour."""
    return [box(24 + i * step, colour if i + 1 in highlighted else others, width=(widths or [47] * 7)[i]) for i in range(7)]


def digit(text, x, colour=WHITE, size=10.0, top=585):
    return {"text": text, "x0": x, "top": top, "size": size, "non_stroking_color": colour}


def digits(odd=(5,), colour=(1.0,), size=12.0, order="1234567", step=31):
    """A row of digits like F03's, the odd ones drawn in another colour and size."""
    return [digit(t, 342 + i * step, colour if int(t) in odd else (0.0, 0.38, 0.58), size if int(t) in odd else 10.0)
            for i, t in enumerate(order)]


# --- the boxes detector ------------------------------------------------------------------

def test_one_box_in_another_colour():  # F02
    assert [score for score, _ in riskscale._boxes(FakePage(rects=scale()))] == [5]


@pytest.mark.parametrize("highlighted", [1, 7])   # the ends of the scale
def test_the_first_and_last_box(highlighted):
    assert [score for score, _ in riskscale._boxes(FakePage(rects=scale((highlighted,))))] == [highlighted]


def test_several_fills_drawn_on_one_box():  # F20 draws a background, a white box and the highlight
    shapes = []
    for i in range(7):
        x = 40 + i * 35
        shapes += [box(x, (0.72, 0.87, 0.85), width=31), box(x + 1, WHITE, width=29)]
        if i == 4:
            shapes.append(box(x + 1, (1.0, 0.85, 0.4), width=29))
    found = riskscale._boxes(FakePage(curves=shapes))
    assert [score for score, _ in found] == [5]
    assert "box 5 of the 1-7 scale is filled" in found[0][1]


def test_a_pattern_fill_has_a_name_not_a_number():
    assert [s for s, _ in riskscale._boxes(FakePage(rects=scale(colour=("P1",))))] == [5]


@pytest.mark.parametrize("page", [
    FakePage(rects=scale(highlighted=(3, 5))),                     # two highlighted
    FakePage(rects=scale(highlighted=())),                         # none highlighted
    FakePage(rects=[box(24 + i * 50, (i / 10, 0, 0)) for i in range(7)]),  # all different: a gradient
    FakePage(rects=scale()[:6]),                                   # six boxes
    FakePage(rects=scale() + [box(374, BLACK)]),                   # eight boxes
    FakePage(rects=scale(widths=[47, 47, 47, 30, 47, 47, 47])),    # not equal
    FakePage(rects=[box(x, GREEN if i == 4 else BLACK) for i, x in enumerate([24, 74, 124, 174, 260, 310, 360])]),  # uneven
    FakePage(rects=[{**b, "fill": False} for b in scale()]),       # outlines, not fills
    FakePage(rects=scale(widths=[5] * 7, step=6)),                 # too small to be a scale
    FakePage(rects=[box(24 + i * 50, GREEN if i < 3 else (BLACK if i == 3 else WHITE)) for i in range(7)]),  # three bands
])
def test_boxes_that_arent_a_highlighted_scale(page):
    assert riskscale._boxes(page) == []


# --- the digits detector -----------------------------------------------------------------

def test_one_digit_in_another_colour_and_size():  # F03
    found = riskscale._digits(FakePage(chars=digits()))
    assert [score for score, _ in found] == [5]
    assert found[0][1] == ("digit 5 of the 1-7 scale is drawn in colour (1.0,) at size 12.0, "
                           "the other six in colour (0.0, 0.38, 0.58) at size 10.0")


def test_one_digit_only_in_another_colour():  # F02, F09 KID
    assert [s for s, _ in riskscale._digits(FakePage(chars=digits(odd=(4,), size=10.0)))] == [4]


@pytest.mark.parametrize("page", [
    FakePage(chars=digits(odd=(4, 5))),                 # two drawn differently
    FakePage(chars=digits(odd=())),                     # all the same
    FakePage(chars=digits(order="1234576")),            # not in order
    FakePage(chars=digits(order="123456")),             # no 7
    FakePage(chars=digits(step=2)),                     # too close together to be a scale
    FakePage(chars=[digit(t, x, size=12.0 if t == "5" else 10.0) for t, x in zip("1234567", [342, 373, 404, 470, 500, 530, 560])]),  # uneven
    FakePage(chars=[digit(t, 342 + i * 31, colour=BLACK if t == "5" else WHITE, top=585 + 10 * i)
                    for i, t in enumerate("1234567")]),  # a highlighted 5, but not one row
    FakePage(chars=[digit(t, 342 + i * 31, colour=GREEN if i < 3 else (BLACK if i == 3 else WHITE))
                    for i, t in enumerate("1234567")]),   # three bands of colour
])
def test_digits_that_arent_a_highlighted_scale(page):
    assert riskscale._digits(page) == []


# --- the whole document ------------------------------------------------------------------

def test_read_scale(monkeypatch):
    monkeypatch.setattr(riskscale.pdfplumber, "open", lambda path: FakePdf(
        FakePage(text="Performance"), FakePage(rects=scale(), chars=digits())))
    score, page, description = riskscale.read_scale(Path("x.pdf"))
    assert (score, page) == (5, 2) and description.startswith("box 5 of the 1-7 scale is filled")


@pytest.mark.parametrize("pages", [
    [FakePage(rects=scale(), text="Monthly performance")],                       # no risk wording on the page
    [FakePage(rects=scale(highlighted=(5,)), chars=digits(odd=(4,), size=10.0))],  # the two detectors disagree
    [FakePage(rects=scale((5,))), FakePage(rects=scale((6,)))],                  # two pages disagree
    [FakePage()],
    [],
])
def test_read_scale_gives_nothing_when_unsure(monkeypatch, pages):
    monkeypatch.setattr(riskscale.pdfplumber, "open", lambda path: FakePdf(*pages))
    assert riskscale.read_scale(Path("x.pdf")) is None


def fields_with_risk(value):
    return {"fund_name": Field("Foo Fund", 1, "Foo Fund"), "risk_score": Field(value)}


def test_fill_from_graphic(monkeypatch):
    monkeypatch.setattr(riskscale, "read_scale", lambda path: (5, 3, "box 5 of the 1-7 scale is filled (1,)"))
    fields, notes = fields_with_risk(NOT_FOUND), []
    riskscale.fill_from_graphic(fields, notes, Path("x.pdf"))
    assert fields["risk_score"] == Field("5", 3, "[scale graphic] box 5 of the 1-7 scale is filled (1,)")
    assert notes == ["Risk score read from the scale graphic on page 3: box 5 of the 1-7 scale is filled (1,)."]


def test_a_risk_score_from_the_text_is_never_replaced(monkeypatch):
    monkeypatch.setattr(riskscale, "read_scale", lambda path: pytest.fail("shouldn't read the graphic"))
    fields, notes = fields_with_risk("4"), []
    riskscale.fill_from_graphic(fields, notes, Path("x.pdf"))
    riskscale.fill_from_graphic({"fund_name": Field("Foo Fund")}, notes, Path("x.pdf"))   # no risk field at all
    assert fields["risk_score"].value == "4" and notes == []


def test_nothing_found_or_an_unreadable_drawing(monkeypatch):
    fields, notes = fields_with_risk(NOT_FOUND), []
    monkeypatch.setattr(riskscale, "read_scale", lambda path: None)
    riskscale.fill_from_graphic(fields, notes, Path("x.pdf"))
    assert fields["risk_score"].value == NOT_FOUND and notes == []

    def broken(path):
        raise KeyError("non_stroking_color")
    monkeypatch.setattr(riskscale, "read_scale", broken)
    riskscale.fill_from_graphic(fields, notes, Path("x.pdf"))
    assert fields["risk_score"].value == NOT_FOUND
    assert notes == ["The risk scale graphic couldn't be read (KeyError)."]


def test_an_answer_cant_claim_to_come_from_the_graphic():
    # A quote dressed up as a graphic description is still checked as text, so it's removed.
    fields = {"risk_score": Field("5", 1, "[scale graphic] box 5 of the 1-7 scale is filled (0.45, 0.79, 0.2)")}
    notes = []
    check_fields(fields, ["Risk and reward profile 1 2 3 4 5 6 7"], notes, date(2026, 11, 1))
    assert fields["risk_score"].value == NOT_FOUND
    assert notes and "quote not found" in notes[0]


@pytest.mark.parametrize("doc_type, read", [("kid", True), ("factsheet", True), ("kiid", False)])
def test_which_documents_use_the_graphic(tmp_path, monkeypatch, doc_type, read):
    (tmp_path / f"F01_{doc_type}.pdf").write_bytes(b"%PDF fake")
    monkeypatch.setattr(cli, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(cli, "read_pages", lambda path: ["page one"])
    calls = []
    monkeypatch.setattr(riskscale, "fill_from_graphic", lambda fields, notes, path: calls.append(path.name))
    cli.extract_all([tmp_path], doc_type, lambda pages, sha, path: (fields_with_risk(NOT_FOUND), []))
    assert calls == ([f"F01_{doc_type}.pdf"] if read else [])


# --- the real documents ------------------------------------------------------------------

@pytest.mark.parametrize("path, expected", [
    ("pdfs/F02_factsheet.pdf", (5, 1)),          # a green box among black ones
    ("pdfs/F03_factsheet.pdf", (5, 1)),          # a larger white digit on a blue box
    ("pdfs/F08_factsheet.pdf", (5, 3)),          # a beige box, no digits in the text
    ("pdfs/unseen/F20_kid.pdf", (5, 1)),         # an orange fill on one of seven boxes
    ("pdfs/F07_factsheet.pdf", None),            # the scale is a picture: nothing to read
    ("pdfs/F04_factsheet.pdf", None),            # no risk scale at all
])
def test_real_documents(path, expected):
    pdf = PROJECT / path
    if not pdf.exists():
        pytest.skip(f"{path} isn't here (PDFs aren't in the repo)")
    found = riskscale.read_scale(pdf)
    assert (found[:2] if found else None) == expected


@pytest.mark.slow
def test_the_reader_agrees_with_the_answer_key_wherever_it_reads_a_score():
    """The check made before the reader was added, kept so it can be repeated: on every
    document, a score read from the graphic must equal the answer key's, and none may be
    read where the key says not_found. The set of documents it reads isn't pinned, only
    these rules. The unseen factsheets were left out until their one honest run (1 Nov
    2026); with that done they're in, so all 58 documents are checked."""
    import csv
    key = {}
    for path in (PROJECT / "data" / "answer_key.csv", PROJECT / "data" / "unseen" / "answer_key.csv"):
        with path.open(encoding="utf-8") as f:
            key.update({(r["fund_id"], r["doc_type"]): r["risk_score"] for r in csv.DictReader(f)})
    pdfs = sorted(p for pattern in ("F*_kid.pdf", "F*_kiid.pdf", "F*_factsheet.pdf") for p in (PROJECT / "pdfs").glob(pattern))
    pdfs += sorted(p for pattern in ("F*_kid.pdf", "F*_factsheet.pdf") for p in (PROJECT / "pdfs" / "unseen").glob(pattern))
    if len(pdfs) < 58:
        pytest.skip(f"only {len(pdfs)} of the 58 PDFs are here (PDFs aren't in the repo)")
    read = {}
    for pdf in pdfs:
        found = riskscale.read_scale(pdf)
        if found:
            read[pdf.stem] = str(found[0])
    wrong = {name: (score, key[tuple(name.split("_"))]) for name, score in read.items() if score != key[tuple(name.split("_"))]}
    assert wrong == {}
    assert {"F02_factsheet", "F03_factsheet", "F08_factsheet", "F20_kid"} <= set(read)
