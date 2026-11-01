"""Command line: extract the figures from trust KIDs, fund KIIDs and factsheets, and score them.

    .venv/bin/python -m fundcrosschecker kid pdfs/F16_kid.pdf
    .venv/bin/python -m fundcrosschecker kid pdfs/          (every *_kid.pdf in the folder)
    .venv/bin/python -m fundcrosschecker score              (compare with the answer key)
    .venv/bin/python -m fundcrosschecker kid pdfs/unseen/
    .venv/bin/python -m fundcrosschecker score --unseen     (the unseen trusts, scored separately)
    .venv/bin/python -m fundcrosschecker factsheet pdfs/    (every *_factsheet.pdf, read by Claude)
    .venv/bin/python -m fundcrosschecker score --factsheets
    .venv/bin/python -m fundcrosschecker factsheet pdfs/unseen/
    .venv/bin/python -m fundcrosschecker score --unseen --factsheets   (the unseen trusts' factsheets)
    .venv/bin/python -m fundcrosschecker kiid pdfs/         (every *_kiid.pdf: the ordinary funds)
    .venv/bin/python -m fundcrosschecker score --kiids
    .venv/bin/python -m fundcrosschecker compare            (each factsheet against its KID or KIID)
    .venv/bin/python -m fundcrosschecker score --comparison

Run these from the project folder, which is where Python finds the package.
`kid` writes output/kid/<fund_id>_kid.json and output/kid_extracted.csv in the
project's output/ folder; `kiid` writes output/kiid/ and output/kiid_extracted.csv
the same way; `factsheet` writes output/factsheet/ and
output/factsheet_extracted.csv, and caches Claude's answers in output/llm/.
Each CSV holds only the documents from the latest run (a run that reads none
leaves it as it was); JSON files from earlier runs are left as they are.
`factsheet` needs an Anthropic API key (ANTHROPIC_API_KEY) for any factsheet
whose answer isn't cached yet. `score` is described in score.py, and `compare`
and `score --comparison` in compare.py.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

from . import compare, factsheet, kid, kiid, labelwrap, output, riskscale, score
from .pdftext import read_pages

OUTPUT = Path(__file__).resolve().parent.parent / "output"
LABELS = {"kid": "KID", "kiid": "KIID", "factsheet": "factsheet"}  # how each document type is named in messages
# Documents whose risk score can come from the scale graphic when the text doesn't give it
# (riskscale.py). Not KIIDs: all five give theirs in the text.
GRAPHIC_RISK = ("kid", "factsheet")
# Documents whose charge label can get back a bracket that wraps onto the line below
# (labelwrap.py). Not KIDs: their rules join a wrapped label themselves.
WRAPPED_LABELS = ("factsheet",)


def pdf_files(paths: list[Path], doc_type: str) -> tuple[list[Path], int]:
    """The files to read, and how many of the given paths don't exist. A folder gives its *_<doc_type>.pdf files."""
    files, missing = [], 0
    for path in paths:
        if not path.exists():
            print(f"Couldn't find {path}", file=sys.stderr)
            missing += 1
        elif path.is_dir():
            files.extend(sorted(path.glob(f"*_{doc_type}.pdf")))
        else:
            files.append(path)
    # The same file given twice (a folder and one of its files) is read once, so it isn't scored twice.
    unique, seen = [], set()
    for path in files:
        if path.resolve() not in seen:
            seen.add(path.resolve())
            unique.append(path)
    return unique, missing


def main() -> int:
    parser = argparse.ArgumentParser(prog="fundcrosschecker")
    sub = parser.add_subparsers(dest="command", required=True)
    kid_cmd = sub.add_parser("kid", help="extract figures from trust KIDs")
    kid_cmd.add_argument("paths", nargs="+", type=Path, help="KID PDFs, or folders of them")
    kiid_cmd = sub.add_parser("kiid", help="extract figures from ordinary funds' KIIDs")
    kiid_cmd.add_argument("paths", nargs="+", type=Path, help="KIID PDFs, or folders of them")
    factsheet_cmd = sub.add_parser("factsheet", help="extract figures from factsheets with Claude")
    factsheet_cmd.add_argument("paths", nargs="+", type=Path, help="factsheet PDFs, or folders of them")
    sub.add_parser("compare", help="compare each fund's factsheet with its KID or KIID")
    score_cmd = sub.add_parser("score", help="compare the extractor's output with the answer key")
    score_cmd.add_argument("--unseen", action="store_true",
                           help="use the unseen trusts' answer key (data/unseen/) and score history")
    score_cmd.add_argument("--factsheets", action="store_true",
                           help="score output/factsheet_extracted.csv instead of the KIDs")
    score_cmd.add_argument("--kiids", action="store_true",
                           help="score output/kiid_extracted.csv instead of the KIDs")
    score_cmd.add_argument("--comparison", action="store_true",
                           help="score output/comparison.csv against data/comparison_key.csv")
    args = parser.parse_args()

    if args.command == "compare":
        return compare.run_compare()
    if args.command == "score":
        if args.comparison and (args.unseen or args.factsheets or args.kiids):
            parser.error("--comparison can't be combined with the other score options")
        if args.comparison:
            return compare.run_score()
        if args.kiids and (args.unseen or args.factsheets):
            parser.error("--kiids can't be combined with --unseen or --factsheets (there are no unseen KIIDs)")
        if args.kiids:
            return score.run(extracted_path=score.EXTRACTED_KIIDS, results_path=score.KIID_RESULTS,
                             doc_type="kiid")
        if args.unseen and args.factsheets:
            return score.run(extracted_path=score.EXTRACTED_FACTSHEETS, key_path=score.UNSEEN_KEY,
                             results_path=score.UNSEEN_FACTSHEET_RESULTS, inputs=score.UNSEEN_INPUTS,
                             pdf_folder="pdfs/unseen/", doc_type="factsheet")
        if args.unseen:
            return score.run(key_path=score.UNSEEN_KEY, results_path=score.UNSEEN_RESULTS,
                             inputs=score.UNSEEN_INPUTS, pdf_folder="pdfs/unseen/")
        if args.factsheets:
            return score.run(extracted_path=score.EXTRACTED_FACTSHEETS, results_path=score.FACTSHEET_RESULTS,
                             doc_type="factsheet")
        return score.run()

    if args.command == "kid":
        return extract_all(args.paths, "kid", lambda pages, sha256: kid.extract(pages))
    if args.command == "kiid":
        return extract_all(args.paths, "kiid", lambda pages, sha256: kiid.extract(pages))

    import anthropic  # only the factsheet command needs it

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY; only used for answers that aren't cached
    return extract_all(args.paths, "factsheet",
                       lambda pages, sha256: factsheet.extract(pages, sha256, client, OUTPUT / "llm"))


def extract_all(paths: list[Path], doc_type: str, extract) -> int:
    """Run `extract(pages, sha256)` on each file, then write the JSON files, the CSV and a table per document."""
    files, failed = pdf_files(paths, doc_type)
    if not files:
        print(f"No {LABELS[doc_type]} files to read, so the CSV was left as it was.", file=sys.stderr)
        return 1

    rows, no_key = [], False
    for path in files:
        # fund_id and doc_type are the only things taken from the file name.
        name = re.fullmatch(rf"(F\d+)_({doc_type})\.pdf", path.name)
        if not name:
            print(f"Skipped {path}: name isn't like F16_{doc_type}.pdf", file=sys.stderr)
            failed += 1
            continue
        fund_id = name.group(1)
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        try:  # one bad PDF shouldn't stop the others
            pages = read_pages(path)
            fields, notes = extract(pages, sha256)
            if doc_type in WRAPPED_LABELS:
                labelwrap.extend_label(fields, notes, path, pages)
            if doc_type in GRAPHIC_RISK:
                riskscale.fill_from_graphic(fields, notes, path)
        except Exception as error:
            print(f"Couldn't extract {path}: {error}", file=sys.stderr)
            # The SDK raises a plain TypeError, not an API error, when it finds no key.
            no_key = no_key or "authentication method" in str(error)
            failed += 1
            continue

        output.write_json(OUTPUT / doc_type / f"{fund_id}_{doc_type}.json", fund_id, doc_type, sha256, fields, notes)
        rows.append(output.csv_row(fund_id, doc_type, fields, notes))
        output.print_table(f"{fund_id} ({path.name})", fields)

    csv_path = OUTPUT / f"{doc_type}_extracted.csv"
    if rows:
        output.write_csv(csv_path, rows)
        print(f"\n{len(rows)} {LABELS[doc_type]}(s) written. {csv_path} now holds only these.")
    else:
        print(f"\nNo {LABELS[doc_type]} could be read, so the CSV was left as it was.", file=sys.stderr)
    if failed:
        print(f"{failed} file(s) skipped or failed (see above).", file=sys.stderr)
    if no_key:
        print("No Anthropic API key found. Create one at https://platform.claude.com/ and run\n"
              "    export ANTHROPIC_API_KEY=...\n"
              "in this terminal first (factsheets already in output/llm/ don't need it).", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
