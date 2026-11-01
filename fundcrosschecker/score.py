"""Score the KID, KIID and factsheet extractors against the answer key (Stories 2.2, 2.3 and 2.1).

Every scored value is one of:
  correct
  wrong     both have a value, but they differ
  missed    the answer key has a value, the tool says not_found
  made up   the answer key says not_found, the tool gives a value. The worst
            kind: it's how a wrong cost gets passed on to a client.

A full run (every KID in the answer key, extracted by the current code, with
the code and the answer key committed) adds one row per field to
results/kid_scores.csv, unless it's the same as the last recorded run. So every
row can be reproduced from the commit it names. That file holds counts only, never text from the PDFs, so it's
committed and keeps a history of the score.

`score --unseen` does the same for the unseen trusts (data/unseen/answer_key.csv,
PDFs in pdfs/unseen/), recording in results/unseen_kid_scores.csv, so their
score is never mixed with the development score. The first recorded run there
is the honest figure; any run after the rules change is a development score again.

`score --factsheets` scores output/factsheet_extracted.csv against the answer
key's factsheet rows, recording in results/factsheet_scores.csv. Claude reads
the factsheets, so a recorded row is reproducible from its commit together with
the cached answers in output/llm/ (asking Claude again can give other answers).

`score --unseen --factsheets` scores the unseen trusts' factsheets against the
factsheet rows of data/unseen/answer_key.csv, recording in
results/unseen_factsheet_scores.csv; again, the first recorded run is the honest one.

`score --kiids` scores output/kiid_extracted.csv against the answer key's kiid
rows (the five ordinary funds, Story 2.3), recording in results/kiid_scores.csv.
The rules were written from those five, so it's a development score.
"""

import csv
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .checks import to_number
from .common import NOT_FOUND, normalise

PROJECT = Path(__file__).resolve().parent.parent
EXTRACTED = PROJECT / "output" / "kid_extracted.csv"
ANSWER_KEY = PROJECT / "data" / "answer_key.csv"
RESULTS = PROJECT / "results" / "kid_scores.csv"
UNSEEN_KEY = PROJECT / "data" / "unseen" / "answer_key.csv"
UNSEEN_RESULTS = PROJECT / "results" / "unseen_kid_scores.csv"
EXTRACTED_FACTSHEETS = PROJECT / "output" / "factsheet_extracted.csv"
FACTSHEET_RESULTS = PROJECT / "results" / "factsheet_scores.csv"
UNSEEN_FACTSHEET_RESULTS = PROJECT / "results" / "unseen_factsheet_scores.csv"
EXTRACTED_KIIDS = PROJECT / "output" / "kiid_extracted.csv"
KIID_RESULTS = PROJECT / "results" / "kiid_scores.csv"
LABELS = {"kid": "KID", "kiid": "KIID", "factsheet": "factsheet"}

SCORED_FIELDS = ["fund_name", "isin", "share_class", "ongoing_charge_pct", "charge_label",
                 "transaction_cost_pct", "total_cost_pct", "risk_score", "risk_method", "doc_date"]
NUMBER_FIELDS = {"ongoing_charge_pct", "transaction_cost_pct", "total_cost_pct", "risk_score"}
EXACT_FIELDS = {"doc_date", "isin", "risk_method"}
KINDS = ["correct", "wrong", "missed", "made up"]
RESULT_COLUMNS = ["run_date", "git_commit", "field", "correct", "wrong", "missed", "made_up"]


@dataclass
class Result:
    fund_id: str
    field: str
    kind: str
    key_value: str
    tool_value: str


def matches(field: str, key_value: str, tool_value: str) -> bool:
    """Story 2.2's matching rules.

    not_found only matches not_found. Numbers match as numbers (0.8 = 0.80,
    0 = 0.00). Dates, ISINs and risk methods must be exactly equal. Names,
    share classes and labels ignore case, extra spaces and curly vs straight quotes.
    """
    if NOT_FOUND in (key_value, tool_value):
        return key_value == tool_value
    if field in NUMBER_FIELDS:
        key_number, tool_number = to_number(key_value), to_number(tool_value)
        return key_number is not None and key_number == tool_number
    if field in EXACT_FIELDS:
        return key_value == tool_value
    return normalise(key_value).casefold() == normalise(tool_value).casefold()


def classify(field: str, key_value: str, tool_value: str) -> str:
    if matches(field, key_value, tool_value):
        return "correct"
    if tool_value == NOT_FOUND:
        return "missed"
    if key_value == NOT_FOUND:
        return "made up"
    return "wrong"


def score(extracted: list[dict], answer_key: list[dict],
          doc_type: str = "kid") -> tuple[list[Result], list[str], list[str]]:
    """Compare each extracted document with its answer key row of the same doc_type.

    Returns the results, the answer key documents that weren't extracted, and
    problems (an extracted document that isn't in the answer key, or a document
    that appears twice). An empty answer key cell means "not checked yet", so it
    isn't scored. A document is scored once, even if it's extracted twice.
    """
    key_rows: dict[str, dict] = {}
    problems: list[str] = []
    for row in answer_key:
        if row["doc_type"] != doc_type:
            continue
        if row["fund_id"] in key_rows:
            problems.append(f"{row['fund_id']} is in the answer key more than once; only its first row was used.")
            continue
        key_rows[row["fund_id"]] = row
    results, scored = [], set()
    for row in extracted:
        fund_id = row["fund_id"]
        if fund_id in scored:
            problems.append(f"{fund_id} was extracted more than once; it was scored once.")
            continue
        scored.add(fund_id)
        if fund_id not in key_rows:
            problems.append(f"{fund_id} isn't in the answer key, so it wasn't scored.")
            continue
        for field in SCORED_FIELDS:
            key_value = key_rows[fund_id][field]
            if key_value == "":
                continue
            results.append(Result(fund_id, field, classify(field, key_value, row[field]), key_value, row[field]))
    not_extracted = sorted(set(key_rows) - {row["fund_id"] for row in extracted})
    return results, not_extracted, problems


def counts_by(results: list[Result], attribute: str) -> dict[str, Counter]:
    table: dict[str, Counter] = {}
    for result in results:
        table.setdefault(getattr(result, attribute), Counter())[result.kind] += 1
    return table


def is_stale(extracted_csv: Path, code_dir: Path) -> bool:
    """True if any code file changed after the CSV was written, so the CSV may not match the code."""
    newest_code = max(path.stat().st_mtime for path in code_dir.glob("*.py"))
    return extracted_csv.stat().st_mtime < newest_code


SCORE_INPUTS = ("fundcrosschecker", "data/answer_key.csv")
UNSEEN_INPUTS = ("fundcrosschecker", "data/unseen/answer_key.csv")


def git_commit(project: Path, inputs: tuple[str, ...] = SCORE_INPUTS) -> str:
    """The last commit that changed the code or the answer key: the version the score belongs to.

    Commits that only touch other files (such as the score history itself) don't
    count, so recording a score and committing it doesn't make the next run look
    new. Marked "+uncommitted" if the code or the answer key has changed since,
    because then that commit alone can't reproduce the score.
    """
    try:
        sha = _git(project, "log", "-1", "--format=%h", "--", *inputs)
        changed = _git(project, "status", "--porcelain", "--", *inputs)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    if not sha:
        return "unknown"
    return f"{sha}+uncommitted" if changed else sha


def _git(project: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, check=True).stdout.strip()


def record(results: list[Result], path: Path, run_date: str, commit: str) -> bool:
    """Add one summary row per field to the results CSV (header written once).

    Returns False, writing nothing, if the last recorded run had the same
    commit and the same counts: running the scorer again adds no history.
    """
    if not results:
        return False  # nothing was scored, so there's nothing to add to the history
    by_field = counts_by(results, "field")
    rows = [[run_date, commit, field, str(c["correct"]), str(c["wrong"]), str(c["missed"]), str(c["made up"])]
            for field, c in ((f, by_field[f]) for f in SCORED_FIELDS if f in by_field)]
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            previous = list(csv.reader(f))[1:]
        if [row[1:] for row in previous[-len(rows):]] == [row[1:] for row in rows]:
            return False
    new_file = not path.exists() or path.stat().st_size == 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        if new_file:
            writer.writerow(RESULT_COLUMNS)
        writer.writerows(rows)
    return True


def print_report(results: list[Result]) -> None:
    total = Counter(result.kind for result in results)
    print(f"{total['correct']} of {len(results)} values correct "
          f"(wrong {total['wrong']}, missed {total['missed']}, made up {total['made up']})")
    for title, attribute in (("By field", "field"), ("By document", "fund_id")):
        print(f"\n{title:<22}" + "".join(f"{kind:>9}" for kind in KINDS))
        for name, c in counts_by(results, attribute).items():
            print(f"{name:<22}" + "".join(f"{c[kind]:>9}" for kind in KINDS))
    not_correct = [r for r in results if r.kind != "correct"]
    if not_correct:
        print("\nNot correct (answer key vs tool)")
        for r in not_correct:
            print(f"{r.fund_id}  {r.field:<22}{r.kind:<9} {r.key_value!r} vs {r.tool_value!r}")


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def run(extracted_path: Path = EXTRACTED, key_path: Path = ANSWER_KEY, results_path: Path = RESULTS,
        project: Path = PROJECT, inputs: tuple[str, ...] = SCORE_INPUTS, pdf_folder: str = "pdfs/",
        doc_type: str = "kid") -> int:
    """The `score` command. `inputs` are the files a score depends on; `pdf_folder` is where its PDFs are."""
    if not extracted_path.exists():
        print(f"No {extracted_path}: run the extractor first (python -m fundcrosschecker {doc_type} {pdf_folder}).")
        return 1
    if not key_path.exists():
        print(f"No answer key at {key_path}.")
        return 1
    extracted, answer_key = read_csv(extracted_path), read_csv(key_path)
    needed = {"fund_id", *SCORED_FIELDS}
    for name, rows, columns in (("extractor output", extracted, needed), ("answer key", answer_key, needed | {"doc_type"})):
        missing = sorted(columns - set(rows[0] if rows else columns))
        if missing:
            print(f"The {name} is missing columns: {', '.join(missing)}.")
            return 1
    results, not_extracted, problems = score(extracted, answer_key, doc_type)
    for problem in problems:
        print(problem)
    print_report(results)

    # Only a full run of the current, committed code goes into the history, so the rows stay comparable.
    commit = git_commit(project, inputs)
    if not_extracted:
        print(f"\nNot recorded: {len(not_extracted)} {LABELS[doc_type]}(s) weren't extracted ({', '.join(not_extracted)}). "
              f"Run the extractor on {pdf_folder} to score them all.")
    elif not results:
        print("\nNot recorded: nothing was scored.")
    elif any("in the answer key more than once" in problem for problem in problems):
        print("\nNot recorded: the answer key has a document twice. Fix it, then score again.")
    elif is_stale(extracted_path, project / "fundcrosschecker"):
        print("\nNot recorded: the code changed after the extractor last ran. Run it again first.")
    elif commit.endswith("+uncommitted"):
        print("\nNot recorded: the code or the answer key has changes that aren't committed. Commit them, then score again.")
    elif record(results, results_path, date.today().isoformat(), commit):
        print(f"\nRecorded in {results_path}")
    else:
        print("\nNot recorded again: same commit and same counts as the last recorded run.")
    return 0
