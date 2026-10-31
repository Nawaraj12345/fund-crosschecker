# Data

Two hand-made files. The PDFs themselves are not in the repo because they are copyrighted. Each one is listed in `sources.csv` with its link and hash, so it can be downloaded again and checked against the exact version used.

## sources.csv

One row per document.

| Column | What to write |
|---|---|
| `fund_id` | Short id you choose, the same for both documents of a fund, e.g. `F01` |
| `provider` | Fund group, e.g. `Vanguard` |
| `fund_name` | Your own label for the fund |
| `doc_type` | `factsheet`, `kiid`, `kid` or `cci` |
| `url` | Where it was downloaded from |
| `downloaded_on` | `YYYY-MM-DD` |
| `sha256` | Output of `shasum -a 256 pdfs/<file>` |
| `local_file` | File name inside `pdfs/`, e.g. `F01_factsheet.pdf` |
| `notes` | Anything odd |

## answer_key.csv

One row per document. Values are read from the PDF and checked against its text layer and risk graphics. The extractor is scored against this file.

| Column | What to write |
|---|---|
| `fund_id`, `doc_type` | Same as in `sources.csv` |
| `fund_name` | Exactly as printed in the document |
| `isin` | 12 characters: country code, 9 characters, check digit |
| `share_class` | As printed, e.g. `A Accumulation`. What counts depends on how many classes the fund or trust has. **More than one class:** the official class name in its fullest printed form, wherever the document prints it, e.g. `Income Shares` rather than the title's `Income`, because it's what tells the classes apart. **One class:** only if the document names it as its own class (title, key facts or product section); a mention elsewhere, such as "its Ordinary Shares are traded on ...", doesn't count, so it's `not_found` |
| `ongoing_charge_pct` | Number in percent, no `%` sign: `0.22` means 0.22%. For a KID, use the ongoing costs line for management and other operating costs, not the total cost or transaction costs. A percentage printed in that line's own description counts (e.g. "The OCF for the year ... was 1.52%"); a figure elsewhere in the KID does not. If the line shows only a £ amount, write `not_found` and put the amount in `notes`; don't work out a percentage from it. If that line prints N/A, write `not_found` and put any figure the KID gives elsewhere (such as an OCF quoted in the text) in `notes`. If the KID has no cost table at all, use the ongoing charge it states in its cost section. A management fee on its own is not an ongoing charge |
| `charge_label` | The label the document uses for that figure, e.g. `Ongoing charges`, `OCF`, `Other ongoing costs` |
| `transaction_cost_pct` | Portfolio transaction costs in percent, as printed. `not_found` if no percentage is printed (put a £ amount in `notes`) |
| `total_cost_pct` | Total yearly cost in percent, as printed, e.g. "Annual cost impact" or "Impact on return (RIY) per year". `not_found` if it prints N/A |
| `risk_score` | `1` to `7` |
| `risk_method` | The name of the risk indicator as printed: `SRRI`, `SRI`, or `other` for any other named scale. `not_found` if the document doesn't name it, even if the document type normally uses one. A KID that says "summary risk indicator" counts as `SRI` |
| `doc_date` | The main "as at" date at the top of the document, as `YYYY-MM-DD` (`YYYY-MM` if only the month is given). Other dates, such as a separate date for the charges, go in `notes` |
| `notes` | Anything odd |

Record only what the document prints. Don't fill a gap with what the rules say should be there.

An empty cell means not checked yet. `not_found` means checked, and the document doesn't show it.

## unseen/

The trusts for the unseen-trusts test: ten trusts that were never looked at while the rules were written. `unseen/sources.csv` and `unseen/answer_key.csv` have the same columns as the files above, and their PDFs go in `pdfs/unseen/`. They're kept apart so their score is never mixed with the development score. The answer key was written from the PDFs and committed before the tool was run on them, so the commit history shows it wasn't fitted to the tool's output.
