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

One row per document, filled in by hand from the PDF. The extractor is scored against this file.

| Column | What to write |
|---|---|
| `fund_id`, `doc_type` | Same as in `sources.csv` |
| `fund_name` | Exactly as printed in the document |
| `isin` | 12 characters: country code, 9 characters, check digit |
| `share_class` | As printed, e.g. `A Accumulation` |
| `ongoing_charge_pct` | Number in percent, no `%` sign: `0.22` means 0.22% |
| `charge_label` | The label the document uses, e.g. `Ongoing charges`, `OCF`, `Total costs` |
| `risk_score` | `1` to `7` |
| `risk_method` | `SRRI` (UCITS KIID), `SRI` (PRIIPs KID) or `other` |
| `doc_date` | `YYYY-MM-DD`, or `YYYY-MM` if only the month is given |
| `notes` | Anything odd |

An empty cell means not checked yet. `not_found` means checked, and the document doesn't show it.
