"""Step 4: write parsed technologies to CSV files in data/processed/.

The CSVs are rebuilt from scratch from the raw HTML on every run, so they are
always a pure function of data/raw/ (re-running never duplicates rows).

Files (every file has a ``tech_id`` column linking back to technologies.csv)
-----------------------------------------------------------------------------
technologies.csv          one row per technology
sections.csv              every free-text section, in page order
inventors.csv             inventor names per technology
keywords.csv              keywords per technology
categories.csv            (category, subcategory) pairs per technology
patents.csv               rows from each page's patent-status table
related_cases.csv         UC case numbers listed on each page
related_technologies.csv  links to other technologies shown on each page

Usage:
    python -m src.scraper.export
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.scraper import config
from src.scraper.fetch import html_path
from src.scraper.parse import MAIN_SECTION_COLUMNS, Technology, parse_file
from src.scraper.sitemap import SitemapEntry, load_entries

# Column layout of each output file.
COLUMNS: dict[str, list[str]] = {
    "technologies": [
        "tech_id", "url", "lastmod", "title", "uc_case", "campus", "campus_raw",
        "contact_name", "contact_email", "meta_description", *MAIN_SECTION_COLUMNS,
    ],
    "sections": ["tech_id", "position", "heading", "section_type", "text"],
    "inventors": ["tech_id", "position", "name"],
    "keywords": ["tech_id", "keyword"],
    "categories": ["tech_id", "category", "subcategory"],
    "patents": ["tech_id", "country", "patent_type", "number", "dated", "case_number"],
    "related_cases": ["tech_id", "uc_case"],
    "related_technologies": ["tech_id", "related_tech_id", "relation"],
}

PATENT_DATE_FORMAT = "%m/%d/%Y"  # as shown on the site, e.g. 06/23/2026


@dataclass
class ExportStats:
    """Summary of an export run."""

    in_sitemap: int = 0
    html_missing: int = 0
    parsed: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


def to_iso_date(value: str) -> str | None:
    """Convert MM/DD/YYYY to YYYY-MM-DD.

    Blank values become None; anything else that doesn't match is returned
    unchanged so no information is lost.
    """
    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), PATENT_DATE_FORMAT).date().isoformat()
    except ValueError:
        return value


def technology_rows(tech: Technology, entry: SitemapEntry) -> dict[str, list[list]]:
    """Flatten one Technology into rows for each output file.

    Args:
        tech: Parsed technology.
        entry: Its sitemap entry (supplies url and lastmod).

    Returns:
        Mapping of file name (see COLUMNS) to the rows for this technology.
    """
    tid = tech.tech_id
    return {
        "technologies": [[
            tid, entry.url, entry.lastmod, tech.title, tech.uc_case, tech.campus,
            tech.campus_raw, tech.contact_name, tech.contact_email, tech.meta_description,
            *(tech.section_text(col) for col in MAIN_SECTION_COLUMNS),
        ]],
        "sections": [[tid, s.position, s.heading, s.section_type, s.text] for s in tech.sections],
        "inventors": [[tid, i, name] for i, name in enumerate(tech.inventors)],
        "keywords": [[tid, kw] for kw in tech.keywords],
        "categories": [[tid, cat, sub] for cat, sub in tech.categories],
        "patents": [
            [tid, p.country, p.patent_type, p.number, to_iso_date(p.dated), p.case]
            for p in tech.patents
        ],
        "related_cases": [[tid, case] for case in tech.related_cases],
        "related_technologies": [[tid, rid, rel] for rid, rel in tech.related_technologies],
    }


def export_csv(
    entries: list[SitemapEntry],
    out_dir: Path = config.CSV_DIR,
    html_dir: Path = config.HTML_DIR,
) -> ExportStats:
    """Parse every downloaded page and (re)write the CSV files.

    Each file is written to a temporary name and swapped in at the end, so a
    failed run never leaves half-written CSVs behind.

    Args:
        entries: Sitemap entries (pages not yet downloaded are counted as
            missing and skipped).
        out_dir: Directory for the CSV files.
        html_dir: Directory of raw HTML pages.

    Returns:
        ExportStats describing what was written. Pages that fail to parse are
        listed in ``errors`` and skipped.
    """
    stats = ExportStats(in_sitemap=len(entries))
    rows: dict[str, list[list]] = {name: [] for name in COLUMNS}

    for entry in entries:
        path = html_path(entry.tech_id, html_dir)
        if not path.exists():
            stats.html_missing += 1
            continue
        try:
            tech = parse_file(path)
            if tech.tech_id != entry.tech_id:
                raise ValueError(f"page reports Tech ID {tech.tech_id}")
        except Exception as exc:  # record and keep going
            stats.errors.append((entry.tech_id, f"{type(exc).__name__}: {exc}"))
            continue
        for name, new_rows in technology_rows(tech, entry).items():
            rows[name].extend(new_rows)
        stats.parsed += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, columns in COLUMNS.items():
        final = out_dir / f"{name}.csv"
        tmp = final.with_suffix(".csv.tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows(rows[name])
        tmp.replace(final)
    return stats


def main() -> None:
    """Command-line entry point."""
    stats = export_csv(load_entries())
    print(
        f"Sitemap: {stats.in_sitemap} | parsed: {stats.parsed} | "
        f"not downloaded yet: {stats.html_missing} | parse errors: {len(stats.errors)}"
    )
    for tech_id, error in stats.errors:
        print(f"  {tech_id}: {error}")
    print(f"CSV files: {config.CSV_DIR}")


if __name__ == "__main__":
    main()
