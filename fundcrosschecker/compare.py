"""Compare each fund's factsheet with its KID or KIID (Story 3.1).

For every fund that has both documents in the extractors' output, the ongoing
charge and the risk score each get a verdict, match, mismatch or cant_compare,
and reason codes (listed in data/README.md under comparison_key.csv). The codes
say what the documents print; that they explain a difference is an inference, so
the report calls them possible reasons. The text not_found is never compared.

`compare` writes output/comparison.csv and prints one block per fund.
`score --comparison` scores that file against data/comparison_key.csv and
records the counts in results/comparison_scores.csv, under the same rules as
the extraction scores: a full, current run of committed code only.
"""

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .checks import to_number
from .common import NOT_FOUND
from .kid import charges_elsewhere_in
from .score import git_commit, is_stale

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "output"
EXTRACTED = {doc_type: OUTPUT / f"{doc_type}_extracted.csv" for doc_type in ("factsheet", "kid", "kiid")}
COMPARISON = OUTPUT / "comparison.csv"
COMPARISON_KEY = PROJECT / "data" / "comparison_key.csv"
COMPARISON_RESULTS = PROJECT / "results" / "comparison_scores.csv"
COMPARISON_INPUTS = ("fundcrosschecker", "data/comparison_key.csv")

FIELDS = ("ongoing_charge_pct", "risk_score")
FIELD_NAMES = {"ongoing_charge_pct": "Ongoing charge", "risk_score": "Risk score"}
FAR_APART_DAYS = 365  # a year or more between the documents' dates
VERDICTS = ("match", "mismatch", "cant_compare")
COLUMNS = ["fund_id", "field", "verdict", "reasons", "factsheet_value", "kid_type", "kid_value",
           "factsheet_page", "factsheet_quote", "kid_page", "kid_quote",
           "factsheet_date", "kid_date", "days_apart", "kid_other_figures"]


@dataclass
class Comparison:
    fund_id: str
    field: str
    verdict: str
    reasons: list[str]
    factsheet_value: str
    kid_type: str                  # "kid" or "kiid"
    kid_value: str
    factsheet_date: str
    kid_date: str
    days_apart: int | None         # factsheet date minus KID date; None if either isn't a full date
    other_figures: list[tuple[str, int, str]] = field(default_factory=list)  # the KID's charges given elsewhere
    sources: dict[str, tuple[int | None, str | None]] = field(default_factory=dict)  # page and quote per side


def compare_documents(factsheet: dict, kid: dict, kid_type: str) -> list[Comparison]:
    """Compare one fund's factsheet row with its KID (or KIID) row from the extracted CSVs."""
    days = _days_apart(factsheet["doc_date"], kid["doc_date"])
    different_class = (NOT_FOUND not in (factsheet["isin"], kid["isin"]) and factsheet["isin"] != kid["isin"])
    others = charges_elsewhere_in(kid.get("notes", "")) if kid_type == "kid" else []
    results = []
    for name in FIELDS:
        a, b = factsheet[name], kid[name]
        if different_class:
            verdict, reasons = "cant_compare", ["different_share_class"]
        else:
            verdict, reasons = _verdict(a, b)
            if name == "ongoing_charge_pct":
                reasons += _charge_reasons(verdict, a, b, others, days)
            else:
                verdict, reasons = _risk_scale(verdict, reasons, factsheet["risk_method"], kid["risk_method"])
        results.append(Comparison(factsheet["fund_id"], name, verdict, reasons, a, kid_type, b,
                                  factsheet["doc_date"], kid["doc_date"], days,
                                  others if name == "ongoing_charge_pct" else []))
    return results


def _verdict(a: str, b: str) -> tuple[str, list[str]]:
    """Compare two printed values as numbers (0.6 equals 0.60), with no tolerance."""
    x, y = _number(a), _number(b)
    if x is None and y is None:
        return "cant_compare", ["neither_none"]
    if x is None:
        return "cant_compare", ["factsheet_none"]
    if y is None:
        return "cant_compare", ["kid_none"]
    return ("match" if x == y else "mismatch"), []


def _number(value: str) -> float | None:
    """None for not_found. Anything else must be a number: the checks let nothing else
    through, so another value means the output files have been changed by hand."""
    if value == NOT_FOUND:
        return None
    number = to_number(value)
    if number is None:
        raise ValueError(f"{value!r} isn't a number")
    return number


def _charge_reasons(verdict: str, a: str, b: str, others: list[tuple[str, int, str]], days: int | None) -> list[str]:
    """What the documents print that may explain a charge verdict."""
    reasons = []
    factsheet_figure = _number(a)
    if others:
        same = factsheet_figure is not None and any(float(figure) == factsheet_figure for figure, _, _ in others)
        reasons.append("kid_text_same" if same else "kid_text_other")
    if verdict == "mismatch":
        if _number(b) == 0:  # in a mismatch, the factsheet's figure is then above 0
            reasons.insert(0, "kid_table_zero")
        if days is not None and abs(days) >= FAR_APART_DAYS:
            reasons.append("far_apart")
        if not reasons:
            reasons.append("no_reason")
    return reasons


def _risk_scale(verdict: str, reasons: list[str], factsheet_method: str, kid_method: str) -> tuple[str, list[str]]:
    """The same score only means the same risk on the same scale (SRI and SRRI are different)."""
    if verdict == "cant_compare":
        return verdict, reasons
    if NOT_FOUND in (factsheet_method, kid_method):
        return verdict, reasons + (["scale_not_stated"] if verdict == "match" else [])
    if factsheet_method != kid_method:
        return "cant_compare", ["different_scales"]
    return verdict, reasons


def _days_apart(factsheet_date: str, kid_date: str) -> int | None:
    try:
        return (date.fromisoformat(factsheet_date) - date.fromisoformat(kid_date)).days
    except ValueError:  # not_found, or only a month ("2026-09")
        return None


# --- the whole run -------------------------------------------------------------------

def compare_all(factsheets: list[dict], kids: list[dict], kiids: list[dict]) -> tuple[list[Comparison], list[str]]:
    """Pair the documents by fund and compare each pair. Returns the comparisons and
    problems: a fund with only one of its two documents, or with both a KID and a KIID."""
    problems = []
    others: dict[str, tuple[str, dict]] = {}
    for kid_type, rows in (("kid", kids), ("kiid", kiids)):
        for row in rows:
            if row["fund_id"] in others:
                problems.append(f"{row['fund_id']} has more than one KID or KIID in the output, so it wasn't compared.")
                others[row["fund_id"]] = ("", {})
            else:
                others[row["fund_id"]] = (kid_type, row)
    comparisons, seen = [], set()
    for row in factsheets:
        fund_id = row["fund_id"]
        if fund_id in seen:
            problems.append(f"{fund_id} has more than one factsheet in the output; it was compared once.")
            continue
        seen.add(fund_id)
        kid_type, kid = others.get(fund_id, (None, None))
        if kid_type is None:
            problems.append(f"{fund_id} has a factsheet but no KID or KIID in the output, so it wasn't compared.")
        elif kid_type:
            try:
                comparisons += compare_documents(row, kid, kid_type)
            except ValueError as error:
                problems.append(f"{fund_id} wasn't compared: {error}.")
    for fund_id, (kid_type, _) in others.items():
        if kid_type and fund_id not in seen:
            problems.append(f"{fund_id} has a {kid_type.upper()} but no factsheet in the output, so it wasn't compared.")
    return sorted(comparisons, key=lambda c: (c.fund_id, FIELDS.index(c.field))), problems


def add_sources(comparisons: list[Comparison], output: Path = OUTPUT) -> list[str]:
    """Add each value's page and quote from the extractor's JSON files. A JSON file left from
    an older run can differ from the CSV; then the quote isn't shown, and that's reported."""
    problems, cache = [], {}
    for c in comparisons:
        for side, doc_type, value in (("factsheet", "factsheet", c.factsheet_value), ("kid", c.kid_type, c.kid_value)):
            path = output / doc_type / f"{c.fund_id}_{doc_type}.json"
            if path not in cache:
                cache[path] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            saved = (cache[path] or {}).get("fields", {}).get(c.field)
            if saved is None or saved.get("value") != value:
                problems.append(f"{path.name} doesn't match the CSV for {c.field}, so its quote isn't shown. "
                                "Run the extractor again.")
                c.sources[side] = (None, None)
            else:
                c.sources[side] = (saved.get("page"), saved.get("quote"))
    return problems


def write_comparison(comparisons: list[Comparison], path: Path = COMPARISON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for c in comparisons:
            (fs_page, fs_quote), (kid_page, kid_quote) = c.sources.get("factsheet", (None, None)), c.sources.get("kid", (None, None))
            writer.writerow({
                "fund_id": c.fund_id, "field": c.field, "verdict": c.verdict, "reasons": ";".join(c.reasons),
                "factsheet_value": c.factsheet_value, "kid_type": c.kid_type, "kid_value": c.kid_value,
                "factsheet_page": fs_page or "", "factsheet_quote": fs_quote or "",
                "kid_page": kid_page or "", "kid_quote": kid_quote or "",
                "factsheet_date": c.factsheet_date, "kid_date": c.kid_date,
                "days_apart": "" if c.days_apart is None else c.days_apart,
                "kid_other_figures": "; ".join(f"{figure}% (page {page})" for figure, page, _ in c.other_figures),
            })


# --- the printed report ----------------------------------------------------------------

def explain(c: Comparison) -> str:
    """The verdict in words, with the reasons the documents give."""
    kid = c.kid_type.upper()
    words = {
        "different_share_class": "The two documents are for different share classes, so they aren't compared like for like.",
        "factsheet_none": "The factsheet doesn't print one.",
        "kid_none": f"The {kid} doesn't print one" + (" in its cost table." if c.field == "ongoing_charge_pct" else "."),
        "neither_none": "Neither document prints one.",
        "kid_table_zero": f"The {kid}'s cost table shows 0%.",
        "far_apart": f"The documents are {abs(c.days_apart or 0)} days apart.",
        "no_reason": "No reason found in the documents: worth asking the manager.",
        "scale_not_stated": "Same score, but the risk scale isn't named in both documents.",
        "different_scales": "The two documents use different risk scales.",
    }
    figures = ", ".join(f"{figure}% (page {page})" for figure, page, _ in c.other_figures)
    words["kid_text_same"] = (f"The {kid}'s text gives {figures}, the same as the factsheet." if len(c.other_figures) == 1
                              else f"The {kid}'s text gives {figures}, one of them the same as the factsheet.")
    words["kid_text_other"] = f"The {kid}'s text gives {figures}."
    text = " ".join(words[reason] for reason in c.reasons)
    return f"Possible reasons: {text}" if c.verdict == "mismatch" and c.reasons != ["no_reason"] else text


def print_report(comparisons: list[Comparison]) -> None:
    for fund_id in dict.fromkeys(c.fund_id for c in comparisons):
        rows = [c for c in comparisons if c.fund_id == fund_id]
        first = rows[0]
        if first.days_apart is None:
            age = "dates can't be compared"
        elif first.days_apart == 0:
            age = "same day"
        else:
            newer = "factsheet" if first.days_apart > 0 else first.kid_type.upper()
            age = f"{abs(first.days_apart)} days apart, the {newer} is newer"
        print(f"\n{fund_id}  factsheet {first.factsheet_date}, {first.kid_type.upper()} {first.kid_date} ({age})")
        for c in rows:
            shown = f"{_show(c.factsheet_value)} vs {_show(c.kid_value)}"
            print(f"  {FIELD_NAMES[c.field]:<15}{shown:<18}{c.verdict.replace('_', ' '):<14}{explain(c)}")
            for side, label in (("factsheet", "factsheet"), ("kid", c.kid_type.upper())):
                page, quote = c.sources.get(side, (None, None))
                if quote:
                    print(f"  {'':<15}{label} page {page}: \"{quote}\"")
    counts = {verdict: sum(c.verdict == verdict for c in comparisons if c.field == "ongoing_charge_pct") for verdict in VERDICTS}
    print(f"\nOngoing charge: {counts['match']} match, {counts['mismatch']} mismatch, "
          f"{counts['cant_compare']} can't compare, out of {len(comparisons) // len(FIELDS)} funds.")


def _show(value: str) -> str:
    return "-" if value == NOT_FOUND else value


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def run_compare(output: Path = OUTPUT, comparison_path: Path = COMPARISON) -> int:
    """The `compare` command."""
    paths = {doc_type: output / f"{doc_type}_extracted.csv" for doc_type in EXTRACTED}
    if not paths["factsheet"].exists() or not (paths["kid"].exists() or paths["kiid"].exists()):
        print("Run the extractors first: `factsheet`, and `kid` and/or `kiid`, on the same funds.")
        return 1
    rows = {doc_type: read_csv(path) if path.exists() else [] for doc_type, path in paths.items()}
    comparisons, problems = compare_all(rows["factsheet"], rows["kid"], rows["kiid"])
    problems += add_sources(comparisons, output)
    for problem in problems:
        print(problem)
    if not comparisons:
        print("No fund has both documents in the output, so nothing was compared.")
        return 1
    write_comparison(comparisons, comparison_path)
    print_report(comparisons)
    print(f"\nWritten to {comparison_path}")
    return 0


# --- scoring the comparison ----------------------------------------------------------

def score_comparison(rows: list[dict], key: list[dict]) -> tuple[dict[str, int], list[str], list[str]]:
    """Compare the tool's verdicts with the comparison key.

    Each key row is one of: correct; a false alarm (the tool says mismatch, the key
    doesn't), the worst kind, since it sends someone chasing a difference that isn't
    there; a missed mismatch (the key says mismatch, the tool doesn't); or another
    wrong verdict (match and cant_compare mixed up). Reasons are counted separately:
    a row's reasons are right if they're the same set of codes as the key's.
    Returns the counts, the key rows the tool didn't compare, and lines describing
    every row that isn't fully right.
    """
    tool = {(r["fund_id"], r["field"]): r for r in rows}
    counts = {"correct": 0, "false alarm": 0, "missed mismatch": 0, "other wrong": 0, "reasons right": 0}
    not_compared, details = [], []
    for k in key:
        row = tool.get((k["fund_id"], k["field"]))
        if row is None:
            not_compared.append(f"{k['fund_id']} {k['field']}")
            continue
        if row["verdict"] == k["verdict"]:
            kind = "correct"
        elif row["verdict"] == "mismatch":
            kind = "false alarm"
        elif k["verdict"] == "mismatch":
            kind = "missed mismatch"
        else:
            kind = "other wrong"
        counts[kind] += 1
        same_reasons = set(filter(None, row["reasons"].split(";"))) == set(filter(None, k["reasons"].split(";")))
        counts["reasons right"] += same_reasons
        if kind != "correct" or not same_reasons:
            details.append(f"{k['fund_id']}  {k['field']:<20}{kind:<17}key {k['verdict']} [{k['reasons']}] "
                           f"vs tool {row['verdict']} [{row['reasons']}]")
    return counts, not_compared, details


SCORE_COLUMNS = ["run_date", "git_commit", "rows", "correct", "false_alarm", "missed_mismatch", "other_wrong", "reasons_right"]


def record_comparison(counts: dict[str, int], rows: int, path: Path, run_date: str, commit: str) -> bool:
    """Add one row to the comparison score history, unless the last row has the same commit and counts."""
    row = [run_date, commit, str(rows)] + [str(counts[kind]) for kind in
                                            ("correct", "false alarm", "missed mismatch", "other wrong", "reasons right")]
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            previous = list(csv.reader(f))[1:]
        if previous and previous[-1][1:] == row[1:]:
            return False
    new_file = not path.exists() or path.stat().st_size == 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        if new_file:
            writer.writerow(SCORE_COLUMNS)
        writer.writerow(row)
    return True


def run_score(comparison_path: Path = COMPARISON, key_path: Path = COMPARISON_KEY,
              results_path: Path = COMPARISON_RESULTS, project: Path = PROJECT, output: Path = OUTPUT) -> int:
    """The `score --comparison` command."""
    if not comparison_path.exists():
        print(f"No {comparison_path}: run `compare` first.")
        return 1
    rows, key = read_csv(comparison_path), read_csv(key_path)
    counts, not_compared, details = score_comparison(rows, key)
    scored = len(key) - len(not_compared)
    print(f"{counts['correct']} of {scored} verdicts correct (false alarms {counts['false alarm']}, "
          f"missed mismatches {counts['missed mismatch']}, other wrong {counts['other wrong']}); "
          f"reasons right on {counts['reasons right']} of {scored}")
    if details:
        print("\nNot fully right (key vs tool)")
        for line in details:
            print(line)

    commit = git_commit(project, COMPARISON_INPUTS)
    extracted = [path for path in (output / f"{t}_extracted.csv" for t in EXTRACTED) if path.exists()]
    if not_compared:
        print(f"\nNot recorded: {len(not_compared)} key row(s) weren't compared ({', '.join(not_compared)}). "
              "Extract both documents for every fund in the key, then run `compare`.")
    elif is_stale(comparison_path, project / "fundcrosschecker") or any(
            comparison_path.stat().st_mtime < path.stat().st_mtime for path in extracted):
        print("\nNot recorded: the code or the extractors' output changed after `compare` last ran. Run it again first.")
    elif commit.endswith("+uncommitted"):
        print("\nNot recorded: the code or the comparison key has changes that aren't committed. Commit them, then score again.")
    elif record_comparison(counts, scored, results_path, date.today().isoformat(), commit):
        print(f"\nRecorded in {results_path}")
    else:
        print("\nNot recorded again: same commit and same counts as the last recorded run.")
    return 0
