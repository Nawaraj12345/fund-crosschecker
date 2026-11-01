"""Tests for the comparison (Story 3.1), using the funds' real values."""

import csv
import json
import sys
from pathlib import Path

import pytest

import fundcrosschecker.__main__ as cli
from fundcrosschecker import compare
from fundcrosschecker.common import NOT_FOUND
from fundcrosschecker.kid import ELSEWHERE_NOTE, charges_elsewhere_in

PROJECT = Path(__file__).resolve().parent.parent


def doc(fund_id, charge, risk="not_found", method="not_found", isin="GB0000000001", day="2026-09-30", notes=""):
    return {"fund_id": fund_id, "isin": isin, "ongoing_charge_pct": charge, "risk_score": risk,
            "risk_method": method, "doc_date": day, "notes": notes}


def elsewhere(*figures):
    return " ".join(ELSEWHERE_NOTE.format(figure=figure, page=3, quote=f"was {figure}%") for figure in figures)


def verdicts(factsheet, kid, kid_type="kid"):
    return {c.field: (c.verdict, sorted(c.reasons)) for c in compare.compare_documents(factsheet, kid, kid_type)}


# --- the ongoing charge, with the real funds' figures --------------------------------------

@pytest.mark.parametrize("factsheet, kid, expected", [
    (doc("F01", "0.20"), doc("F01", "0.20", day="2026-06-26"), ("match", [])),
    (doc("F04", "1.12"), doc("F04", "1.52", day="2026-05-25"), ("mismatch", ["no_reason"])),
    (doc("F05", NOT_FOUND), doc("F05", "0.70"), ("cant_compare", ["factsheet_none"])),
    (doc("F06", "0.69"), doc("F06", "0.00", day="2025-09-11", notes=elsewhere("0.77")),
     ("mismatch", ["far_apart", "kid_table_zero", "kid_text_other"])),
    (doc("F09", "0.6"), doc("F09", "0.8", day="2017-12-29"), ("mismatch", ["far_apart"])),
    (doc("F10", "0.73"), doc("F10", NOT_FOUND, notes=elsewhere("0.73")), ("cant_compare", ["kid_none", "kid_text_same"])),
    (doc("F13", NOT_FOUND), doc("F13", "0.00", notes=elsewhere("1.35")), ("cant_compare", ["factsheet_none", "kid_text_other"])),
    (doc("F14", "1.03"), doc("F14", NOT_FOUND, notes=elsewhere("1.03", "1.10")), ("cant_compare", ["kid_none", "kid_text_same"])),
    (doc("F15", "0.79"), doc("F15", "0.78", day="2025-09-11"), ("mismatch", ["far_apart"])),
    (doc("F20", NOT_FOUND), doc("F20", NOT_FOUND), ("cant_compare", ["neither_none"])),
    (doc("F22", "0.75"), doc("F22", "0.00", day="2026-03-25"), ("mismatch", ["kid_table_zero"])),
    (doc("F26", "0.68"), doc("F26", "0.73", notes=elsewhere("0.59")), ("mismatch", ["kid_text_other"])),
    (doc("F28", "1.74"), doc("F28", "0.00", notes=elsewhere("1.74")), ("mismatch", ["kid_table_zero", "kid_text_same"])),
])
def test_charge_verdicts_and_reasons(factsheet, kid, expected):
    assert verdicts(factsheet, kid)["ongoing_charge_pct"] == expected


@pytest.mark.parametrize("a, b, verdict", [
    ("0.6", "0.60", "match"),     # the same number written differently
    ("0", "0.00", "match"),
    ("0.79", "0.78", "mismatch"),  # no tolerance
    ("0.825", "0.82", "mismatch"),
])
def test_numbers_are_compared_as_numbers(a, b, verdict):
    assert verdicts(doc("F01", a), doc("F01", b))["ongoing_charge_pct"][0] == verdict


def test_different_isins_mean_different_share_classes():  # F07: I USD Acc and I GBP Acc
    result = verdicts(doc("F07", "0.91", "7", isin="IE00BYVJRD56"), doc("F07", "0.92", "7", isin="IE00BYVJRH94"), "kiid")
    assert result == {"ongoing_charge_pct": ("cant_compare", ["different_share_class"]),
                      "risk_score": ("cant_compare", ["different_share_class"])}


def test_a_missing_isin_doesnt_stop_the_comparison():  # six factsheets print none
    assert verdicts(doc("F16", "0.45", isin=NOT_FOUND), doc("F16", "0.45"))["ongoing_charge_pct"] == ("match", [])


@pytest.mark.parametrize("kid_day, far", [
    ("2025-09-30", True),    # exactly 365 days: a year
    ("2025-10-01", False),   # 364 days
    ("2027-09-30", True),    # the KID newer by a year counts too
    ("2026-09", False),      # only a month: the gap isn't known, so it isn't claimed
    (NOT_FOUND, False),
])
def test_far_apart_from_a_year(kid_day, far):
    reasons = verdicts(doc("F15", "0.79"), doc("F15", "0.78", day=kid_day))["ongoing_charge_pct"][1]
    assert ("far_apart" in reasons) == far
    assert reasons == (["far_apart"] if far else ["no_reason"])


def test_kid_table_zero_needs_a_factsheet_figure_above_zero():
    assert verdicts(doc("F01", "0.00"), doc("F01", "0"))["ongoing_charge_pct"] == ("match", [])
    assert "kid_table_zero" not in verdicts(doc("F01", "0.10"), doc("F01", "0.20"))["ongoing_charge_pct"][1]


def test_a_kiids_notes_are_never_read_as_other_figures():
    result = verdicts(doc("F01", "0.20"), doc("F01", "0.30", notes=elsewhere("0.20")), "kiid")
    assert result["ongoing_charge_pct"] == ("mismatch", ["no_reason"])


# --- the risk score --------------------------------------------------------------------

@pytest.mark.parametrize("factsheet, kid, expected", [
    (("4", "SRRI"), ("4", NOT_FOUND), ("match", ["scale_not_stated"])),    # F01
    (("5", NOT_FOUND), ("5", NOT_FOUND), ("match", ["scale_not_stated"])),  # F02, F03
    (("4", "SRI"), ("4", "SRI"), ("match", [])),                            # F25: the same named scale
    (("4", "SRRI"), ("4", "SRI"), ("cant_compare", ["different_scales"])),
    (("3", "SRRI"), ("5", "SRI"), ("cant_compare", ["different_scales"])),
    (("4", "SRI"), ("5", "SRI"), ("mismatch", [])),
    ((NOT_FOUND, NOT_FOUND), ("5", "SRI"), ("cant_compare", ["factsheet_none"])),  # most trusts
])
def test_risk_verdicts(factsheet, kid, expected):
    result = verdicts(doc("F01", "0.20", *factsheet), doc("F01", "0.20", *kid))
    assert result["risk_score"] == expected


# --- the note the KID reader writes, read back ---------------------------------------------

@pytest.mark.parametrize("quote", [
    "most recent figure for 2025 was 0.73%",
    'the "OCF" (as defined) was 1.74%',      # quote marks and brackets inside the quote
    "",
])
def test_the_elsewhere_note_reads_back(quote):
    note = ELSEWHERE_NOTE.format(figure="0.73", page=12, quote=quote)
    text = f"No cost table: ongoing charge taken from the cost section. {note} {note}"
    assert charges_elsewhere_in(text) == [("0.73", 12, quote)] * 2


def test_other_notes_arent_read_as_figures():
    assert charges_elsewhere_in("Transaction costs: only a £ amount is given (116 GBP), so no percentage.") == []
    assert charges_elsewhere_in("") == []


# --- the whole run -------------------------------------------------------------------------

def test_funds_are_paired_and_problems_reported():
    comparisons, problems = compare.compare_all(
        factsheets=[doc("F01", "0.20"), doc("F02", "0.05"), doc("F03", "0.12"), doc("F03", "0.12"), doc("F04", "abc")],
        kids=[doc("F04", "1.52"), doc("F05", "0.70"), doc("F03", "0.12")],
        kiids=[doc("F01", "0.20"), doc("F03", "0.12")])
    assert [(c.fund_id, c.field) for c in comparisons] == [("F01", "ongoing_charge_pct"), ("F01", "risk_score")]
    assert problems == [
        "F03 has more than one KID or KIID in the output, so it wasn't compared.",
        "F02 has a factsheet but no KID or KIID in the output, so it wasn't compared.",
        "F03 has more than one factsheet in the output; it was compared once.",
        "F04 wasn't compared: 'abc' isn't a number.",
        "F05 has a KID but no factsheet in the output, so it wasn't compared.",
    ]


def test_nothing_to_compare():
    assert compare.compare_all([], [], []) == ([], [])


@pytest.fixture
def output(tmp_path):
    """Extractor output for F04 and F10 (factsheets and KIDs), as the commands write it."""
    rows = {"factsheet": [doc("F04", "1.12"), doc("F10", "0.73")],
            "kid": [doc("F04", "1.52", day="2026-05-25"), doc("F10", NOT_FOUND, notes=elsewhere("0.73"))]}
    for doc_type, docs in rows.items():
        with (tmp_path / f"{doc_type}_extracted.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(docs[0]))
            writer.writeheader()
            writer.writerows(docs)
        for row in docs:
            fields = {name: {"value": row[name], "page": 2, "quote": f"{doc_type} says {row[name]}"}
                      for name in ("ongoing_charge_pct", "risk_score")}
            path = tmp_path / doc_type / f"{row['fund_id']}_{doc_type}.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({"fields": fields}), encoding="utf-8")
    return tmp_path


def test_compare_writes_every_value_with_its_page_and_quote(output, capsys):
    assert compare.run_compare(output, output / "comparison.csv") == 0
    rows = compare.read_csv(output / "comparison.csv")
    assert [(r["fund_id"], r["field"], r["verdict"]) for r in rows] == [
        ("F04", "ongoing_charge_pct", "mismatch"), ("F04", "risk_score", "cant_compare"),
        ("F10", "ongoing_charge_pct", "cant_compare"), ("F10", "risk_score", "cant_compare")]
    assert (rows[0]["factsheet_quote"], rows[0]["kid_page"], rows[0]["days_apart"]) == ("factsheet says 1.12", "2", "128")
    assert rows[2]["reasons"] == "kid_none;kid_text_same" and rows[2]["kid_other_figures"] == '0.73% (page 3: "was 0.73%")'
    printed = capsys.readouterr().out
    assert "1.12 vs 1.52" in printed and "No reason found in the documents" in printed
    assert "Possible reasons: No reason" not in printed   # nothing to call a possible reason
    assert 'The KID\'s text gives 0.73% (page 3: "was 0.73%"), the same as the factsheet.' in printed
    assert "0 match, 1 mismatch, 1 can't compare, out of 2 funds" in printed


def test_a_json_file_from_an_older_run_isnt_quoted(output, capsys):
    path = output / "kid" / "F04_kid.json"
    saved = json.loads(path.read_text())
    saved["fields"]["ongoing_charge_pct"]["value"] = "1.50"   # an older reading
    path.write_text(json.dumps(saved))
    (output / "factsheet" / "F10_factsheet.json").unlink()
    compare.run_compare(output, output / "comparison.csv")
    printed = capsys.readouterr().out
    assert "F04_kid.json doesn't match the CSV for ongoing_charge_pct" in printed
    assert "F10_factsheet.json doesn't match the CSV" in printed
    rows = compare.read_csv(output / "comparison.csv")
    assert rows[0]["kid_quote"] == "" and rows[0]["factsheet_quote"] == "factsheet says 1.12"


def test_compare_needs_the_extractors_output(tmp_path, capsys):
    assert compare.run_compare(tmp_path, tmp_path / "comparison.csv") == 1
    assert "Run the extractors first" in capsys.readouterr().out
    assert not (tmp_path / "comparison.csv").exists()


def test_same_day_and_kid_newer_in_the_report(capsys):
    same = compare.compare_documents(doc("F01", "0.20"), doc("F01", "0.20"), "kiid")
    newer = compare.compare_documents(doc("F14", "1.03", day="2026-03-31"), doc("F14", "1.03", day="2026-07-31"), "kid")
    month = compare.compare_documents(doc("F03", "0.12", day="2026-09"), doc("F03", "0.12"), "kiid")
    compare.print_report(same + newer + month)
    printed = capsys.readouterr().out
    assert "(same day)" in printed and "(122 days apart, the KID is newer)" in printed
    assert "(dates can't be compared)" in printed


# --- the comparison logic reproduces the hand-written key ----------------------------------

# The figures the KIDs give outside their cost rows, each checked in the PDF (Story 3.1).
TEXT_FIGURES = {"F06": ["0.77"], "F10": ["0.73"], "F11": ["0.67"], "F13": ["1.35"], "F14": ["1.03", "1.10"], "F19": ["0.74"]}


def test_the_logic_on_the_answer_keys_values_gives_the_comparison_key():
    with (PROJECT / "data" / "answer_key.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["notes"] = elsewhere(*TEXT_FIGURES.get(row["fund_id"], [])) if row["doc_type"] == "kid" else ""
    comparisons, problems = compare.compare_all([r for r in rows if r["doc_type"] == "factsheet"],
                                                [r for r in rows if r["doc_type"] == "kid"],
                                                [r for r in rows if r["doc_type"] == "kiid"])
    assert problems == []
    tool = [{"fund_id": c.fund_id, "field": c.field, "verdict": c.verdict, "reasons": ";".join(c.reasons)}
            for c in comparisons]
    key = compare.read_csv(compare.COMPARISON_KEY)
    counts, not_compared, details = compare.score_comparison(tool, key)
    assert (counts["correct"], counts["reasons right"], not_compared, details) == (38, 38, [], [])


# --- scoring ---------------------------------------------------------------------------------

def key_row(fund_id, field, verdict, reasons=""):
    return {"fund_id": fund_id, "field": field, "verdict": verdict, "reasons": reasons}


def test_scoring_kinds():
    key = [key_row("F01", "ongoing_charge_pct", "match"), key_row("F04", "ongoing_charge_pct", "mismatch", "no_reason"),
           key_row("F05", "ongoing_charge_pct", "cant_compare", "factsheet_none"),
           key_row("F02", "risk_score", "match", "scale_not_stated"),
           key_row("F06", "ongoing_charge_pct", "mismatch", "kid_table_zero;far_apart"),
           key_row("F09", "ongoing_charge_pct", "mismatch", "far_apart")]
    tool = [key_row("F01", "ongoing_charge_pct", "mismatch", "no_reason"),          # false alarm
            key_row("F04", "ongoing_charge_pct", "cant_compare", "kid_none"),       # missed mismatch
            key_row("F05", "ongoing_charge_pct", "mismatch", "no_reason"),          # false alarm too
            key_row("F02", "risk_score", "cant_compare", "factsheet_none"),         # other wrong
            key_row("F06", "ongoing_charge_pct", "mismatch", "far_apart;kid_table_zero")]  # right, reasons in another order
    counts, not_compared, details = compare.score_comparison(tool, key)
    assert counts == {"correct": 1, "false alarm": 2, "missed mismatch": 1, "other wrong": 1, "reasons right": 1}
    assert not_compared == ["F09 ongoing_charge_pct"]
    assert len(details) == 4 and details[0].startswith("F01  ongoing_charge_pct  false alarm")


def test_right_verdict_with_wrong_reasons_is_listed():
    counts, _, details = compare.score_comparison([key_row("F15", "ongoing_charge_pct", "mismatch", "no_reason")],
                                                  [key_row("F15", "ongoing_charge_pct", "mismatch", "far_apart")])
    assert (counts["correct"], counts["reasons right"]) == (1, 0) and len(details) == 1


def test_recording_once_per_commit_and_counts(tmp_path):
    path = tmp_path / "comparison_scores.csv"
    counts = {"correct": 35, "false alarm": 0, "missed mismatch": 0, "other wrong": 3, "reasons right": 35}
    assert compare.record_comparison(counts, 38, path, "2026-11-01", "abc1234")
    assert not compare.record_comparison(counts, 38, path, "2026-11-02", "abc1234")   # nothing new
    assert compare.record_comparison(counts, 38, path, "2026-11-02", "def5678")
    lines = path.read_text().splitlines()
    assert lines[0] == ",".join(compare.SCORE_COLUMNS) and len(lines) == 3
    assert lines[1] == "2026-11-01,abc1234,38,35,0,0,3,35"


@pytest.fixture
def scored(output, monkeypatch):
    compare.run_compare(output, output / "comparison.csv")
    key = output / "key.csv"
    key.write_text("fund_id,field,verdict,reasons,notes\nF04,ongoing_charge_pct,mismatch,no_reason,\n"
                   "F04,risk_score,cant_compare,neither_none,\n", encoding="utf-8")
    monkeypatch.setattr(compare, "git_commit", lambda project, inputs: "abc1234")
    monkeypatch.setattr(compare, "is_stale", lambda path, code: False)
    return {"comparison_path": output / "comparison.csv", "key_path": key,
            "results_path": output / "scores.csv", "project": output, "output": output}


def test_a_full_current_run_is_recorded(scored, capsys):
    assert compare.run_score(**scored) == 0
    printed = capsys.readouterr().out
    assert "2 of 2 verdicts correct (false alarms 0" in printed and "Recorded in" in printed
    assert scored["results_path"].read_text().splitlines()[1].endswith(",abc1234,2,2,0,0,0,2")


def test_not_recorded_when_a_key_row_wasnt_compared(scored, capsys):
    with scored["key_path"].open("a") as f:
        f.write("F99,ongoing_charge_pct,match,,\n")
    compare.run_score(**scored)
    assert "Not recorded: 1 key row(s) weren't compared (F99 ongoing_charge_pct)" in capsys.readouterr().out
    assert not scored["results_path"].exists()


def test_not_recorded_when_uncommitted_or_out_of_date(scored, monkeypatch, capsys):
    monkeypatch.setattr(compare, "git_commit", lambda project, inputs: "abc1234+uncommitted")
    compare.run_score(**scored)
    assert "changes that aren't committed" in capsys.readouterr().out
    monkeypatch.setattr(compare, "git_commit", lambda project, inputs: "abc1234")
    monkeypatch.setattr(compare, "is_stale", lambda path, code: True)
    compare.run_score(**scored)
    assert "changed after `compare` last ran" in capsys.readouterr().out
    assert not scored["results_path"].exists()


def test_not_recorded_when_the_extractors_ran_after_compare(scored, capsys):
    import os
    newer = (scored["comparison_path"].stat().st_mtime + 10,) * 2
    os.utime(scored["output"] / "kid_extracted.csv", newer)
    compare.run_score(**scored)
    assert "changed after `compare` last ran" in capsys.readouterr().out


def test_score_needs_a_comparison(tmp_path, capsys):
    assert compare.run_score(comparison_path=tmp_path / "none.csv") == 1
    assert "run `compare` first" in capsys.readouterr().out


# --- the commands ---------------------------------------------------------------------------

def test_the_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(compare, "run_compare", lambda: calls.append("compare") or 0)
    monkeypatch.setattr(compare, "run_score", lambda: calls.append("score") or 0)
    for argv in (["compare"], ["score", "--comparison"]):
        monkeypatch.setattr(sys, "argv", ["fundcrosschecker", *argv])
        assert cli.main() == 0
    assert calls == ["compare", "score"]
    assert compare.COMPARISON_RESULTS.name == "comparison_scores.csv"


@pytest.mark.parametrize("extra", [["--unseen"], ["--factsheets"], ["--kiids"]])
def test_score_comparison_cant_be_combined(monkeypatch, capsys, extra):
    monkeypatch.setattr(compare, "run_score", lambda: pytest.fail("shouldn't score"))
    monkeypatch.setattr(sys, "argv", ["fundcrosschecker", "score", "--comparison", *extra])
    with pytest.raises(SystemExit):
        cli.main()
    assert "--comparison can't be combined" in capsys.readouterr().err


def test_the_kids_text_figures_in_words():
    f14 = compare.compare_documents(doc("F14", "1.03"), doc("F14", NOT_FOUND, notes=elsewhere("1.03", "1.10")), "kid")[0]
    # only the figure that matches is named, with its quote: the other may be another year's
    assert compare.explain(f14) == ('The KID doesn\'t print one in its cost table. '
                                    'The KID\'s text gives 1.03% (page 3: "was 1.03%"), the same as the factsheet.')
    f06 = compare.compare_documents(doc("F06", "0.69"), doc("F06", "0.00", notes=elsewhere("0.77", "0.80")), "kid")[0]
    assert compare.explain(f06) == ('Possible reasons: The KID\'s cost table shows 0%. The KID\'s text gives '
                                    '0.77% (page 3: "was 0.77%"); 0.80% (page 3: "was 0.80%").')
