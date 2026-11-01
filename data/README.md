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
| `charge_label` | The label the document uses for that figure, e.g. `Ongoing charges`, `OCF`, `Other ongoing costs`. A bracket printed in the label's own cell is part of the label, even when it wraps onto the next line, e.g. `Ongoing charges (year end 31 Aug 2025)` (F04) or `Ongoing Charges (30 April 2026)` (F11); a footnote mark isn't. If `ongoing_charge_pct` is `not_found` (for example the line prints N/A), this is `not_found` too: there's no figure to label |
| `transaction_cost_pct` | Portfolio transaction costs in percent, as printed. `not_found` if no percentage is printed (put a £ amount in `notes`) |
| `total_cost_pct` | Total yearly cost in percent, as printed, e.g. "Annual cost impact" or "Impact on return (RIY) per year". `not_found` if it prints N/A |
| `risk_score` | `1` to `7` |
| `risk_method` | The name of the risk indicator as printed: `SRRI`, `SRI`, or `other` for any other named scale. `not_found` if the document doesn't name it, even if the document type normally uses one. A KID that says "summary risk indicator" counts as `SRI` |
| `doc_date` | The main "as at" date at the top of the document, as `YYYY-MM-DD` (`YYYY-MM` if only the month is given). Other dates, such as a separate date for the charges, go in `notes` |
| `notes` | Anything odd |

Record only what the document prints. Don't fill a gap with what the rules say should be there.

An empty cell means not checked yet. `not_found` means checked, and the document doesn't show it.

## unseen/

The trusts for the unseen-trusts test: ten trusts that were never looked at while the rules were written. `unseen/sources.csv` and `unseen/answer_key.csv` have the same columns as the files above, and their PDFs go in `pdfs/unseen/`. They're kept apart so their score is never mixed with the development score. The answer key was written from the PDFs and committed before the tool was run on them, so the commit history shows it wasn't fitted to the tool's output: the KID rows on 31 October and 1 November 2026, the factsheet rows on 1 November 2026, before the factsheet extractor read any of them.

## comparison_key.csv

The expected result of comparing each fund's factsheet with its KID or KIID (Story 3.1), for F01–F19: one row per fund and compared field (`ongoing_charge_pct`, `risk_score`). Written by hand from `answer_key.csv` and from the figures the KIDs give outside their cost rows (each checked in the PDF), and committed before the comparison code, so the comparison is scored against what the documents say rather than against its own output. F20–F29 get their rows once their factsheets have been read; since their values were looked at while the comparison rules were designed, any score on them is a development score.

| Column | What to write |
|---|---|
| `fund_id` | Same as in `answer_key.csv` |
| `field` | `ongoing_charge_pct` or `risk_score` |
| `verdict` | `match` (both print it and the numbers are equal, so 0.6 = 0.60), `mismatch` (both print it and the numbers differ, with no tolerance) or `cant_compare` (either side prints nothing, the two documents are for different share classes, or, for the risk score, they name different risk scales). The text `not_found` is never compared |
| `reasons` | Codes separated by `;`, in any order. Which side prints nothing: `factsheet_none`, `kid_none` (also for a KIID), `neither_none`. `different_share_class`: both print an ISIN and they differ. For the ongoing charge: `kid_table_zero` (a mismatch where the KID's figure is 0 and the factsheet's isn't), `kid_text_same` (the KID gives the factsheet's figure outside its cost row), `kid_text_other` (it gives other figures there, none equal to the factsheet's), `far_apart` (a mismatch where the documents' dates are 365 days or more apart), `no_reason` (a mismatch with none of these). For the risk score: `scale_not_stated` (a match where either document doesn't name its scale), `different_scales` (both name a scale and they differ). Empty for a plain match |
| `notes` | The values and anything worth knowing |
