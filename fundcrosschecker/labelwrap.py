"""A factsheet's charge label whose bracket wraps onto the line below, read from the layout.

Factsheets often print the charge label in a narrow cell, so a bracket that belongs to
the label wraps onto the next line or two: F03 prints "Ongoing Charges Figure (OCF) per
year" with "(fixed):" under it, F24 "Ongoing charges ratio" with "(for 12 months ended"
and "30 June 2026)" under it. The text layer runs the columns together, so Claude quotes
the first line and the bracket is lost.

This runs in code after the checks, only on a label that passed them, and only adds a
bracket when the layout leaves no doubt:
- the label is printed once on its page, with the ongoing charge figure as the very
  next word to its right; the label's column runs from its left edge to that figure,
- the next line of that column starts with "(" at the label's left edge, and each
  line of the bracket follows the one above it within two line heights,
- every word of those lines starts and ends inside the column,
- the bracket closes within three lines, with nothing else of the cell after it (a
  colon may follow) and no percentage of its own further along that line, which
  would make it a separate row,
- it holds a word of two or more letters, so "(1)" or "(*)" from a footnote list
  doesn't count.
The longer label then needs a quote from the page text that holds all its words in
order, by the quote check's own rule, starting where the label's quote is printed.
Anything less clear-cut leaves the label as it was.

Before the checks, the same layout reading also confirms a bracket Claude did give but
quoted only in part (F04), so the quote check doesn't remove a right answer
(`confirm_claimed_bracket`). Both run from factsheet.extract, which has the PDF's path.
"""

import re
from pathlib import Path

import pdfplumber

from .checks import same_word, value_in_quote, words
from .common import NOT_FOUND, Field, normalise

EDGE = 1.5        # points: how far a line's start may be from the label's left edge
LINE = 1.5        # points: words whose tops are this close are on the same line
MAX_LINES = 3     # lines a bracket may take
MAX_QUOTE = 400   # characters: the longest quote that may join the label to its bracket
FOOTNOTE_MARKS = "*†‡"
PERCENT = re.compile(rf"[-+]?\d+(?:[.,]\d+)?%[{FOOTNOTE_MARKS}]{{0,2}}")


def extend_label(fields: dict[str, Field], notes: list[str], path: Path, pages: list[str]) -> None:
    """Add a wrapped bracket to the charge label in place, with a note, when one is found."""
    label, charge = fields.get("charge_label"), fields.get("ongoing_charge_pct")
    if not label or not charge or NOT_FOUND in (label.value, charge.value) or not label.page:
        return
    try:
        with pdfplumber.open(path) as pdf:
            bracket = wrapped_bracket(pdf.pages[label.page - 1].extract_words(), label.value, charge.value)
    except Exception as error:  # an odd page shouldn't stop the document being read
        notes.append(f"The charge label's layout couldn't be read ({type(error).__name__}).")
        return
    if not bracket:
        return
    longer = f"{label.value} {bracket}"
    quote = joining_quote(normalise(pages[label.page - 1]), normalise(label.quote or ""), longer)
    if quote is None:
        notes.append(f"charge_label: {bracket!r} is printed under the label, but no quote on the page holds "
                     f"the whole label, so it was left as {label.value!r}.")
        return
    fields["charge_label"] = Field(longer, label.page, quote)
    notes.append(f"charge_label: {bracket!r} added, printed under {label.value!r} on page {label.page} "
                 "(the label wraps onto the next line).")


def confirm_claimed_bracket(fields: dict[str, Field], notes: list[str], path: Path, pages: list[str]) -> None:
    """Before the checks: lengthen the label's quote when the layout confirms its bracket.

    Claude sometimes gives the whole label, bracket included, but quotes only its first
    line: F04's "Ongoing charges (year end 31 Aug 2025)" quoted as "Ongoing charges". The
    quote check would then remove a right answer. If the layout shows exactly that bracket
    under the rest of the label (by the same rules as `wrapped_bracket`), the quote is
    lengthened to a piece of the page text holding the whole label, and the checks then
    judge the label as they would any answer. Otherwise nothing changes.
    """
    label, charge = fields.get("charge_label"), fields.get("ongoing_charge_pct")
    if not label or not charge or NOT_FOUND in (label.value, charge.value) or not label.quote:
        return
    claim = re.fullmatch(r"(.+?) (\([^()]+\))", label.value.strip())
    if not claim or not label.page or not 1 <= label.page <= len(pages):
        return
    base, bracket = claim.groups()
    quote, page_text = normalise(label.quote), normalise(pages[label.page - 1])
    if value_in_quote("charge_label", label.value, quote) or not value_in_quote("charge_label", base, quote):
        return  # the quote already holds the whole label, or not even the rest of it: the checks decide
    try:
        with pdfplumber.open(path) as pdf:
            seen = wrapped_bracket(pdf.pages[label.page - 1].extract_words(), base, charge.value)
    except Exception as error:  # an odd page shouldn't stop the document being read
        notes.append(f"The charge label's layout couldn't be read ({type(error).__name__}).")
        return
    if seen is None or words(seen) != words(bracket):
        return  # the layout doesn't show that bracket under the label
    joined = joining_quote(page_text, quote, label.value)
    if joined is None:
        return
    fields["charge_label"] = Field(label.value, label.page, joined)
    notes.append(f"charge_label: the quote was lengthened to hold {bracket!r}, which is printed under "
                 f"{base!r} on page {label.page} (the label wraps onto the next line).")


def wrapped_bracket(page_words: list[dict], label: str, figure: str) -> str | None:
    """The bracket printed under the label, in its column, or None.

    `page_words` are pdfplumber words (text, x0, x1, top, bottom).
    """
    lines = lines_of(page_words)
    places = label_places(lines, label, figure)
    if len(places) != 1:
        return None  # not found, or printed more than once with its figure: unsure which
    left, top, height, right = places[0]

    text, depth, previous_top, used = "", 0, top, 0
    for line in lines:
        if line[0]["top"] <= top + LINE:
            continue  # the label's own line, or above it
        column = [w for w in line if left - EDGE <= w["x0"] < right]
        if not column:
            continue  # only other columns on this line
        first = column[0]
        if abs(first["x0"] - left) > EDGE or first["top"] - previous_top > 2 * height:
            return None  # not the next line of the label's own cell
        if any(w["x1"] > right for w in column):
            return None  # a word runs past the figure's edge: not plainly in the label's column
        if not text and not first["text"].startswith("("):
            return None  # the line under the label isn't a bracket
        for n, word in enumerate(column):
            for i, char in enumerate(word["text"]):
                depth += {"(": 1, ")": -1}.get(char, 0)
                if depth == 0:  # the bracket that opened the first line has closed
                    after = word["text"][i + 1:].strip(":") or column[n + 1:]
                    own_figure = any(PERCENT.fullmatch(w["text"]) for w in line if w["x0"] >= right)
                    bracket = f"{text} {word['text'][:i + 1]}".strip()
                    if after or own_figure or not re.search(r"[^\W\d_]{2}", bracket):
                        return None  # more of the cell follows, a separate row, or a footnote mark
                    return bracket
            text = f"{text} {word['text']}".strip()
        previous_top, used = first["top"], used + 1
        if used == MAX_LINES:
            return None  # the bracket doesn't close within MAX_LINES
    return None


def lines_of(page_words: list[dict]) -> list[list[dict]]:
    """The page's words grouped into lines, top to bottom, each line left to right."""
    lines: list[list[dict]] = []
    for word in sorted(page_words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= LINE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def label_places(lines: list[list[dict]], label: str, figure: str) -> list[tuple[float, float, float, float]]:
    """Where the label's words are printed side by side on one line with the figure as the
    next word to their right: (left, top, height, the figure's left edge)."""
    wanted = words(label)
    if not wanted:
        return []
    every_word = sorted((w for line in lines for w in line), key=lambda w: w["x0"])
    places = []
    for line in lines:
        for start, first in enumerate(line):
            if not words(first["text"]):
                continue  # a bullet or a dash before the label isn't where the label starts
            got: list[str] = []
            last = first
            for word in line[start:]:
                if len(got) >= len(wanted):
                    break
                got += words(word["text"], fold=False)
                last = word
            if len(got) != len(wanted) or not all(map(same_word, wanted, got)):
                continue
            # The next word to the right at the label's height (it may sit a little lower,
            # in another font) must be the figure itself.
            beside = next((w for w in every_word if w["x0"] > last["x1"]
                           and w["top"] < last["bottom"] and w["bottom"] > last["top"]), None)
            if beside is not None and is_figure(beside["text"], figure):
                places.append((first["x0"], first["top"], first["bottom"] - first["top"], beside["x0"]))
    return places


def is_figure(text: str, figure: str) -> bool:
    """Whether a printed word is the ongoing charge figure: "0.12%", "0.12", or with a
    footnote mark after it ("0.56%†", "0.73%*")."""
    return re.fullmatch(rf"{re.escape(figure)}%?[{FOOTNOTE_MARKS}]{{0,2}}", text) is not None


def joining_quote(page_text: str, quote: str, label: str) -> str | None:
    """The shortest piece of the page text that starts where the label's quote is printed
    (trying each place it is) and holds all the longer label's words in order, or None."""
    if not quote:
        return None
    for found in re.finditer(re.escape(quote), page_text):
        piece_text = page_text[found.start():found.start() + MAX_QUOTE]
        for end in (m.end() for m in re.finditer(r"\S+", piece_text)):
            if end >= len(quote) and value_in_quote("charge_label", label, piece_text[:end]):
                return piece_text[:end]
    return None
