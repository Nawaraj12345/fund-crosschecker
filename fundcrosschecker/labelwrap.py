"""A factsheet's charge label whose bracket wraps onto the line below, read from the layout.

Factsheets often print the charge label in a narrow cell, so a bracket that belongs to
the label wraps onto the next line or two: F03 prints "Ongoing Charges Figure (OCF) per
year" with "(fixed):" under it, F24 "Ongoing charges ratio" with "(for 12 months ended"
and "30 June 2026)" under it. The text layer runs the columns together, so Claude quotes
the first line and the bracket is lost.

This runs in code after the checks, only on a label that passed them, and only adds a
bracket that:
- is on the same page as the label, next to the ongoing charge figure,
- starts with "(" directly under the label, at the label's left edge,
- stays left of the figure, so it's in the label's own column,
- closes within three lines, each starting at that same edge.
The longer label then needs a quote from the page text that holds all its words in
order, by the quote check's own rule, starting where the label's quote starts.
Anything less clear-cut leaves the label as it was.
"""

import re
from pathlib import Path

import pdfplumber

from .checks import same_word, value_in_quote, words
from .common import NOT_FOUND, Field, normalise

EDGE = 1.5        # points: how far a line's start may be from the label's left edge
MAX_LINES = 3     # lines a bracket may take
MAX_QUOTE = 400   # characters: the longest quote that may join the label to its bracket


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
    if not bracket or normalise(bracket).casefold() in normalise(label.value).casefold():
        return
    longer = f"{label.value} {bracket}"
    page_texts = [normalise(page) for page in pages]
    quote = joining_quote(page_texts[label.page - 1], normalise(label.quote or ""), longer)
    if quote is None:
        notes.append(f"charge_label: {bracket!r} is printed under the label, but no quote on the page holds "
                     f"the whole label, so it was left as {label.value!r}.")
        return
    fields["charge_label"] = Field(longer, label.page, quote)
    notes.append(f"charge_label: {bracket!r} added, printed under {label.value!r} on page {label.page} "
                 "(the label wraps onto the next line).")


def wrapped_bracket(page_words: list[dict], label: str, figure: str) -> str | None:
    """The bracket printed under the label, in its column, or None.

    `page_words` are pdfplumber words (text, x0, x1, top, bottom). The label must appear
    exactly once on the page with the figure (e.g. "0.12%") to its right on the same line.
    """
    found = [place for place in label_places(page_words, label, figure) if place[3] is not None]
    if len(found) != 1:
        return None
    left, top, height, right = found[0]
    below = sorted((w for w in page_words if w["top"] > top + 1 and w["x0"] >= left - EDGE and w["x1"] <= right),
                   key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    for word in below:
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= 1.5:
            lines[-1].append(word)
        else:
            lines.append([word])

    text, depth, previous_top = "", 0, top
    for line in lines[:MAX_LINES]:
        first = line[0]
        if abs(first["x0"] - left) > EDGE or first["top"] - previous_top > 2 * height:
            return None  # not the next line of the label's own cell
        if not text and not first["text"].startswith("("):
            return None  # the line under the label isn't a bracket
        for word in line:
            for i, char in enumerate(word["text"]):
                depth += {"(": 1, ")": -1}.get(char, 0)
                if depth == 0:  # the bracket that opened the first line has closed
                    return f"{text} {word['text'][:i + 1]}".strip()
            text = f"{text} {word['text']}".strip()
        previous_top = first["top"]
    return None  # the bracket doesn't close within MAX_LINES


def label_places(page_words: list[dict], label: str, figure: str) -> list[tuple[float, float, float, float | None]]:
    """Where the label's words are printed side by side on one line: (left, top, height,
    left edge of the figure to their right, or None if no figure follows on that line)."""
    wanted = words(label)
    places = []
    for first in page_words:
        if not words(first["text"]):
            continue  # a bullet or a dash before the label isn't where the label starts
        # The words from this one rightwards on its line, left to right.
        line = sorted((w for w in page_words if abs(w["top"] - first["top"]) <= 1.5 and w["x0"] >= first["x0"]),
                      key=lambda w: w["x0"])
        got: list[str] = []
        last = None
        for word in line:
            if len(got) >= len(wanted):
                break
            got += words(word["text"], fold=False)
            last = word
        if last is None or len(got) != len(wanted) or not all(map(same_word, wanted, got)):
            continue
        figure_left = next((w["x0"] for w in page_words if w["x0"] > last["x1"] and is_figure(w["text"], figure)
                            and w["top"] < last["bottom"] and w["bottom"] > last["top"]), None)
        places.append((first["x0"], first["top"], first["bottom"] - first["top"], figure_left))
    return places


def is_figure(text: str, figure: str) -> bool:
    """Whether a printed word is the ongoing charge figure: "0.12%", "1.36 %" or "0.12"."""
    return re.fullmatch(rf"{re.escape(figure)} ?%?", text) is not None


def joining_quote(page_text: str, quote: str, label: str) -> str | None:
    """The shortest piece of the page text that starts with the label's quote and holds
    all the longer label's words in order, or None."""
    start = page_text.find(quote) if quote else -1
    if start < 0:
        return None
    for end in (m.end() for m in re.finditer(r"\S+", page_text[start:start + MAX_QUOTE])):
        piece = page_text[start:start + end]
        if value_in_quote("charge_label", label, piece):
            return piece
    return None
