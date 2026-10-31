"""Spike for issue #3: compare pdfplumber and PyMuPDF on the trust KIDs.

Checks what Story 2.2 needs from a PDF library:
  1. speed on all 14 trust KIDs
  2. the F16 thin-slice lines can be found in the page text
  3. reading order (F09's risk sentence)
  4. cost table rows as separate cells (F04, F06, F10, F19)
  5. text that a quote check can match ("Other ongoing costs N/A" on F19)
  6. ligatures and odd characters (F12, F10)

Result (31 Oct 2026): pdfplumber chosen. It read all 4 cost rows as cells and
kept F09 in order; PyMuPDF found no tables and read F09 out of order. One
catch: pdfplumber's F19 row has the right figure ("N/A") but its description
cell picks up text from a neighbouring column.
PyMuPDF was then removed from the project, so to re-run this spike:
    .venv/bin/pip install pymupdf
    .venv/bin/python spikes/compare_pdf_libs.py
"""

import re
import time
import unicodedata
from pathlib import Path

import pdfplumber
import pymupdf

PDFS = Path("pdfs")
TRUST_KIDS = sorted(PDFS.glob("F*_kid.pdf"))


def normalise(text):
    """The quote check's normalisation from Story 2.2."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace("‐", "-")
    return re.sub(r"\s+", " ", text).strip()


# --- the two libraries, behind the same small interface ---------------------

def pages_plumber(path):
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def pages_mupdf(path):
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def tables_plumber(path, page_no):
    with pdfplumber.open(path) as pdf:
        return pdf.pages[page_no - 1].extract_tables()


def tables_mupdf(path, page_no):
    """Tries both of PyMuPDF's table strategies: ruling lines, then text alignment."""
    with pymupdf.open(path) as doc:
        page = doc[page_no - 1]
        tables = page.find_tables().tables or page.find_tables(strategy="text").tables
        return [t.extract() for t in tables]


LIBS = {
    "pdfplumber": (pages_plumber, tables_plumber),
    "PyMuPDF": (pages_mupdf, tables_mupdf),
}


# --- checks -----------------------------------------------------------------

def check_speed(pages_fn):
    start = time.perf_counter()
    for path in TRUST_KIDS:
        pages_fn(path)
    return time.perf_counter() - start


F16_LINES = [
    "ISIN: GB00BS88V647",
    "Date of Production: 08/06/2026",
    "We have classified this product as 4",
    "was 0.45%",
    "summary risk indicator",
]


def check_f16(pages_fn):
    text = normalise(" ".join(pages_fn(PDFS / "F16_kid.pdf")))
    return {line: line in text for line in F16_LINES}


def check_reading_order(pages_fn):
    """Is F09's risk sentence under the risk heading, as on the page?

    On the page the sentence sits under "What are the risks". If the page
    header block ("This document provides you with key information") comes
    out between the two, the library has read the page out of order.
    """
    page1 = normalise(pages_fn(PDFS / "F09_kid.pdf")[0])
    heading = page1.find("What are the risks")
    sentence = page1.find("classified this product as 4 out of 7")
    if sentence < 0:
        return "sentence not found"
    between = page1[heading:sentence]
    if "This document provides you with key information" in between:
        return "out of order (page header block comes between heading and sentence)"
    return "in order"


COST_ROWS = {
    "F04_kid.pdf": (3, "Management fees"),
    "F06_kid.pdf": (3, "Other ongoing costs"),
    "F10_kid.pdf": (3, "Other ongoing costs"),
    "F19_kid.pdf": (3, "Other ongoing costs"),
}


def check_tables(tables_fn):
    results = {}
    for name, (page_no, label) in COST_ROWS.items():
        found = None
        for table in tables_fn(PDFS / name, page_no):
            for row in table:
                cells = [normalise(c or "") for c in row]
                if any(label in c for c in cells):
                    found = [c[:40] for c in cells if c]
                    break
            if found:
                break
        results[name[:3]] = found or "row not found as a table"
    return results


def check_quote(pages_fn):
    page3 = normalise(pages_fn(PDFS / "F19_kid.pdf")[2])
    return "Other ongoing costs N/A" in page3


def check_characters(pages_fn):
    f12 = " ".join(pages_fn(PDFS / "F12_kid.pdf"))
    f10 = " ".join(pages_fn(PDFS / "F10_kid.pdf"))
    return {
        "F12 has ﬁ ligature": "ﬁ" in f12,
        "F12 'Identifier' after NFKC": "Identifier:" in normalise(f12),
        "F10 has U+2010 hyphen": "‐" in f10,
    }


def main():
    for lib, (pages_fn, tables_fn) in LIBS.items():
        print(f"===== {lib}")
        print(f"speed, 14 KIDs: {check_speed(pages_fn):.2f}s")
        print("F16 lines found:", check_f16(pages_fn))
        print("F09 reading order:", check_reading_order(pages_fn))
        print("cost rows as cells:")
        for fund, row in check_tables(tables_fn).items():
            print(f"   {fund}: {row}")
        print("F19 quote 'Other ongoing costs N/A' matches:", check_quote(pages_fn))
        print("characters:", check_characters(pages_fn))
        print()


if __name__ == "__main__":
    main()
