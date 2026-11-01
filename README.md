# Fund CrossChecker

Fund CrossChecker is being built to check whether a UK investment trust's **factsheet** and its **Key Information Document (KID)** give the same figures, starting with costs. Where they differ, it will show both numbers, where each one came from, and why they might differ.

It's for a fund selector at a wealth manager: someone who passes a trust's cost on to clients and needs to know which figure to trust.

## Why it's needed

- A trust's factsheet and its KID both come from the same manager, so you'd expect them to agree. They don't always.
- Since November 2024, UK investment trusts don't have to publish a KID at all, and those that still do can show costs however they like. Some print a full cost table, some print N/A or 0.00% on every cost line, some state the charge only in the text, and one KID is nearly nine years old. A new format, the CCI product summary, is due by 8 June 2027, so the formats will keep changing until then.
- A first check (Sprint 1) of 19 funds found cost differences in **5 of 14 trusts**, and in **none of the 5 ordinary (open-ended) funds** used as controls. The clearest example is Henderson Far East Income: 1.12% on the factsheet and 1.52% in the KID, both for the year to 31 August 2025.

## What it does today

The project is in Sprint 2. It reads trust KIDs with rules, and factsheets with Claude.

**Trust KIDs:**

- **Extracts 10 fields** from each KID: fund name, ISIN, share class, ongoing charge and its label, transaction cost, total cost, risk score, risk method and document date. Each value it finds comes with the page and the exact text it was read from.
- **Checks every value before saving it.** It checks the format (ISIN check digit, percentages from 0 to 5, risk score 1 to 7, a real date) and that the quoted text really is on that page and contains the value. A value that fails either check becomes `not_found`, with the reason in the notes, so the tool never reports a number it can't point to in the document. One known gap: the number check still accepts a number that is part of a bigger one ("1" inside "1.5%" or "£1,000"), and an empty name. The rules were kept unchanged until the test on unseen trusts; that test is now done, so this fix comes next. Until then the tests record these cases as expected failures.
- **Reads cost tables**, including the awkward layouts: rows where the description column is mixed in, labels split over two lines, figures given as N/A or only as a £ amount. When the KID states a charge somewhere else, such as in its text, the notes record it with its page.
- **Scores itself** against an answer key built from the PDFs (see [The data](#the-data)). On the 14 trust KIDs the rules were written from: **126 of 140 values correct, 0 wrong, 0 made up**. The other 14 are `not_found` so far: 9 dates written in other ways, and the names (plus two share classes) of the 3 KIDs without a "Product" heading. That's a development score. **On 10 trusts it had never seen** (its first run on them, on 1 November 2026, after their answer key was committed and with no rule changes) it scored **71 of 100 correct, 1 wrong, 28 missed, 0 made up**, which is the more honest figure. Even that flatters it: 25 of the 71 are values the KID doesn't print, rightly reported as `not_found`, so of the 75 values these KIDs do print it found 46 (61%), against 96 of 110 (87%) on the development KIDs. The 28 missed are 9 dates, 5 names, 4 share classes, 7 cost figures with 2 of their labels, and 1 risk score; the wrong one is a name read with its label ("Name Seraphim Space Investment Trust plc"). Once the rules are changed to fix these, the 10 trusts count as development documents too, so 71 of 100 stays the unseen figure.

**Factsheets:** factsheets come in a different layout from every provider, so instead of rules each factsheet's text goes to Claude (`claude-opus-5-5`), which answers each of the same 10 fields with the value, the page and the exact words it read it from. Every answer then goes through the same format checks and quote check as the KIDs, so Claude can miss a figure but can't put one in the output that the PDF doesn't show. Answers are cached by the PDF's hash, the model and the prompt, so re-running costs nothing and gives the same answers. On the 19 development factsheets (16 providers) the latest prompt scores **175 of 190 values correct, 0 wrong, 0 made up** (the first prompt scored 167, with 7 wrong). All 15 `not_found` have known causes: 11 are the checks being stricter than factsheet text needs (footnote numbers stuck to labels, labels in brackets, dates such as 30-Sep-2026, a figure split as "1 .03%") and 4 are risk scores shown only as a shaded box. An earlier prompt also showed the checks at work: they stopped a share class Claude gave for a factsheet that doesn't name one, with a quote that didn't contain it.

Not built yet: the factsheet-versus-KID comparison itself, and a web page.

## How it works

```
KID (PDF)  ->  text, page by page (pdfplumber)
           ->  rules for each field (fundcrosschecker/kid.py)
           ->  format checks and quote check (fundcrosschecker/checks.py)
           ->  output/kid/<fund>_kid.json   (each value with its page and quote)
               output/kid_extracted.csv      (same columns as the answer key)
           ->  scorer (fundcrosschecker/score.py)  ->  results/kid_scores.csv

Factsheet (PDF)  ->  text, page by page (pdfplumber)
                 ->  Claude answers each field with value, page and quote (fundcrosschecker/factsheet.py),
                     cached in output/llm/
                 ->  the same format checks and quote check (fundcrosschecker/checks.py)
                 ->  output/factsheet/ and output/factsheet_extracted.csv
                 ->  scorer  ->  results/factsheet_scores.csv
```

pdfplumber was chosen over PyMuPDF after a comparison on the trust KIDs (`spikes/compare_pdf_libs.py`). It read the cost tables as separate cells and kept F09's risk sentence in its place on the page, where PyMuPDF did neither, and it has an MIT licence. One limit: on two-column pages it merges the columns line by line, so a sentence that wraps inside one column comes out in pieces.

## Running it

You need Python 3.10 or later (built on 3.12.6).

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

The PDFs aren't in the repo because they're copyrighted. Download each one from its link in `data/sources.csv`, save it in `pdfs/` under the name in the `local_file` column, and check it with `shasum -a 256 pdfs/<file>` against the `sha256` column. If the hash differs, it's a different version of the document (usually a newer one), and the answer key may not match it. Some sites only work in a browser.

Run these from the project folder:

```
.venv/bin/python -m fundcrosschecker kid pdfs/          # extract every *_kid.pdf
.venv/bin/python -m fundcrosschecker score              # compare with the answer key
.venv/bin/python -m fundcrosschecker kid pdfs/unseen/   # the unseen trusts
.venv/bin/python -m fundcrosschecker score --unseen     # scored apart from the development score
.venv/bin/python -m fundcrosschecker factsheet pdfs/    # every *_factsheet.pdf, read by Claude
.venv/bin/python -m fundcrosschecker score --factsheets # compare with the factsheet rows
.venv/bin/python -m pytest                              # run the tests
```

The tests don't need the PDFs or an API key: the one test that reads a real KID skips itself when `pdfs/` isn't there, and the factsheet tests use a stand-in for Claude.

The `factsheet` command needs your own Anthropic API key (create one at https://platform.claude.com/, then run `export ANTHROPIC_API_KEY=...` in the terminal you run it from, or add that line to `~/.zshrc` so every new terminal has it). A full run of all 19 factsheets costs about $0.90 (measured twice on 31 October 2026; each request prints its tokens and cost); after that the cached answers are used, at no cost.

## The data

- `data/sources.csv`: the 38 documents (a factsheet and a KID or KIID for each of 19 funds, F01–F19), each with its link, download date and SHA-256.
- `data/answer_key.csv`: what each document actually says, one row per document. It's the ground truth the extractor is scored against.
- `data/unseen/`: the same two files for the unseen-trusts test (F20 onwards), trusts that were never looked at while the rules were written. Their answer key was committed before the tool was run on them.
- `data/README.md`: the rules for every answer key column. The main rule is **record only what's printed**. `not_found` means checked and not shown; an empty cell means not checked yet.

Every answer key value was checked against its PDF's text by script, and every risk score against the document's wording or its risk graphic on the rendered page. It hasn't been checked line by line by hand.

## Project layout

```
fundcrosschecker/  the code: __main__.py (the commands), pdftext.py, kid.py, factsheet.py, checks.py, score.py, output.py, common.py
tests/             unit tests; the extractor's and checks' tests use real wording from the KIDs
spikes/            the PDF library comparison
data/              sources, answer key and their rules
results/           score history (counts only), committed; the unseen trusts' in their own file
output/            extractor output and Claude's cached answers, hold text from the PDFs, never committed
pdfs/              the downloaded PDFs, never committed
```

## What's next

| When | What |
|---|---|
| Sprint 2 (to 29 Nov 2026) | Done: the test on 10 trusts the tool hadn't seen (71 of 100). Next: fix the known gaps in the checks and let them allow for factsheet text; then what the KIDs missed (dates and names written in other ways, share classes, costs); then the unseen trusts' factsheets (answer key first, then one run) |
| Sprint 3 (30 Nov – 13 Dec 2026) | The ordinary funds' KIIDs (the controls), then the comparison: match, mismatch, or can't compare, with the likely reason |
| Later | CCI product summaries (expected from early 2027), a whole buy list at once, and a simple web page |
