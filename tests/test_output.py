"""Tests for writing results (output.py): normal, edge and invalid inputs."""

import csv
import json

import pytest

from fundcrosschecker import output
from fundcrosschecker.common import NOT_FOUND, Field


def test_csv_row_and_json_keep_every_value(tmp_path):
    fields = {"fund_name": Field("F&C Investment Trust PLC", 1, "F&C INVESTMENT TRUST PLC"), "isin": Field(NOT_FOUND)}
    row = output.csv_row("F16", "kid", fields, ["a note.", "another."])
    assert row == {"fund_id": "F16", "doc_type": "kid", "notes": "a note. another.",
                   "fund_name": "F&C Investment Trust PLC", "isin": NOT_FOUND}
    path = tmp_path / "kid" / "F16_kid.json"
    output.write_json(path, "F16", "kid", "ab" * 32, fields, [])
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["fields"]["fund_name"] == {"value": "F&C Investment Trust PLC", "page": 1, "quote": "F&C INVESTMENT TRUST PLC"}


def test_json_keeps_non_ascii_text(tmp_path):
    path = tmp_path / "x.json"
    output.write_json(path, "F09", "kid", "00", {"charge_label": Field("Ongoing Charges Ratio (‘OCR’)", 1, "£1,000 ‘OCR’")}, [])
    assert "‘OCR’" in path.read_text(encoding="utf-8")  # written as is, not as \u escapes


def test_csv_has_the_answer_key_columns_in_order(tmp_path):
    path = tmp_path / "out.csv"
    output.write_csv(path, [{"fund_id": "F16", "doc_type": "kid", "notes": ""}])  # edge: a row with no fields
    with path.open() as f:
        rows = list(csv.reader(f))
    assert rows[0] == output.COLUMNS
    assert rows[1] == ["F16", "kid"] + [""] * (len(output.COLUMNS) - 2)  # missing values are empty cells


def test_csv_with_no_rows_is_just_the_header(tmp_path):
    path = tmp_path / "out.csv"
    output.write_csv(path, [])
    assert path.read_text().strip() == ",".join(output.COLUMNS)


def test_a_field_that_isnt_an_answer_key_column_is_an_error(tmp_path):
    # Invalid: better to stop than to drop a value silently.
    with pytest.raises(ValueError):
        output.write_csv(tmp_path / "out.csv", [{"fund_id": "F16", "doc_type": "kid", "notes": "", "extra": "1"}])


@pytest.mark.parametrize("quote, value, expected", [
    ("Ongoing charges 0.45%", "0.45", "Ongoing charges 0.45%"),       # short: unchanged
    ("", "", ""),                                                     # empty
    ("a" * 61, "zzz", "a" * 59 + "…"),                                # value not in the quote: start kept
    ("x" * 80 + " 0.45%", "0.45", "…" + ("x" * 80 + " 0.45")[-58:] + "…"),  # value near the end stays in view
])
def test_short_quote(quote, value, expected):
    shortened = output.short_quote(quote, value)
    assert shortened == expected
    assert len(shortened) <= 60


def test_print_table_lists_only_known_columns(capsys):
    output.print_table("F16", {"fund_name": Field("A plc", 1, "A plc"), "not_a_column": Field("x", 1, "x")})
    printed = capsys.readouterr().out
    assert "A plc" in printed and "not_a_column" not in printed
    output.print_table("empty", {})  # edge: nothing to show
    assert "field" in capsys.readouterr().out
