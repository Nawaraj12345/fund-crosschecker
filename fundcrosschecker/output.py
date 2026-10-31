"""Write extraction results: JSON with sources, a CSV in answer key format, and a terminal table."""

import csv
import json
from pathlib import Path

from .common import Field

# Same names and order as data/answer_key.csv, so the scorer can compare them.
COLUMNS = [
    "fund_id", "doc_type", "fund_name", "isin", "share_class", "ongoing_charge_pct",
    "charge_label", "transaction_cost_pct", "total_cost_pct", "risk_score",
    "risk_method", "doc_date", "notes",
]


def write_json(path: Path, fund_id: str, doc_type: str, sha256: str,
               fields: dict[str, Field], notes: list[str]) -> None:
    result = {
        "fund_id": fund_id,
        "doc_type": doc_type,
        "file_sha256": sha256,
        "fields": {name: vars(field) for name, field in fields.items()},
        "notes": " ".join(notes),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def csv_row(fund_id: str, doc_type: str, fields: dict[str, Field], notes: list[str]) -> dict[str, str]:
    row = {"fund_id": fund_id, "doc_type": doc_type, "notes": " ".join(notes)}
    row.update({name: field.value for name, field in fields.items()})
    return row


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def short_quote(quote: str, value: str, width: int = 60) -> str:
    """Shorten a quote for the terminal, keeping the value in view. "…" marks cut text."""
    if len(quote) <= width:
        return quote
    end = quote.find(value) + len(value) if value in quote else 0
    if end <= width - 1:
        return quote[:width - 1] + "…"
    start = end - (width - 2)
    return "…" + quote[start:end] + ("…" if end < len(quote) else "")


def print_table(title: str, fields: dict[str, Field]) -> None:
    print(f"\n{title}")
    print(f"{'field':<22}{'value':<34}{'page':<6}quote")
    for name in COLUMNS:
        if name in fields:
            f = fields[name]
            quote = short_quote(f.quote or "", f.value)
            print(f"{name:<22}{f.value[:32]:<34}{str(f.page or ''):<6}{quote}")
