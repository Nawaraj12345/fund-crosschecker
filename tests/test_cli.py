"""Tests for the command line's extraction loop (no PDFs or API key needed)."""

import sys

import pytest

import fundcrosschecker.__main__ as cli
from fundcrosschecker.common import NOT_FOUND, Field


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A folder with two fake factsheets and one KID; output goes to tmp_path/output."""
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    for name in ("F01_factsheet.pdf", "F02_factsheet.pdf", "F16_kid.pdf"):
        (pdfs / name).write_bytes(b"%PDF fake " + name.encode())
    monkeypatch.setattr(cli, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(cli, "read_pages", lambda path: ["page one"])
    return pdfs


def fields():
    return {"fund_name": Field("A Fund", 1, "A Fund"), "isin": Field(NOT_FOUND)}, []


def test_a_folder_gives_only_its_documents_of_that_type(folder):
    seen = []
    assert cli.extract_all([folder], "factsheet", lambda pages, sha: seen.append(sha) or fields()) == 0
    assert len(seen) == 2  # the two factsheets, not the KID
    csv_text = (folder.parent / "output" / "factsheet_extracted.csv").read_text()
    assert "F01,factsheet,A Fund" in csv_text and "F16" not in csv_text
    assert (folder.parent / "output" / "factsheet" / "F02_factsheet.json").exists()


def test_a_missing_key_gives_one_hint(folder, capsys):
    def no_key(pages, sha):
        raise TypeError("Could not resolve authentication method. Expected one of api_key ...")

    assert cli.extract_all([folder], "factsheet", no_key) == 1
    err = capsys.readouterr().err
    assert err.count("Couldn't extract") == 2
    assert err.count("No Anthropic API key found") == 1
    assert not (folder.parent / "output" / "factsheet_extracted.csv").exists()


def test_other_errors_give_no_key_hint(folder, capsys):
    def broken(pages, sha):
        raise ValueError("the PDF has no pages")

    assert cli.extract_all([folder], "factsheet", broken) == 1
    assert "API key" not in capsys.readouterr().err


def test_kid_messages_still_say_kid(folder, capsys):
    cli.extract_all([folder], "kid", lambda pages, sha: fields())
    assert "1 KID(s) written" in capsys.readouterr().out


def test_the_same_file_twice_is_read_once(folder):
    seen = []
    cli.extract_all([folder, folder / "F01_factsheet.pdf"], "factsheet", lambda pages, sha: seen.append(sha) or fields())
    assert len(seen) == 2  # F01 and F02, not F01 twice
    assert (folder.parent / "output" / "factsheet_extracted.csv").read_text().count("F01,") == 1


def test_an_empty_folder_reads_nothing(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert cli.extract_all([tmp_path / "empty"], "kid", lambda pages, sha: fields()) == 1
    assert "No KID files to read" in capsys.readouterr().err


def test_a_missing_path_is_reported(folder, capsys):
    assert cli.extract_all([folder.parent / "nope", folder], "factsheet", lambda pages, sha: fields()) == 1
    err = capsys.readouterr().err
    assert "Couldn't find" in err and "1 file(s) skipped or failed" in err


def test_a_file_with_the_wrong_name_is_skipped(folder, capsys):
    odd = folder / "F17_KID.PDF"
    odd.write_bytes(b"%PDF")
    assert cli.extract_all([odd], "kid", lambda pages, sha: fields()) == 1
    assert "name isn't like F16_kid.pdf" in capsys.readouterr().err


def test_kiids_and_kids_are_told_apart(folder, capsys):
    (folder / "F01_kiid.pdf").write_bytes(b"%PDF fake kiid")
    seen = []
    assert cli.extract_all([folder], "kiid", lambda pages, sha: seen.append(sha) or fields()) == 0
    assert len(seen) == 1 and "1 KIID(s) written" in capsys.readouterr().out   # not the KID
    assert (folder.parent / "output" / "kiid" / "F01_kiid.json").exists()
    assert "F01,kiid,A Fund" in (folder.parent / "output" / "kiid_extracted.csv").read_text()
    seen.clear()
    cli.extract_all([folder], "kid", lambda pages, sha: seen.append(sha) or fields())
    assert len(seen) == 1   # F16_kid.pdf only, not F01_kiid.pdf


def test_the_kiid_command_uses_the_kiid_reader(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "extract_all", lambda paths, doc_type, extract: calls.append((paths, doc_type, extract)) or 0)
    monkeypatch.setattr(cli.kiid, "extract", lambda pages: ("read as a KIID", pages))
    monkeypatch.setattr(sys, "argv", ["fundcrosschecker", "kiid", str(tmp_path)])
    assert cli.main() == 0
    [(paths, doc_type, extract)] = calls
    assert (paths, doc_type) == ([tmp_path], "kiid")
    assert extract(["page"], "sha") == ("read as a KIID", ["page"])
