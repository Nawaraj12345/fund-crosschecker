"""Extract a fund factsheet's figures with Claude (Story 2.1).

Factsheets have no fixed layout (the 19 here come from 16 providers, each with
its own), so instead of rules the page text goes to Claude, which answers each
field with the value, the page and the exact words it read it from. Every answer
then goes through the same checks as the KID extractor (checks.py): a value
whose quote isn't on that page, isn't in its quote, or has the wrong format
becomes not_found, with the reason in the notes. So Claude can miss a figure,
but it can't put one in the output that the PDF doesn't show.

Answers are cached in output/llm/ by the PDF's hash, the model and the prompt,
so running again costs nothing and gives the same answers. Changing the prompt
or the model asks again.
"""

import hashlib
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from .checks import check_fields
from .common import NOT_FOUND, Field

MODEL = "claude-opus-5-5"
PRICE_PER_MILLION = {"input": 4.00, "output": 20.00}  # US$, this model's list price; for the cost line only
EFFORT = "high"  # reading a messy layout carefully matters more than speed here
FIELDS = ["fund_name", "isin", "share_class", "ongoing_charge_pct", "charge_label",
          "transaction_cost_pct", "total_cost_pct", "risk_score", "risk_method", "doc_date"]

# Based on data/README.md's answer key rules, so the tool and the answer key read
# factsheets the same way.
SYSTEM_PROMPT = """You read UK fund factsheets and record exactly what they print.

You get the text of each page, inside <page number="N"> tags. For each field, give:
- value: the value, written as below, or "not_found" if the factsheet doesn't print it.
- page: the page number it is on.
- quote: a short piece of text copied exactly from that page (a line or part of a line)
  that contains the whole value as printed (for a label, all of its words). Pick a place
  where the value is printed in one piece, e.g. the title for the fund name. Copy it
  character for character; don't fix spacing, spelling or symbols. For not_found, page and
  quote may be null.

Record only what is printed. Never work a value out, never fill a gap from what the rules
say should be there, and never use outside knowledge of the fund.

Fields:
- fund_name: the fund's name exactly as printed at the top, without the share class (even
  when the class is printed on the same line, e.g. "... Fund P Accumulation Shares" or
  "... PLC Income"), and without a ticker or abbreviation in brackets, e.g. "(HFEL)".
- isin: the 12-character ISIN of the share class the factsheet is about.
- share_class: the share class the factsheet is about, as named in its title, key facts or
  fund details, in its fullest form there, e.g. "Income Shares" rather than "Income". A
  mention in descriptive or legal text (e.g. "its Ordinary Shares are traded on ...") doesn't
  count. not_found if no share class is named in those places.
- ongoing_charge_pct: the ongoing charge as a number without the % sign, digits as printed
  ("0.20%" -> "0.20"). It may be called Ongoing charge, OCF, Ongoing Charges Ratio or similar.
  A management fee on its own is not an ongoing charge.
- charge_label: the label exactly as printed next to that figure, e.g. "Ongoing Charges
  Figure (OCF)". Include words in brackets only if they are printed as part of the label
  itself, e.g. "Ongoing charges (year end 31 Aug 2025)"; never add a date or period from
  elsewhere. Leave out footnote marks such as a trailing number or "*".
  not_found if ongoing_charge_pct is not_found.
- transaction_cost_pct: portfolio transaction costs in percent, only if printed as such.
- total_cost_pct: a total yearly cost figure of the kind a KID prints, labelled e.g. "Annual
  cost impact", "Total costs" or "Impact on return (RIY) per year", only if printed. An
  expense ratio or charge (e.g. "Total expenses", "Total expense ratio", an ongoing charge or
  a management fee) is not this field.
- risk_score: the risk indicator's number from 1 to 7, only if the number is printed as text
  (a shaded box in a graphic doesn't count).
- risk_method: "SRRI" or "SRI" if the factsheet names that indicator (in full or as the
  abbreviation), "other" for any other named 1-7 scale, otherwise not_found.
- doc_date: the date the factsheet is "as at", as YYYY-MM-DD: the full date at the top if
  there is one. If the top gives only a month (e.g. "September 2026"), use the full "as at"
  date the factsheet gives for its figures in that month (e.g. "NAV as at 30 September
  2026"), quoting where it's printed; YYYY-MM only if no day is printed for that month.
  Other dates, such as charge periods or performance periods, don't count.
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
    """Changes when the PDF, the model, the effort, the prompt or the answer format changes."""
    setup = json.dumps([MODEL, EFFORT, SYSTEM_PROMPT, FactsheetAnswers.model_json_schema()], sort_keys=True)
    return f"{pdf_sha256[:16]}-{hashlib.sha256(setup.encode()).hexdigest()[:12]}"


def _cached_or_asked(pages, pdf_sha256, client, cache_dir: Path, notes: list[str]) -> dict | None:
    path = cache_dir / f"{cache_key(pdf_sha256)}.json"
    if path.exists():
        # Checked against the answer format, so a damaged file stops with a clear message instead of a
        # confusing error later. It isn't replaced automatically, because asking Claude again costs money.
        try:
            return FactsheetAnswers.model_validate_json(path.read_text(encoding="utf-8")).model_dump()
        except ValueError as error:  # pydantic's ValidationError, for bad JSON or missing fields
            raise ValueError(f"the cached answer {path} is damaged or incomplete; delete it to ask Claude again") from error
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
    usage = getattr(response, "usage", None)
    if usage is None:  # the API always reports usage, but a missing figure shouldn't lose a good answer
        print("Asked Claude: token use not reported", file=sys.stderr)
    else:
        cost = (usage.input_tokens * PRICE_PER_MILLION["input"] + usage.output_tokens * PRICE_PER_MILLION["output"]) / 1e6
        print(f"Asked Claude: {usage.input_tokens:,} input + {usage.output_tokens:,} output tokens, about ${cost:.3f}",
              file=sys.stderr)
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        notes.append(f"Claude gave no usable answer (stop reason: {response.stop_reason}), so every field is not_found.")
        return None
    return response.parsed_output.model_dump()
