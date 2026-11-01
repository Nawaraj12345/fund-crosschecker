"""Read a risk score that a document shows only on its 1-7 scale graphic.

Some documents don't print the risk score as text: they highlight it on the
scale, as a box in another colour (F02, F08 factsheets, F20 KID) or a digit drawn
differently (F03 factsheet). This reads the PDF's drawing data for that, on pages
with risk wording, using two detectors:

  boxes:  seven equal, evenly spaced filled boxes in a row, exactly one of them
          filled differently from the other six
  digits: the digits 1 to 7 in a row, left to right, exactly one of them drawn
          in another colour or size

Anything ambiguous (two highlighted, all different, the two detectors or two
pages disagreeing) gives nothing. A scale that is a picture (F07 factsheet) has
no drawing data to read, so it gives nothing too.

It's used only as a fallback: after the quote and format checks, and only when
the risk score is still not_found (see fill_from_graphic). The value then comes
with a description of the graphic instead of a text quote, marked
"[scale graphic]". Before it was added it was tried on 48 documents that print
their score as text or in the answer key: it fired on 21 and agreed every time,
and never fired on a document without a risk scale.
"""

import re
from pathlib import Path
from statistics import pstdev

import pdfplumber

from .common import NOT_FOUND, Field

# Risk wording that must be on the same page as the scale.
ANCHOR = re.compile(r"risk indicator|risk and reward|risk reward|lower risk|higher risk|\bSRRI\b|\bSRI\b", re.IGNORECASE)
MARK = "[scale graphic]"


def _colour(obj: dict) -> tuple:
    """A shape's or character's fill colour, rounded. A pattern fill has a name instead ("P1")."""
    c = obj.get("non_stroking_color")
    values = c if isinstance(c, (list, tuple)) else () if c is None else (c,)
    return tuple(round(v, 2) if isinstance(v, (int, float)) else str(v) for v in values)


def _boxes(page) -> list[tuple[int, str]]:
    """Seven equal, evenly spaced filled boxes in a row; exactly one filled differently."""
    shapes = [s for s in page.rects + page.curves if s.get("fill") and 8 <= s["height"] <= 60 and 8 <= s["width"] <= 90]
    rows: dict[tuple[int, int], list[dict]] = {}
    for s in shapes:
        rows.setdefault((round(s["top"] / 3), round(s["bottom"] / 3)), []).append(s)
    found = []
    for row in rows.values():
        boxes: list[dict] = []
        for s in sorted(row, key=lambda s: s["x0"]):
            # Several fills drawn on top of each other make one box (F20 draws three).
            if boxes and s["x0"] < boxes[-1]["x1"] - 0.5 * (s["x1"] - s["x0"]):
                boxes[-1]["x1"] = max(boxes[-1]["x1"], s["x1"])
                boxes[-1]["fills"].add(_colour(s))
            else:
                boxes.append({"x0": s["x0"], "x1": s["x1"], "fills": {_colour(s)}})
        if len(boxes) != 7:
            continue
        widths = [b["x1"] - b["x0"] for b in boxes]
        steps = [b2["x0"] - b1["x0"] for b1, b2 in zip(boxes, boxes[1:])]
        if pstdev(widths) > 2 or pstdev(steps) > 2:
            continue
        fills = [frozenset(b["fills"]) for b in boxes]
        odd = [i for i, f in enumerate(fills) if fills.count(f) == 1]
        if len(odd) == 1 and len(set(fills)) == 2:
            i = odd[0]
            other = fills[1] if i == 0 else fills[0]
            found.append((i + 1, f"box {i + 1} of the 1-7 scale is filled {_show(fills[i])}, the other six {_show(other)}"))
    return found


def _digits(page) -> list[tuple[int, str]]:
    """The digits 1 to 7 in a row, left to right; exactly one drawn in another colour or size."""
    digits = [c for c in page.chars if re.fullmatch(r"[1-7]", c["text"])]
    found = []
    for one in (c for c in digits if c["text"] == "1"):
        row = sorted((d for d in digits if abs(d["top"] - one["top"]) <= 4 and d["x0"] >= one["x0"] - 1),
                     key=lambda d: d["x0"])[:7]
        if "".join(d["text"] for d in row) != "1234567":
            continue
        steps = [b["x0"] - a["x0"] for a, b in zip(row, row[1:])]
        if pstdev(steps) > 3 or min(steps) < 4:
            continue
        looks = [(_colour(d), round(d["size"], 1)) for d in row]
        odd = [i for i, look in enumerate(looks) if looks.count(look) == 1]
        if len(odd) == 1 and len(set(looks)) == 2:
            i = odd[0]
            other = looks[1] if i == 0 else looks[0]
            found.append((i + 1, f"digit {i + 1} of the 1-7 scale is drawn in colour {_look(looks[i])}, "
                                 f"the other six in colour {_look(other)}"))
    return found


def _look(look: tuple) -> str:
    colour, size = look
    return f"{colour} at size {size}"


def _show(fills: frozenset) -> str:
    return " and ".join(str(f) for f in sorted(fills, key=str))


def read_scale(path: Path) -> tuple[int, int, str] | None:
    """(score, page, description) when the document's scale graphic shows exactly one score."""
    seen = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            if not ANCHOR.search(page.extract_text() or ""):
                continue
            for detector in (_boxes, _digits):
                seen += [(score, page_no, text) for score, text in detector(page)]
    if len({score for score, _, _ in seen}) != 1:
        return None  # nothing found, or two readings that disagree
    return seen[0]


def fill_from_graphic(fields: dict[str, Field], notes: list[str], path: Path) -> None:
    """If the risk score is still not_found after the checks, take it from the scale graphic.

    Runs in code after the checks, so nothing in an extractor's answer (or Claude's)
    can make a value skip the text quote check this way.
    """
    if "risk_score" not in fields or fields["risk_score"].value != NOT_FOUND:
        return
    try:
        found = read_scale(path)
    except Exception as error:  # an odd drawing shouldn't stop the document being read
        notes.append(f"The risk scale graphic couldn't be read ({type(error).__name__}).")
        return
    if found:
        score, page_no, description = found
        fields["risk_score"] = Field(str(score), page_no, f"{MARK} {description}")
        notes.append(f"Risk score read from the scale graphic on page {page_no}: {description}.")
