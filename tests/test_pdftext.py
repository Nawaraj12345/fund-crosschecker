"""Tests for reading a PDF's text (pdftext.py): a real KID, and files that aren't PDFs."""

from pathlib import Path

import pytest
from pdfplumber.utils.exceptions import PdfminerException

from fundcrosschecker.pdftext import read_pages

F16 = Path(__file__).resolve().parent.parent / "pdfs" / "F16_kid.pdf"


@pytest.mark.skipif(not F16.exists(), reason="needs pdfs/F16_kid.pdf (not in the repo)")
def test_reads_every_page_of_a_real_kid():
    pages = read_pages(F16)
    assert len(pages) == 3
    assert "GB00BS88V647" in pages[0]


def test_a_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_pages(tmp_path / "missing.pdf")


@pytest.mark.parametrize("content", [b"", b"not a pdf at all"])
def test_a_file_that_isnt_a_pdf_is_an_error(tmp_path, content):
    # The command line catches this per file, so one bad file doesn't stop the others.
    path = tmp_path / "bad.pdf"
    path.write_bytes(content)
    with pytest.raises(PdfminerException):
        read_pages(path)
