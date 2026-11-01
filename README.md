# Fund CrossChecker

**Does a fund's factsheet give the same figures as its own KID?**

Fund CrossChecker checks whether a UK investment trust's **factsheet** and its **Key Information Document (KID)** give the same figures, starting with the ongoing charge and the risk score. It reads both documents, compares them, and for each figure says match, mismatch or can't compare. Where they differ, it shows both numbers, the page and words each one came from, and the likely reason, such as a KID whose cost table shows 0%, or a KID more than a year older than the factsheet. Ordinary funds' factsheets and KIIDs are checked the same way, as controls.

It's for a fund selector at a wealth manager: someone who passes a trust's cost on to clients and needs to know which figure to trust.

## Why it's needed

- A trust's factsheet and its KID both come from the same manager, so you'd expect them to agree. They don't always.
- Since November 2024, UK investment trusts don't have to publish a KID at all, and those that still do can show costs however they like. Some print a full cost table, some print N/A or 0.00% on every cost line, some state the charge only in the text, and one KID is nearly nine years old. A new format, the CCI product summary, is due by 8 June 2027, so the formats will keep changing until then.
- A first check (Sprint 1) of 19 funds found cost differences in **5 of 14 trusts**, and in **none of the 5 ordinary (open-ended) funds** used as controls. The clearest example is Henderson Far East Income: 1.12% on the factsheet and 1.52% in the KID, both for the year to 31 August 2025.

## What it does today

The project is in Sprint 2, with Sprint 3's work started early. It reads trust KIDs and ordinary funds' KIIDs with rules and factsheets with Claude, then compares each fund's factsheet with its KID or KIID.

**Trust KIDs:**

- **Extracts 10 fields** from each KID: fund name, ISIN, share class, ongoing charge and its label, transaction cost, total cost, risk score, risk method and document date. Each value it finds comes with the page and the exact text it was read from.
- **Checks every value before saving it.** It checks the format (ISIN check digit, percentages from 0 to 5, risk score 1 to 7, a real date, no empty text) and that the quoted text really is on that page and contains the value. A number has to stand on its own in its quote: "1" doesn't count inside "1.5%", "£1,000", "-1%" or a footnote mark such as "SRRI1", and a date doesn't count inside a longer one (8 June isn't in "18 June"). A value that fails either check becomes `not_found`, with the reason in the notes, so the tool never reports a number it can't point to in the document. One exception, made on purpose: a risk score that a document shows only by highlighting it on the 1–7 scale graphic (a box or digit in another colour) is read from the PDF's drawing data, after the checks and only when the text gives no score. It comes with a description of the highlighted box instead of a text quote, and nothing an extractor or Claude answers can take that route. Before it was added it was tried on 48 documents whose score is known: it gave a score for 21, all right, and never gave one where there's no risk scale.
- **Reads cost tables**, including the awkward layouts: rows where the description column is mixed in, labels split over the lines of their cell, a space before the % sign, tables printed without their "Composition of costs" heading, figures given as N/A or only as a £ amount. When the KID states a charge somewhere else, such as in its text, the notes record it with its page.
- **Scores itself** against an answer key built from the PDFs (see [The data](#the-data)). **The honest figure: on 10 trusts it had never seen** (its first run on them, on 1 November 2026, after their answer key was committed and with no rule changes) it scored **71 of 100 correct, 1 wrong, 28 missed, 0 made up**. Even that flatters it: 25 of the 71 are values the KID doesn't print, rightly reported as `not_found`, so of the 75 values these KIDs do print it found 46 (61%), against 96 of 110 (87%) on the 14 KIDs the rules were written from. The 28 missed were mostly wordings the rules hadn't met (9 dates, 5 names, 4 share classes, 7 cost figures with 2 of their labels) and 1 risk score; the wrong one was a name read with its label ("Name Seraphim Space Investment Trust plc"). The rules were then extended to those wordings, so all 24 trust KIDs now count as development documents: **140 of 140** on the first 14 and **98 of 100** on the other 10 (with the risk score one KID shows only on its scale graphic now read from the drawing), 0 wrong, 0 made up. The 2 left are the name and share class of a KID whose two text columns run together. Those are development scores, not evidence about new trusts; that would need a fresh unseen set.

**Ordinary funds' KIIDs (the controls):** the 5 open-ended funds' KIIDs follow one standard layout, so they're read with rules too (`fundcrosschecker/kiid.py`), sharing the ISIN rule, the date pattern and every check with the trust KIDs. A KIID has no transaction or total cost, so those two are always `not_found`. Its risk score is read from the text, whether it's written as a digit ("rated 4"), as a word ("rated five") or only as the larger number the text layer lifts out of the 1–7 scale. Score: **50 of 50 correct, 0 made up**. That's a development score: the rules were written from these five and there are no unseen KIIDs, so it shows the rules fit these documents, not that they'd work on others.

**Factsheets:** factsheets come in a different layout from every provider, so instead of rules each factsheet's text goes to Claude (`claude-opus-5-5`), which answers each of the same 10 fields with the value, the page and the exact words it read it from. Every answer then goes through the same format checks and quote check as the KIDs, so Claude can miss a figure but can't put one in the output that the PDF doesn't show. Answers are cached by the PDF's hash, the model and the prompt, so re-running costs nothing and gives the same answers. On the 19 development factsheets (16 providers) the latest prompt, with the scale graphic reader, scores **187 of 190 values correct, 1 wrong, 0 made up** (the first prompt scored 167, with 7 wrong). The checks used to remove 11 answers for reasons that don't matter in factsheet text (footnote numbers stuck to labels, labels in brackets, dates such as 30-Sep-2026 or with the spaces lost, a figure split as "1 .03%"). Now they allow for those, which brought back 9 correct values. Of the other two, one is still rightly removed (its quote doesn't hold the whole label), and one now counts as wrong: Claude's label for one factsheet leaves out the "(fixed)" it prints. Three factsheets show their risk score only as a highlighted box or digit on the scale; those are now read from the drawing (184 of 190 before). A fourth draws its scale as a picture, with no drawing data to read, so it stays `not_found`. An earlier prompt also showed the checks at work: they stopped a share class Claude gave for a factsheet that doesn't name one, with a quote that didn't contain it.

**The comparison:** for each fund, the ongoing charge and the risk score get one of three verdicts, match, mismatch or can't compare, with the reasons the documents give: the KID's cost table shows 0%, the KID's own text gives another figure (or the factsheet's), the documents are a year or more apart, they're for different share classes, or one side prints nothing. These are labelled possible reasons, since they're inferences. Every value comes with its page and quote, and numbers are compared as numbers (0.6 equals 0.60) with no tolerance. On the 19 funds with both documents read (F01–F19) the ongoing charge gives **7 match, 5 mismatch, 7 can't compare**, and **0 false alarms on the 5 ordinary funds**. Against a comparison key written by hand before the comparison code, **all 38 verdicts are right, with 0 false alarms and 0 missed mismatches** (35 before the scale graphic reader: three factsheets show their risk score only as a highlighted box). Run on the answer key's own values, the comparison logic gives all 38. Two examples: Henderson Far East Income prints 1.12% on its factsheet and 1.52% in its KID for the same year, with no reason in either document; and in 4 trusts (F10, F11, F14, F19) the KID's cost table says N/A while its own text gives exactly the factsheet's figure, which the tool points out.

Not built yet: the comparison for the 10 newer trusts (F20–F29), which needs their factsheets read first, and a web page.

## How it works

```
KID (PDF)  ->  text, page by page (pdfplumber)
           ->  rules for each field (fundcrosschecker/kid.py)
           ->  format checks and quote check (fundcrosschecker/checks.py)
           ->  output/kid/<fund>_kid.json   (each value with its page and quote)
               output/kid_extracted.csv      (same columns as the answer key)
           ->  a risk score shown only on the scale graphic, from the drawing (fundcrosschecker/riskscale.py)
           ->  scorer (fundcrosschecker/score.py)  ->  results/kid_scores.csv

KIID (PDF)  ->  the same steps with the KIID rules (fundcrosschecker/kiid.py)
            ->  output/kiid/, output/kiid_extracted.csv  ->  results/kiid_scores.csv

Each fund's factsheet and KID or KIID output  ->  comparison (fundcrosschecker/compare.py)
            ->  output/comparison.csv  ->  scored against data/comparison_key.csv  ->  results/comparison_scores.csv

Factsheet (PDF)  ->  text, page by page (pdfplumber)
                 ->  Claude answers each field with value, page and quote (fundcrosschecker/factsheet.py),
                     cached in output/llm/
                 ->  the same format checks and quote check (fundcrosschecker/checks.py)
                 ->  a risk score shown only on the scale graphic, from the drawing (riskscale.py)
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
.venv/bin/python -m fundcrosschecker kiid pdfs/         # every *_kiid.pdf (the ordinary funds)
.venv/bin/python -m fundcrosschecker score --kiids      # compare with the KIID rows
.venv/bin/python -m fundcrosschecker compare            # each factsheet against its KID or KIID
.venv/bin/python -m fundcrosschecker score --comparison # the verdicts against the comparison key
.venv/bin/python -m fundcrosschecker factsheet pdfs/    # every *_factsheet.pdf, read by Claude
.venv/bin/python -m fundcrosschecker score --factsheets # compare with the factsheet rows
.venv/bin/python -m fundcrosschecker factsheet pdfs/unseen/          # the unseen trusts' factsheets
.venv/bin/python -m fundcrosschecker score --unseen --factsheets     # scored apart, in their own file
.venv/bin/python -m pytest                              # run the tests
.venv/bin/python -m pytest -m slow                      # the slow check: the scale graphic reader on all 48 PDFs
```

The tests don't need the PDFs or an API key: the tests that read real PDFs skip themselves when the PDFs aren't there, and the factsheet tests use a stand-in for Claude.

The `factsheet` command needs your own Anthropic API key (create one at https://platform.claude.com/, then run `export ANTHROPIC_API_KEY=...` in the terminal you run it from). A full run of all 19 factsheets costs about $0.90 (measured twice on 31 October 2026; each request prints its tokens and cost); after that the cached answers are used, at no cost.

## The data

- `data/sources.csv`: the 38 documents (a factsheet and a KID or KIID for each of 19 funds, F01–F19), each with its link, download date and SHA-256.
- `data/answer_key.csv`: what each document actually says, one row per document. It's the ground truth the extractor is scored against.
- `data/unseen/`: the same two files for the unseen-trusts test (F20 onwards), trusts that were never looked at while the rules were written. Their answer key was committed before the tool was run on them.
- `data/comparison_key.csv`: the expected verdict for each fund's ongoing charge and risk score (F01–F19), written by hand before the comparison code.
- `data/README.md`: the rules for every answer key column. The main rule is **record only what's printed**. `not_found` means checked and not shown; an empty cell means not checked yet.

Every answer key value was checked against its PDF's text by script, and every risk score against the document's wording or its risk graphic on the rendered page. On 1 November 2026, 20 values from the F01–F19 key, picked at random (seed 20261031), were checked by hand against the PDFs: all 20 were right. The rest of the key, and the unseen trusts' key, haven't been checked by hand.

## Project layout

```
fundcrosschecker/  the code: __main__.py (the commands), pdftext.py, kid.py, kiid.py, factsheet.py, checks.py, riskscale.py, score.py, compare.py, output.py, common.py
tests/             unit tests; the extractors' and checks' tests use real wording from the KIDs and KIIDs
spikes/            the PDF library comparison
data/              sources, answer key and their rules
results/           score history (counts only), committed; the unseen trusts' in their own file
output/            extractor output and Claude's cached answers, hold text from the PDFs, never committed
pdfs/              the downloaded PDFs, never committed
```

## What's next

| When | What |
|---|---|
| Sprint 2 (to 29 Nov 2026) | Done: the test on 10 trusts the tool hadn't seen (71 of 100), then the checks' known gaps, checks that allow for factsheet text, and the KID wordings that test showed up. Next: the unseen trusts' factsheets (their answer key is committed; the one run is still to do) |
| Sprint 3 (30 Nov – 13 Dec 2026) | Done early: the ordinary funds' KIIDs (the controls, 50 of 50) and the comparison on F01–F19 (38 of 38 verdicts, 0 false alarms). Next: the comparison for F20–F29 once their factsheets are read (a development score, since their values were looked at while designing it), and making the repo public |
| Later | CCI product summaries (expected from early 2027), a whole buy list at once, and a simple web page |
