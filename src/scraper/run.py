"""Run the full UC Tech Transfer scraping pipeline.

Steps:
  1. sitemap   download sitemap.xml and list every technology page
  2. fetch     download each page to data/raw/html/ (resumable; skips existing)
  3. parse +   parse every downloaded page and write
  4. export    CSV files to data/processed/

Usage (from the repo root):
    python -m src.scraper.run                 # everything (~1-3 h the first time)
    python -m src.scraper.run --limit 50      # trial run on 50 pages
    python -m src.scraper.run --parse-only    # skip downloading; rebuild CSVs from data/raw/
    python -m src.scraper.run --refresh-sitemap
"""

from __future__ import annotations

import argparse

from src.scraper import config, export, fetch
from src.scraper.sitemap import download_sitemap, load_entries


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Scrape the UC Tech Transfer site into CSV files.")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="only download N pages (spread across the ID range); useful for a trial run",
    )
    parser.add_argument(
        "--parse-only", action="store_true",
        help="skip downloading; rebuild the CSVs from pages already in data/raw/html/",
    )
    parser.add_argument(
        "--refresh-sitemap", action="store_true",
        help="re-download sitemap.xml instead of reusing the saved copy",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the pipeline end to end."""
    args = parse_args(argv)

    print("[1/4] Sitemap")
    download_sitemap(overwrite=args.refresh_sitemap)
    entries = load_entries()
    print(f"      {len(entries)} technologies listed")

    if args.parse_only:
        print("[2/4] Download skipped (--parse-only)")
    else:
        targets = fetch.select_entries(entries, args.limit)
        print(f"[2/4] Downloading {len(targets)} pages (existing files are skipped)")
        results = fetch.fetch_all(targets)
        failed = [r for r in results if r.status not in ("200", "skipped")]
        print(f"      done; {len(failed)} failed (see {config.FETCH_LOG_PATH})")

    print("[3-4/4] Parsing and writing CSVs")
    stats = export.export_csv(entries)
    print(
        f"      parsed {stats.parsed}, not downloaded {stats.html_missing}, "
        f"parse errors {len(stats.errors)} -> {config.CSV_DIR}"
    )
    for tech_id, error in stats.errors:
        print(f"      parse error {tech_id}: {error}")


if __name__ == "__main__":
    main()
