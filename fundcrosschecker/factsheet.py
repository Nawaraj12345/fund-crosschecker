"""Extract a fund factsheet's figures with Claude (Story 2.1).

Factsheets have no fixed layout (19 providers, 19 layouts), so instead of rules
the page text goes to Claude, which answers each field with the value, the page
and the exact words it read it from. Every answer then goes through the same
checks as the KID extractor (checks.py): a value whose quote isn't on that page,
isn't in its quote, or has the wrong format becomes not_found, with the reason
in the notes. So Claude can miss a figure, but it can't put one in the output
that the PDF doesn't show.

Answers are cached in output/llm/ by the PDF's hash, the model and the prompt,
so running again costs nothing and gives the same answers. Changing the prompt
or the model asks again.
"""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from .checks import check_fields
from .common import NOT_FOUND, Field

MODEL = "claude-opus-5-5"
EFFORT = "high"  # reading a messy layout carefully matters more than speed here
FIELDS = ["fund_name", "isin", "share_class", "ongoing_charge_pct", "charge_label",
          "transaction_cost_pct", "total_cost_pct", "risk_score", "risk_method", "doc_date"]

# The rules are data/README.md's answer key rules, so the tool and the answer key read
# factsheets the same way.
SYSTEM_PROMPT = """You read UK fund factsheets and record exactly what they print.

You get the text of each page, inside <page number="N"> tags. For each field, give:
- value: the value, written as below, or "not_found" if the factsheet doesn't print it.
- page: the page number it is on.
- quote: a short piece of text copied exactly from that page (a line or part of a line)
  that contains the value as printed. Copy it character for character; don't fix spacing,
  spelling or symbols. For not_found, page and quote may be null.

Record only what is printed. Never work a value out, never fill a gap from what the rules
say should be there, and never use outside knowledge of the fund.

Fields:
- fund_name: the fund's name exactly as printed at the top (not the share class, unless
  the name and class are printed as one).
- isin: the 12-character ISIN of the share class the factsheet is about.
- share_class: the share class as printed, e.g. "A Accumulation". not_found if none is named.
- ongoing_charge_pct: the ongoing charge as a number without the % sign, digits as printed
  ("0.20%" -> "0.20"). It may be called Ongoing charge, OCF, Ongoing Charges Ratio or similar.
  A management fee on its own is not an ongoing charge.
- charge_label: the label printed next to that figure, e.g. "Ongoing Charges Figure (OCF)".
  not_found if ongoing_charge_pct is not_found.
- transaction_cost_pct: portfolio transaction costs in percent, only if printed as such.
- total_cost_pct: a total yearly cost in percent (e.g. "Annual cost impact"), only if printed.
- risk_score: the risk indicator's number from 1 to 7, only if the number is printed as text
  (a shaded box in a graphic doesn't count).
- risk_method: "SRRI" or "SRI" if the factsheet names that indicator (in full or as the
  abbreviation), "other" for any other named 1-7 scale, otherwise not_found.
- doc_date: the main "as at" date at the top of the factsheet, as YYYY-MM-DD (YYYY-MM if only
  the month is given). Other dates, such as performance dates further down, don't count.
"""


class Answer(BaseModel):
    """Claude's answer for one field."""

    value: str
    page: int | None
    quote: str | None


class FactsheetAnswers(BaseModel):
    """The structured output Claude must return: one answer per answer key field."""

    fund_name: Answer
    isin: Answer
    share_class: Answer
    ongoing_charge_pct: Answer
    charge_label: Answer
    transaction_cost_pct: Answer
    total_cost_pct: Answer
    risk_score: Answer
    risk_method: Answer
    doc_date: Answer


def extract(pages: list[str], pdf_sha256: str, client, cache_dir: Path) -> tuple[dict[str, Field], list[str]]:
    """Return the factsheet's fields (keyed by answer key column, in its order) and notes.

    `client` is an anthropic.Anthropic(); it's only used when the answer isn't cached.
    """
    if not pages:
        raise ValueError("the PDF has no pages")
    notes: list[str] = []
    answers = _cached_or_asked(pages, pdf_sha256, client, cache_dir, notes)
    fields = {name: Field(NOT_FOUND) for name in FIELDS}
    if answers is not None:
        for name in FIELDS:
            answer = answers[name]
            # An empty value would pass the quote check (it's "in" every quote), so it counts as not_found.
            fields[name] = Field(answer["value"].strip() or NOT_FOUND, answer["page"], answer["quote"])
    check_fields(fields, pages, notes)
    return fields, notes


def prompt_text(pages: list[str]) -> str:
    """The factsheet's pages as Claude sees them."""
    return "\n".join(f'<page number="{n}">\n{text}\n</page>' for n, text in enumerate(pages, start=1))


def cache_key(pdf_sha256: str) -> str:
    """Changes when the PDF, the model, the prompt or the answer format changes."""
    setup = json.dumps([MODEL, EFFORT, SYSTEM_PROMPT, FactsheetAnswers.model_json_schema()], sort_keys=True)
    return f"{pdf_sha256[:16]}-{hashlib.sha256(setup.encode()).hexdigest()[:12]}"


def _cached_or_asked(pages, pdf_sha256, client, cache_dir: Path, notes: list[str]) -> dict | None:
    path = cache_dir / f"{cache_key(pdf_sha256)}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    answers = _ask_claude(pages, client, notes)
    if answers is not None:  # a failed answer isn't cached, so the next run asks again
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(answers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return answers


def _ask_claude(pages: list[str], client, notes: list[str]) -> dict | None:
    """One request; the answer comes back as FactsheetAnswers or not at all."""
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},
        # If the model declines, the request re-runs on Anthropic's recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt_text(pages)}],
        output_format=FactsheetAnswers,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        notes.append(f"Claude gave no usable answer (stop reason: {response.stop_reason}), so every field is not_found.")
        return None
    return response.parsed_output.model_dump()
