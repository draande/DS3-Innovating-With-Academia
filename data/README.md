# Data

## UC Tech Transfer "Available Technologies"

Scraped from https://techtransfer.universityofcalifornia.edu/ by the
`src/scraper` pipeline (`python -m src.scraper.run`).

| Path | In git? | Contents |
| --- | --- | --- |
| `raw/sitemap.xml` | no | Snapshot of the site's sitemap (list of all technology pages) |
| `raw/html/<tech_id>.html` | no | Raw downloaded pages (~120 MB) — never edit by hand |
| `raw/fetch_log.csv` | no | One row per download attempt (status, size, time) |
| `processed/uc_techtransfer/*.csv` | **yes** | The scraped dataset |

### CSV files (`processed/uc_techtransfer/`)

Every file has a `tech_id` column linking back to `technologies.csv`.

| File | One row per |
| --- | --- |
| `technologies.csv` | technology: title, campus, UC case, contact, main text sections |
| `sections.csv` | free-text section, exactly as headed on the page |
| `inventors.csv` | inventor of a technology |
| `keywords.csv` | keyword of a technology |
| `categories.csv` | (category, subcategory) of a technology |
| `patents.csv` | patent / application listed for a technology |
| `related_cases.csv` | related UC case number |
| `related_technologies.csv` | link to another technology (`related` or `same_inventor`) |

Quick start:

```python
import pandas as pd

tech = pd.read_csv("data/processed/uc_techtransfer/technologies.csv")
inventors = pd.read_csv("data/processed/uc_techtransfer/inventors.csv")
tech.merge(inventors, on="tech_id")  # one row per (technology, inventor)
```

See `docs/AGENTS.md` ("Useful context") for known data gotchas.
