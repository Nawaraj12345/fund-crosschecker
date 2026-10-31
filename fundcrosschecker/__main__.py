"""Command line: extract the figures from trust KIDs, and score them.

    .venv/bin/python -m fundcrosschecker kid pdfs/F16_kid.pdf
    .venv/bin/python -m fundcrosschecker kid pdfs/          (every *_kid.pdf in the folder)
    .venv/bin/python -m fundcrosschecker score              (compare with the answer key)
    .venv/bin/python -m fundcrosschecker kid pdfs/unseen/
    .venv/bin/python -m fundcrosschecker score --unseen     (the unseen trusts, scored separately)

Run these from the project folder, which is where Python finds the package.
`kid` writes output/kid/<fund_id>_kid.json and output/kid_extracted.csv in the
project's output/ folder. The CSV holds only the KIDs
from the latest run (a run that reads none leaves it as it was); JSON files
from earlier runs are left as they are. `score` is described in score.py.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

from . import kid, output, score
from .pdftext import read_pages

OUTPUT = Path(__file__).resolve().parent.parent / "output"


def kid_files(paths: list[Path]) -> tuple[list[Path], int]:
    """The KID files to read, and how many of the given paths don't exist."""
    files, missing = [], 0
    for path in paths:
        if not path.exists():
            print(f"Couldn't find {path}", file=sys.stderr)
            missing += 1
        elif path.is_dir():
            files.extend(sorted(path.glob("*_kid.pdf")))
        else:
            files.append(path)
    return files, missing


def main() -> int:
    parser = argparse.ArgumentParser(prog="fundcrosschecker")
    sub = parser.add_subparsers(dest="command", required=True)
    kid_cmd = sub.add_parser("kid", help="extract figures from trust KIDs")
    kid_cmd.add_argument("paths", nargs="+", type=Path, help="KID PDFs, or folders of them")
    score_cmd = sub.add_parser("score", help="compare output/kid_extracted.csv with the answer key")
    score_cmd.add_argument("--unseen", action="store_true",
                           help="use the unseen trusts' answer key (data/unseen/) and score history")
    args = parser.parse_args()

    if args.command == "score":
        if args.unseen:
            return score.run(key_path=score.UNSEEN_KEY, results_path=score.UNSEEN_RESULTS,
                             inputs=score.UNSEEN_INPUTS, pdf_folder="pdfs/unseen/")
        return score.run()

    files, failed = kid_files(args.paths)
    if not files:
        print("No KID files to read, so the CSV was left as it was.", file=sys.stderr)
        return 1

    rows = []
    for path in files:
        # fund_id and doc_type are the only things taken from the file name.
        name = re.fullmatch(r"(F\d+)_(kid)\.pdf", path.name)
        if not name:
            print(f"Skipped {path}: name isn't like F16_kid.pdf", file=sys.stderr)
            failed += 1
            continue
        fund_id, doc_type = name.groups()
        try:  # one bad PDF shouldn't stop the others
            pages = read_pages(path)
            fields, notes = kid.extract(pages)
        except Exception as error:
            print(f"Couldn't extract {path}: {error}", file=sys.stderr)
            failed += 1
            continue

        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        output.write_json(OUTPUT / "kid" / f"{fund_id}_{doc_type}.json", fund_id, doc_type, sha256, fields, notes)
        rows.append(output.csv_row(fund_id, doc_type, fields, notes))
        output.print_table(f"{fund_id} ({path.name})", fields)

    csv_path = OUTPUT / "kid_extracted.csv"
    if rows:
        output.write_csv(csv_path, rows)
        print(f"\n{len(rows)} KID(s) written. {csv_path} now holds only these.")
    else:
        print("\nNo KID could be read, so the CSV was left as it was.", file=sys.stderr)
    if failed:
        print(f"{failed} file(s) skipped or failed (see above).", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
