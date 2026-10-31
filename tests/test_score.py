"""Tests for the scorer (Story 2.2, step 3)."""

import csv
import os
import subprocess
import sys

import pytest

import fundcrosschecker.__main__ as cli
import fundcrosschecker.score as score_module
from fundcrosschecker.common import NOT_FOUND
from fundcrosschecker.score import (SCORED_FIELDS, UNSEEN_INPUTS, classify, git_commit, is_stale, record, run,
                                    score)


# --- matching rules ------------------------------------------------------------

@pytest.mark.parametrize("field, key_value, tool_value, kind", [
    # numbers match as numbers
    ("ongoing_charge_pct", "0.8", "0.80", "correct"),
    ("total_cost_pct", "0", "0.00", "correct"),
    ("total_cost_pct", "1.0", "1", "correct"),
    ("ongoing_charge_pct", "0.8", "0.85", "wrong"),
    ("risk_score", "4", "5", "wrong"),
    ("ongoing_charge_pct", "0.8", "N/A", "wrong"),          # not a number
    # names, share classes and labels ignore case, extra spaces and curly quotes
    ("fund_name", "HICL INFRASTRUCTURE PLC", "HICL Infrastructure plc", "correct"),
    ("fund_name", "F&C  Investment Trust PLC ", "F&C Investment Trust PLC", "correct"),
    ("fund_name", "RIT’s Trust plc", "RIT's Trust plc", "correct"),
    ("charge_label", "Other ongoing costs", "Other on-going costs", "wrong"),
    # dates, ISINs and risk methods must be exact
    ("doc_date", "2026-06-08", "2026-06-08", "correct"),
    ("doc_date", "2026-06-08", "2026-08-06", "wrong"),
    ("isin", "GB00BS88V647", "gb00bs88v647", "wrong"),
    ("risk_method", "SRI", "sri", "wrong"),
    # not_found only matches not_found
    ("share_class", NOT_FOUND, NOT_FOUND, "correct"),
    ("ongoing_charge_pct", "1.52", NOT_FOUND, "missed"),
    ("share_class", NOT_FOUND, "Ordinary shares", "made up"),
])
def test_classify(field, key_value, tool_value, kind):
    assert classify(field, key_value, tool_value) == kind


# --- scoring rows ----------------------------------------------------------------

def key_row(fund_id, **values):
    row = {"fund_id": fund_id, "doc_type": "kid", "notes": ""}
    row.update({field: NOT_FOUND for field in SCORED_FIELDS})
    row.update(values)
    return row


def test_every_scored_field_is_compared():
    results, not_extracted, problems = score([key_row("F16")], [key_row("F16")])
    assert [r.field for r in results] == SCORED_FIELDS
    assert all(r.kind == "correct" for r in results)
    assert not_extracted == [] and problems == []


def test_empty_answer_key_cell_is_not_scored():  # empty means "not checked yet"
    results, _, _ = score([key_row("F16")], [key_row("F16", isin="")])
    assert "isin" not in [r.field for r in results]
    assert len(results) == len(SCORED_FIELDS) - 1


def test_factsheet_rows_in_the_answer_key_are_ignored():
    factsheet = key_row("F16", isin="GB00BS88V647")
    factsheet["doc_type"] = "factsheet"
    results, not_extracted, _ = score([key_row("F16")], [key_row("F16"), factsheet])
    assert all(r.kind == "correct" for r in results)
    assert not_extracted == []


def test_kids_not_extracted_and_unknown_kids_are_reported():
    results, not_extracted, problems = score([key_row("F16"), key_row("F99")], [key_row("F16"), key_row("F19")])
    assert {r.fund_id for r in results} == {"F16"}
    assert not_extracted == ["F19"]
    assert problems == ["F99 isn't in the answer key, so it wasn't scored."]


# --- recording -------------------------------------------------------------------

def read_rows(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.reader(f))


def test_record_writes_a_header_once_and_one_row_per_field(tmp_path):
    results, _, _ = score([key_row("F16", isin="not_found")], [key_row("F16", isin="GB00BS88V647")])
    path = tmp_path / "results" / "kid_scores.csv"
    assert record(results, path, "2026-10-31", "b768b9f")
    assert record(results, path, "2026-11-01", "abc1234")  # a new commit is recorded
    rows = read_rows(path)
    assert rows[0] == ["run_date", "git_commit", "field", "correct", "wrong", "missed", "made_up"]
    assert len(rows) == 1 + 2 * len(SCORED_FIELDS)
    isin_row = next(r for r in rows if r[2] == "isin")
    assert isin_row == ["2026-10-31", "b768b9f", "isin", "0", "0", "1", "0"]


def test_same_commit_and_counts_are_not_recorded_twice(tmp_path):
    results, _, _ = score([key_row("F16")], [key_row("F16")])
    path = tmp_path / "kid_scores.csv"
    assert record(results, path, "2026-10-31", "b768b9f")
    assert not record(results, path, "2026-11-01", "b768b9f")  # same code, same result, later day
    assert len(read_rows(path)) == 1 + len(SCORED_FIELDS)
    changed, _, _ = score([key_row("F16", isin="not_found")], [key_row("F16", isin="GB00BS88V647")])
    assert record(changed, path, "2026-11-01", "b768b9f")  # same commit, different counts: recorded
    assert len(read_rows(path)) == 1 + 2 * len(SCORED_FIELDS)


def test_csv_older_than_the_code_is_stale(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "kid.py").write_text("x = 1\n")
    extracted = tmp_path / "kid_extracted.csv"
    extracted.write_text("fund_id\n")
    os.utime(extracted, (1_000_000, 1_000_000))      # CSV written long ago
    os.utime(code / "kid.py", (2_000_000, 2_000_000))  # code changed later
    assert is_stale(extracted, code)
    os.utime(extracted, (3_000_000, 3_000_000))      # extractor run again
    assert not is_stale(extracted, code)


def test_empty_results_file_still_gets_a_header(tmp_path):
    path = tmp_path / "kid_scores.csv"
    path.write_text("")
    results, _, _ = score([key_row("F16")], [key_row("F16")])
    assert record(results, path, "2026-10-31", "b768b9f")
    assert read_rows(path)[0][0] == "run_date"


# --- which commit a score belongs to ----------------------------------------------

def git(project, *args):
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
                   cwd=project, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "fundcrosschecker").mkdir()
    (tmp_path / "fundcrosschecker" / "kid.py").write_text("x = 1\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "answer_key.csv").write_text("fund_id\n")
    (tmp_path / "data" / "sources.csv").write_text("fund_id\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def head(project):
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=project, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_clean_checkout_gives_the_commit(project):
    assert git_commit(project) == head(project)


def test_committing_other_files_keeps_the_commit(project):
    # Committing the score history mustn't make the next run look like new code.
    scored = head(project)
    (project / "results").mkdir()
    (project / "results" / "kid_scores.csv").write_text("run_date\n")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "Recorded a score")
    assert head(project) != scored
    assert git_commit(project) == scored


def test_committing_the_answer_key_moves_the_commit(project):
    (project / "data" / "answer_key.csv").write_text("fund_id,changed\n")
    git(project, "commit", "-q", "-am", "Changed the answer key")
    assert git_commit(project) == head(project)


@pytest.mark.parametrize("changed_file", ["fundcrosschecker/kid.py", "data/answer_key.csv"])
def test_changed_code_or_answer_key_is_marked_uncommitted(project, changed_file):
    (project / changed_file).write_text("changed\n")
    assert git_commit(project).endswith("+uncommitted")


def test_other_changes_dont_count(project):
    (project / "data" / "sources.csv").write_text("changed\n")
    assert "+" not in git_commit(project)


def test_outside_a_git_repo_gives_unknown(tmp_path):
    assert git_commit(tmp_path) == "unknown"


def test_each_answer_key_only_affects_its_own_score(project):
    # The unseen answer key changing mustn't touch the development score, and the reverse.
    (project / "data" / "unseen").mkdir()
    (project / "data" / "unseen" / "answer_key.csv").write_text("fund_id\n")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "Added the unseen answer key")
    unseen_added = head(project)
    assert git_commit(project, UNSEEN_INPUTS) == unseen_added
    assert git_commit(project) != unseen_added

    (project / "data" / "unseen" / "answer_key.csv").write_text("fund_id,changed\n")
    assert git_commit(project, UNSEEN_INPUTS).endswith("+uncommitted")
    assert "+" not in git_commit(project)


# --- the command's error messages ---------------------------------------------------

def test_missing_files_and_columns_are_reported(tmp_path, capsys):
    extracted, key, results = tmp_path / "out.csv", tmp_path / "key.csv", tmp_path / "scores.csv"
    assert run(extracted, key, results) == 1
    assert "run the extractor first" in capsys.readouterr().out

    extracted.write_text("fund_id,isin\nF16,GB00BS88V647\n")
    assert run(extracted, key, results) == 1
    assert "No answer key" in capsys.readouterr().out

    key.write_text("fund_id,doc_type," + ",".join(SCORED_FIELDS) + "\n")
    assert run(extracted, key, results) == 1
    assert "The extractor output is missing columns: charge_label, doc_date" in capsys.readouterr().out
    assert not results.exists()


def scoring_files(folder):
    """An answer key and extractor output for one KID, written after the code, so not stale."""
    header = "fund_id,doc_type," + ",".join(SCORED_FIELDS)
    row = "F16,kid," + ",".join(["not_found"] * len(SCORED_FIELDS))
    (folder / "key.csv").write_text(f"{header}\n{row}\n")
    (folder / "out.csv").write_text(f"{header}\n{row}\n")
    return folder / "out.csv", folder / "key.csv", folder / "scores.csv"


def test_uncommitted_code_is_scored_but_not_recorded(project, capsys):
    (project / "fundcrosschecker" / "kid.py").write_text("x = 2\n")  # a change that isn't committed
    extracted, key, results = scoring_files(project)
    assert run(extracted, key, results, project) == 0
    assert "aren't committed" in capsys.readouterr().out
    assert not results.exists()


def test_committed_code_is_recorded(project, capsys):
    extracted, key, results = scoring_files(project)
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "scoring files")
    assert run(extracted, key, results, project) == 0
    assert "Recorded in" in capsys.readouterr().out
    assert read_rows(results)[1][1] == git_commit(project)


def test_unseen_score_ignores_changes_to_the_development_key(project, capsys):
    (project / "data" / "unseen").mkdir()
    extracted, key, results = scoring_files(project / "data" / "unseen")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "scoring files")
    (project / "data" / "answer_key.csv").write_text("fund_id,changed\n")  # not part of the unseen score
    assert run(extracted, key, results, project, inputs=UNSEEN_INPUTS) == 0
    assert "Recorded in" in capsys.readouterr().out


def test_missing_kids_message_names_the_right_folder(project, capsys):
    extracted, key, results = scoring_files(project)
    extracted.write_text("fund_id,doc_type," + ",".join(SCORED_FIELDS) + "\n")  # nothing extracted
    with key.open("a") as f:
        f.write("F20,kid," + ",".join(["not_found"] * len(SCORED_FIELDS)) + "\n")
    run(extracted, key, results, project, pdf_folder="pdfs/unseen/")
    assert "Run the extractor on pdfs/unseen/" in capsys.readouterr().out
    assert not results.exists()


def test_score_unseen_uses_the_unseen_files(monkeypatch):
    calls = []
    monkeypatch.setattr(score_module, "run", lambda **kwargs: calls.append(kwargs) or 0)
    for argv, expected in ((["score"], {}),
                           (["score", "--unseen"], {"key_path": score_module.UNSEEN_KEY,
                                                    "results_path": score_module.UNSEEN_RESULTS,
                                                    "inputs": UNSEEN_INPUTS, "pdf_folder": "pdfs/unseen/"})):
        monkeypatch.setattr(sys, "argv", ["fundcrosschecker", *argv])
        assert cli.main() == 0
        assert calls.pop() == expected
    assert score_module.UNSEEN_KEY.parts[-3:] == ("data", "unseen", "answer_key.csv")
    assert score_module.UNSEEN_RESULTS.name == "unseen_kid_scores.csv"
    assert score_module.UNSEEN_RESULTS != score_module.RESULTS
