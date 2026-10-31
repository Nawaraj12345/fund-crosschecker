"""Tests for the factsheet extractor (Story 2.1). A fake client stands in for Claude,
so these run without an API key and cost nothing."""

from types import SimpleNamespace

import pytest

from fundcrosschecker import factsheet
from fundcrosschecker.common import NOT_FOUND

PAGES = [
    "F&C Investment Trust PLC\nMonthly factsheet as at 30 September 2026\n"
    "ISIN GB00BS88V647 Ordinary Shares\nOngoing charges 0.45%",
    "Risk: Synthetic Risk and Reward Indicator (SRRI) 6",
]
SHA = "ab" * 32


def answer(value=NOT_FOUND, page=None, quote=None):
    return {"value": value, "page": page, "quote": quote}


def good_answers(**changes):
    """Answers a careful reader would give for PAGES; pass field=answer(...) to change one."""
    answers = {name: answer() for name in factsheet.FIELDS}
    answers.update(
        fund_name=answer("F&C Investment Trust PLC", 1, "F&C Investment Trust PLC"),
        isin=answer("GB00BS88V647", 1, "ISIN GB00BS88V647"),
        share_class=answer("Ordinary Shares", 1, "GB00BS88V647 Ordinary Shares"),
        ongoing_charge_pct=answer("0.45", 1, "Ongoing charges 0.45%"),
        charge_label=answer("Ongoing charges", 1, "Ongoing charges 0.45%"),
        risk_score=answer("6", 2, "(SRRI) 6"),
        risk_method=answer("SRRI", 2, "Synthetic Risk and Reward Indicator (SRRI)"),
        doc_date=answer("2026-09-30", 1, "as at 30 September 2026"),
    )
    answers.update(changes)
    return answers


class FakeClient:
    """Records each request and returns a canned response, like client.beta.messages.parse."""

    def __init__(self, answers=None, stop_reason="end_turn"):
        self.requests = []
        parsed = factsheet.FactsheetAnswers.model_validate(answers) if answers else None
        usage = SimpleNamespace(input_tokens=10_000, output_tokens=2_000)
        self._response = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage)
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **request):
        self.requests.append(request)
        return self._response


def run(client, tmp_path, pages=PAGES):
    return factsheet.extract(pages, SHA, client, tmp_path / "llm")


def test_answers_that_pass_the_checks_are_kept(tmp_path):
    fields, notes = run(FakeClient(good_answers()), tmp_path)
    assert list(fields) == factsheet.FIELDS
    assert fields["ongoing_charge_pct"].value == "0.45"
    assert (fields["risk_score"].value, fields["risk_score"].page) == ("6", 2)
    assert fields["transaction_cost_pct"].value == NOT_FOUND
    assert notes == []


@pytest.mark.parametrize("name, bad, reason", [
    # a number that isn't in the PDF: the quote check stops it
    ("ongoing_charge_pct", answer("0.54", 1, "Ongoing charges 0.54%"), "quote not found on page 1"),
    # a real quote that doesn't hold the value
    ("ongoing_charge_pct", answer("0.5", 1, "Ongoing charges 0.45%"), "value not in its quote"),
    # right words, wrong page
    ("isin", answer("GB00BS88V647", 2, "ISIN GB00BS88V647"), "quote not found on page 2"),
    # format checks
    ("isin", answer("GB00BS88V648", 1, "GB00BS88V648"), "not a valid ISIN"),
    ("risk_score", answer("8", 2, "(SRRI) 6"), "not a whole number from 1 to 7"),
    ("doc_date", answer("2026-09", 1, "30 September 2026"), "not a YYYY-MM-DD date"),
    ("fund_name", answer("F&C Investment Trust PLC", None, None), "no page or quote"),
])
def test_answers_that_fail_a_check_become_not_found(tmp_path, name, bad, reason):
    fields, notes = run(FakeClient(good_answers(**{name: bad})), tmp_path)
    assert fields[name].value == NOT_FOUND
    assert any(reason in note for note in notes)


def test_an_empty_value_is_not_found(tmp_path):
    fields, _ = run(FakeClient(good_answers(share_class=answer("  ", 1, "Ordinary Shares"))), tmp_path)
    assert fields["share_class"].value == NOT_FOUND


def test_removing_the_charge_removes_its_label(tmp_path):
    answers = good_answers(ongoing_charge_pct=answer("0.54", 1, "Ongoing charges 0.54%"))
    fields, _ = run(FakeClient(answers), tmp_path)
    assert fields["charge_label"].value == NOT_FOUND


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_no_usable_answer_gives_not_found_and_is_not_cached(tmp_path, stop_reason):
    client = FakeClient(None, stop_reason)
    fields, notes = run(client, tmp_path)
    assert {f.value for f in fields.values()} == {NOT_FOUND}
    assert stop_reason in notes[0]
    run(client, tmp_path)
    assert len(client.requests) == 2  # asked again: nothing was cached


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_an_answer_that_stopped_early_isnt_used(tmp_path, stop_reason):
    # Even if something parsed, an answer cut short or declined may be incomplete.
    fields, notes = run(FakeClient(good_answers(), stop_reason), tmp_path)
    assert {f.value for f in fields.values()} == {NOT_FOUND}
    assert stop_reason in notes[0]


def test_each_request_reports_its_cost(tmp_path, capsys):
    run(FakeClient(good_answers()), tmp_path)
    assert "10,000 input + 2,000 output tokens, about $0.080" in capsys.readouterr().err
    run(FakeClient(good_answers()), tmp_path)  # cached: no request, so no cost line
    assert "Asked Claude" not in capsys.readouterr().err


def test_cost_line_at_the_edges(tmp_path, capsys):
    client = FakeClient(good_answers())
    client._response.usage = SimpleNamespace(input_tokens=0, output_tokens=0)  # zero
    run(client, tmp_path)
    assert "0 input + 0 output tokens, about $0.000" in capsys.readouterr().err
    client = FakeClient(good_answers())
    client._response.usage = SimpleNamespace(input_tokens=999_999_999, output_tokens=123_456_789)  # very large
    factsheet.extract(PAGES, "cd" * 32, client, tmp_path / "llm")
    assert "999,999,999 input + 123,456,789 output tokens, about $6469.136" in capsys.readouterr().err


def test_missing_usage_keeps_the_answer(tmp_path, capsys):
    client = FakeClient(good_answers())
    client._response.usage = None  # invalid: the API always sends usage, but it mustn't lose a good answer
    fields, _ = run(client, tmp_path)
    assert fields["ongoing_charge_pct"].value == "0.45"
    assert "token use not reported" in capsys.readouterr().err


@pytest.mark.parametrize("damage", ["{not json", '{"fund_name": {"value": "x", "page": 1, "quote": "x"}}'])
def test_a_damaged_cache_file_stops_with_a_clear_message(tmp_path, damage):
    cache = tmp_path / "llm"
    cache.mkdir()
    (cache / f"{factsheet.cache_key(SHA)}.json").write_text(damage)  # bad JSON, or fields missing
    client = FakeClient(good_answers())
    with pytest.raises(ValueError, match="damaged or incomplete; delete it to ask Claude again"):
        factsheet.extract(PAGES, SHA, client, cache)
    assert client.requests == []  # not replaced by asking again, which would cost money


def test_all_not_found_is_a_valid_answer(tmp_path):
    fields, notes = run(FakeClient({name: answer() for name in factsheet.FIELDS}), tmp_path)
    assert {f.value for f in fields.values()} == {NOT_FOUND}
    assert notes == []


def test_answers_are_cached(tmp_path):
    client = FakeClient(good_answers())
    first, _ = run(client, tmp_path)
    second, _ = run(client, tmp_path)
    assert len(client.requests) == 1
    assert first == second
    assert len(list((tmp_path / "llm").glob("*.json"))) == 1


def test_changing_the_prompt_asks_again(tmp_path, monkeypatch):
    client = FakeClient(good_answers())
    run(client, tmp_path)
    monkeypatch.setattr(factsheet, "SYSTEM_PROMPT", factsheet.SYSTEM_PROMPT + " Changed.")
    run(client, tmp_path)
    assert len(client.requests) == 2


def test_the_request(tmp_path):
    client = FakeClient(good_answers())
    run(client, tmp_path)
    request = client.requests[0]
    assert request["model"] == factsheet.MODEL
    assert request["output_format"] is factsheet.FactsheetAnswers
    assert request["fallbacks"] == "default"
    assert request["system"] == factsheet.SYSTEM_PROMPT
    content = request["messages"][0]["content"]
    assert '<page number="1">' in content and '<page number="2">' in content
    assert "Ongoing charges 0.45%" in content


def one_line(text):
    """Spaces and line breaks as single spaces, so re-wrapping the prompt doesn't break the test."""
    return " ".join(text.split())


@pytest.mark.parametrize("rule", [
    "Record only what is printed.",
    "never fill a gap from what the rules say should be there",
    # Added in prompt v3, after v2 made up F16's share class from a legal sentence:
    "A mention in descriptive or legal text",
    # Added in prompt v4, after v3 made up F16's total cost from "Total expenses" (two lines of one rule):
    "An expense ratio or charge",
    "is not this field.",
    # Added in prompt v3, after v2 added a date from elsewhere to F11's label:
    "never add a date or period from elsewhere",
])
def test_the_prompt_keeps_its_key_rules(rule):
    # Changing one of these should be a deliberate decision, so it has to change this test too.
    assert one_line(rule) in one_line(factsheet.SYSTEM_PROMPT)


def test_every_answer_key_field_is_asked_for():
    assert list(factsheet.FactsheetAnswers.model_fields) == factsheet.FIELDS


def test_empty_pdf_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        run(FakeClient(good_answers()), tmp_path, pages=[])
