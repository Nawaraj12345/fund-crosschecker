"""Read a PDF's text layer.

This and riskscale.py (which reads the risk scale's drawing) are the only
modules that use pdfplumber, so the PDF library can be swapped in two places.

pdfplumber reads across the whole page, so on two-column pages (F16's page 1)
the left and right columns are merged line by line. A value on one line is
still found, but a sentence that wraps inside one column comes out in pieces.
"""

from pathlib import Path

import pdfplumber


def read_pages(path: Path) -> list[str]:
    """Return the text of each page. Index 0 is page 1."""
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]
