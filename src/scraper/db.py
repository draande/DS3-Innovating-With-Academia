"""Step 4: store parsed technologies in SQLite and export CSV copies.

The database is rebuilt from scratch from the raw HTML on every run, so it is
always a pure function of data/raw/ (re-running never duplicates rows).

Tables
------
technologies            one row per technology (tech_id primary key)
sections                every free-text section, in page order
inventors               unique inventor names
technology_inventors    technology <-> inventor links
categories              unique (category, subcategory) pairs
technology_categories   technology <-> category links
keywords                unique keywords (case-insensitive)
technology_keywords     technology <-> keyword links
related_cases           UC case numbers listed on each page
patents                 rows from each page's patent-status table
related_technologies    links to other technologies shown on each page
parse_errors            pages that could not be parsed
technology_full_text    (view) all sections of a technology joined in order

Usage:
    python -m src.scraper.db
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.scraper import config
from src.scraper.fetch import html_path
from src.scraper.parse import MAIN_SECTION_COLUMNS, Technology, parse_file
from src.scraper.sitemap import SitemapEntry, load_entries

SCHEMA = """
CREATE TABLE technologies (
    tech_id          INTEGER PRIMARY KEY,
    url              TEXT NOT NULL,
    lastmod          TEXT,              -- sitemap last-modified date (YYYY-MM-DD)
    title            TEXT NOT NULL,
    uc_case          TEXT,
    campus           TEXT,              -- normalized, e.g. 'UC San Diego'
    campus_raw       TEXT,              -- label exactly as on the page
    contact_name     TEXT,
    contact_email    TEXT,
    meta_description TEXT,
    background       TEXT,
    summary          TEXT,
    description      TEXT,
    applications     TEXT,
    advantages       TEXT
);
CREATE TABLE sections (
    tech_id      INTEGER NOT NULL REFERENCES technologies(tech_id),
    position     INTEGER NOT NULL,
    heading      TEXT NOT NULL,
    section_type TEXT NOT NULL,
    text         TEXT NOT NULL,
    PRIMARY KEY (tech_id, position)
);
CREATE TABLE inventors (
    inventor_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);
CREATE TABLE technology_inventors (
    tech_id     INTEGER NOT NULL REFERENCES technologies(tech_id),
    inventor_id INTEGER NOT NULL REFERENCES inventors(inventor_id),
    position    INTEGER NOT NULL,
    PRIMARY KEY (tech_id, inventor_id)
);
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    category    TEXT NOT NULL,
    subcategory TEXT                   -- NULL when only a top-level category is listed
);
CREATE TABLE technology_categories (
    tech_id     INTEGER NOT NULL REFERENCES technologies(tech_id),
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    PRIMARY KEY (tech_id, category_id)
);
CREATE TABLE keywords (
    keyword_id INTEGER PRIMARY KEY,
    keyword    TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE technology_keywords (
    tech_id    INTEGER NOT NULL REFERENCES technologies(tech_id),
    keyword_id INTEGER NOT NULL REFERENCES keywords(keyword_id),
    PRIMARY KEY (tech_id, keyword_id)
);
CREATE TABLE related_cases (
    tech_id INTEGER NOT NULL REFERENCES technologies(tech_id),
    uc_case TEXT NOT NULL,
    PRIMARY KEY (tech_id, uc_case)
);
CREATE TABLE patents (
    tech_id     INTEGER NOT NULL REFERENCES technologies(tech_id),
    country     TEXT,
    patent_type TEXT,
    number      TEXT,
    dated       TEXT,                  -- ISO date (YYYY-MM-DD) when parseable
    case_number TEXT
);
CREATE TABLE related_technologies (
    tech_id         INTEGER NOT NULL REFERENCES technologies(tech_id),
    related_tech_id INTEGER NOT NULL,  -- may point to a page no longer listed
    relation        TEXT NOT NULL,     -- 'related' or 'same_inventor'
    PRIMARY KEY (tech_id, related_tech_id, relation)
);
CREATE TABLE parse_errors (
    tech_id INTEGER PRIMARY KEY,
    error   TEXT NOT NULL
);
CREATE INDEX idx_technologies_campus ON technologies(campus);
CREATE INDEX idx_sections_type ON sections(section_type);
CREATE INDEX idx_patents_tech ON patents(tech_id);

-- All sections of a technology joined in page order (handy for search/NLP).
-- A view rather than a stored column so the text is not stored twice.
CREATE VIEW technology_full_text AS
SELECT tech_id, group_concat(heading || char(10) || text, char(10) || char(10)) AS full_text
FROM (SELECT * FROM sections ORDER BY tech_id, position)
GROUP BY tech_id;
"""

PATENT_DATE_FORMAT = "%m/%d/%Y"  # as shown on the site, e.g. 06/23/2026


@dataclass
class BuildStats:
    """Summary of a database build."""

    in_sitemap: int = 0
    html_missing: int = 0
    parsed: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


def to_iso_date(value: str) -> str:
    """Convert MM/DD/YYYY to YYYY-MM-DD; return the input unchanged if it doesn't match."""
    try:
        return datetime.strptime(value.strip(), PATENT_DATE_FORMAT).date().isoformat()
    except ValueError:
        return value


class _IdCache:
    """Assigns stable integer IDs to unique values (inventors, keywords, ...)."""

    def __init__(self, key=lambda v: v) -> None:
        self._ids: dict = {}
        self._key = key
        self.rows: list[tuple] = []

    def get(self, value) -> int:
        k = self._key(value)
        if k not in self._ids:
            self._ids[k] = len(self._ids) + 1
            row = value if isinstance(value, tuple) else (value,)
            self.rows.append((self._ids[k], *row))
        return self._ids[k]


def _insert_technology(
    cur: sqlite3.Cursor,
    tech: Technology,
    entry: SitemapEntry,
    inventors: _IdCache,
    categories: _IdCache,
    keywords: _IdCache,
) -> None:
    """Insert one technology and all of its child rows."""
    main_text = {col: tech.section_text(col) for col in MAIN_SECTION_COLUMNS}
    cur.execute(
        "INSERT INTO technologies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            tech.tech_id, entry.url, entry.lastmod, tech.title, tech.uc_case,
            tech.campus, tech.campus_raw, tech.contact_name, tech.contact_email,
            tech.meta_description, *(main_text[c] for c in MAIN_SECTION_COLUMNS),
        ),
    )
    cur.executemany(
        "INSERT INTO sections VALUES (?,?,?,?,?)",
        [(tech.tech_id, s.position, s.heading, s.section_type, s.text) for s in tech.sections],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO technology_inventors VALUES (?,?,?)",
        [(tech.tech_id, inventors.get(name), i) for i, name in enumerate(tech.inventors)],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO technology_categories VALUES (?,?)",
        [(tech.tech_id, categories.get(pair)) for pair in tech.categories],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO technology_keywords VALUES (?,?)",
        [(tech.tech_id, keywords.get(kw)) for kw in tech.keywords],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO related_cases VALUES (?,?)",
        [(tech.tech_id, case) for case in tech.related_cases],
    )
    cur.executemany(
        "INSERT INTO patents VALUES (?,?,?,?,?,?)",
        [
            (tech.tech_id, p.country, p.patent_type, p.number, to_iso_date(p.dated), p.case)
            for p in tech.patents
        ],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO related_technologies VALUES (?,?,?)",
        [(tech.tech_id, rid, rel) for rid, rel in tech.related_technologies],
    )


def build_database(
    entries: list[SitemapEntry],
    db_path: Path = config.DB_PATH,
    html_dir: Path = config.HTML_DIR,
) -> BuildStats:
    """Parse every downloaded page and (re)build the SQLite database.

    The database is written to a temporary file and swapped in at the end, so a
    failed build never leaves a half-written database behind.

    Args:
        entries: Sitemap entries (supply url/lastmod; pages not yet downloaded
            are counted as missing and skipped).
        db_path: Output SQLite file.
        html_dir: Directory of raw HTML pages.

    Returns:
        BuildStats describing what was stored.
    """
    stats = BuildStats(in_sitemap=len(entries))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(".db.tmp")
    tmp_path.unlink(missing_ok=True)

    inventors = _IdCache()
    categories = _IdCache()
    keywords = _IdCache(key=str.casefold)

    conn = sqlite3.connect(tmp_path)
    try:
        cur = conn.cursor()
        cur.executescript(SCHEMA)
        for entry in entries:
            path = html_path(entry.tech_id, html_dir)
            if not path.exists():
                stats.html_missing += 1
                continue
            try:
                tech = parse_file(path)
                if tech.tech_id != entry.tech_id:
                    raise ValueError(f"page reports Tech ID {tech.tech_id}")
            except Exception as exc:  # record and keep going; reviewed in validation
                stats.errors.append((entry.tech_id, f"{type(exc).__name__}: {exc}"))
                continue
            _insert_technology(cur, tech, entry, inventors, categories, keywords)
            stats.parsed += 1

        cur.executemany("INSERT INTO inventors VALUES (?,?)", inventors.rows)
        cur.executemany("INSERT INTO categories VALUES (?,?,?)", categories.rows)
        cur.executemany("INSERT INTO keywords VALUES (?,?)", keywords.rows)
        cur.executemany("INSERT INTO parse_errors VALUES (?,?)", stats.errors)
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    tmp_path.replace(db_path)
    return stats


def export_csv(db_path: Path = config.DB_PATH, out_dir: Path = config.CSV_DIR) -> list[Path]:
    """Export every table in the database to ``out_dir/<table>.csv``.

    Args:
        db_path: SQLite database to export.
        out_dir: Directory for the CSV files.

    Returns:
        Paths of the files written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with sqlite3.connect(db_path) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        for table in tables:
            cur = conn.execute(f'SELECT * FROM "{table}"')
            path = out_dir / f"{table}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow([d[0] for d in cur.description])
                writer.writerows(cur)
            written.append(path)
    return written


def main() -> None:
    """Command-line entry point: build the database, then export CSVs."""
    stats = build_database(load_entries())
    export_csv()
    print(
        f"Sitemap: {stats.in_sitemap} | parsed: {stats.parsed} | "
        f"not downloaded yet: {stats.html_missing} | parse errors: {len(stats.errors)}"
    )
    print(f"Database: {config.DB_PATH}")
    print(f"CSV exports: {config.CSV_DIR}")


if __name__ == "__main__":
    main()
