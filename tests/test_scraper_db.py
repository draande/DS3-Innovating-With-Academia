import sqlite3
from pathlib import Path

import pytest

from src.scraper.db import build_database, export_csv, to_iso_date
from src.scraper.sitemap import SitemapEntry

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_IDS = [10027, 29501, 34791]


def _entries(ids):
    return [
        SitemapEntry(i, f"https://techtransfer.universityofcalifornia.edu/NCD/{i}.html", "2026-01-01")
        for i in ids
    ]


@pytest.fixture()
def built_db(tmp_path):
    db_path = tmp_path / "test.db"
    # 99999 has no HTML file -> counted as missing, not an error.
    stats = build_database(_entries(FIXTURE_IDS + [99999]), db_path, FIXTURES)
    return db_path, stats


def test_build_stats(built_db) -> None:
    _, stats = built_db
    assert stats.parsed == 3
    assert stats.html_missing == 1
    assert stats.errors == []


def test_technologies_rows(built_db) -> None:
    db_path, _ = built_db
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tech_id, campus, uc_case, lastmod FROM technologies ORDER BY tech_id"
        ).fetchall()
        assert rows == [
            (10027, "UCLA", "1990-558-0", "2026-01-01"),
            (29501, "UCLA", "2016-050-0", "2026-01-01"),
            (34791, "UC Davis", "2018-471-0", "2026-01-01"),
        ]
        description = conn.execute(
            "SELECT description FROM technologies WHERE tech_id = 10027"
        ).fetchone()[0]
        assert description.startswith("Monoclonal antibodies")


def test_child_tables_linked(built_db) -> None:
    db_path, _ = built_db
    with sqlite3.connect(db_path) as conn:
        inventors = [r[0] for r in conn.execute(
            """SELECT i.name FROM technology_inventors ti
               JOIN inventors i USING (inventor_id)
               WHERE ti.tech_id = 34791 ORDER BY ti.position"""
        )]
        assert inventors == ["Shim, Heesung", "Singh, Latika", "Singh, Vikrant", "Wulff, Heike"]

        patent = conn.execute(
            "SELECT number, dated FROM patents WHERE tech_id = 34791 ORDER BY dated DESC LIMIT 1"
        ).fetchone()
        assert patent == ("12661340", "2026-06-23")

        cats = conn.execute(
            """SELECT c.category, c.subcategory FROM technology_categories tc
               JOIN categories c USING (category_id) WHERE tc.tech_id = 10027"""
        ).fetchall()
        assert ("Medical", "Therapeutics") in cats

        # Shared categories are stored once and reused.
        n_health = conn.execute(
            "SELECT COUNT(*) FROM categories WHERE category='Biotechnology' AND subcategory='Health'"
        ).fetchone()[0]
        assert n_health == 1


def test_rebuild_does_not_duplicate(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    build_database(_entries(FIXTURE_IDS), db_path, FIXTURES)
    build_database(_entries(FIXTURE_IDS), db_path, FIXTURES)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM technologies").fetchone()[0] == 3


def test_mismatched_tech_id_is_recorded_as_error(tmp_path) -> None:
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "555.html").write_bytes((FIXTURES / "10027.html").read_bytes())
    stats = build_database(_entries([555]), tmp_path / "t.db", html_dir)
    assert stats.parsed == 0
    assert stats.errors and "10027" in stats.errors[0][1]


def test_export_csv(built_db, tmp_path) -> None:
    db_path, _ = built_db
    paths = export_csv(db_path, tmp_path / "csv")
    names = {p.name for p in paths}
    assert {"technologies.csv", "patents.csv", "inventors.csv"} <= names
    header = (tmp_path / "csv" / "technologies.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("tech_id,url,lastmod,title")


def test_to_iso_date() -> None:
    assert to_iso_date("06/23/2026") == "2026-06-23"
    assert to_iso_date("unknown") == "unknown"
