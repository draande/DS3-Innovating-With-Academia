import csv
from pathlib import Path

import pytest

from src.scraper.export import COLUMNS, export_csv, to_iso_date
from src.scraper.sitemap import SitemapEntry

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_IDS = [10027, 29501, 34791]


def _entries(ids):
    return [
        SitemapEntry(i, f"https://techtransfer.universityofcalifornia.edu/NCD/{i}.html", "2026-01-01")
        for i in ids
    ]


def _read(out_dir: Path, name: str) -> list[dict]:
    with (out_dir / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def exported(tmp_path):
    out_dir = tmp_path / "csv"
    # 99999 has no HTML file -> counted as missing, not an error.
    stats = export_csv(_entries(FIXTURE_IDS + [99999]), out_dir, FIXTURES)
    return out_dir, stats


def test_export_stats(exported) -> None:
    _, stats = exported
    assert stats.parsed == 3
    assert stats.html_missing == 1
    assert stats.errors == []


def test_all_files_written_with_headers(exported) -> None:
    out_dir, _ = exported
    for name, columns in COLUMNS.items():
        with (out_dir / f"{name}.csv").open(encoding="utf-8") as fh:
            assert next(csv.reader(fh)) == columns
    assert not list(out_dir.glob("*.tmp"))


def test_technologies_rows(exported) -> None:
    out_dir, _ = exported
    rows = _read(out_dir, "technologies")
    assert [(r["tech_id"], r["campus"], r["uc_case"], r["lastmod"]) for r in rows] == [
        ("10027", "UCLA", "1990-558-0", "2026-01-01"),
        ("29501", "UCLA", "2016-050-0", "2026-01-01"),
        ("34791", "UC Davis", "2018-471-0", "2026-01-01"),
    ]
    assert rows[0]["description"].startswith("Monoclonal antibodies")


def test_detail_files_link_by_tech_id(exported) -> None:
    out_dir, _ = exported
    inventors = [r["name"] for r in _read(out_dir, "inventors") if r["tech_id"] == "34791"]
    assert inventors == ["Shim, Heesung", "Singh, Latika", "Singh, Vikrant", "Wulff, Heike"]

    patents = [r for r in _read(out_dir, "patents") if r["tech_id"] == "34791"]
    assert ("12661340", "2026-06-23") in [(p["number"], p["dated"]) for p in patents]

    cats = [(r["category"], r["subcategory"]) for r in _read(out_dir, "categories") if r["tech_id"] == "10027"]
    assert ("Medical", "Therapeutics") in cats


def test_rerun_does_not_duplicate(tmp_path) -> None:
    out_dir = tmp_path / "csv"
    export_csv(_entries(FIXTURE_IDS), out_dir, FIXTURES)
    export_csv(_entries(FIXTURE_IDS), out_dir, FIXTURES)
    assert len(_read(out_dir, "technologies")) == 3


def test_mismatched_tech_id_is_recorded_as_error(tmp_path) -> None:
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "555.html").write_bytes((FIXTURES / "10027.html").read_bytes())
    stats = export_csv(_entries([555]), tmp_path / "csv", html_dir)
    assert stats.parsed == 0
    assert stats.errors and "10027" in stats.errors[0][1]


def test_to_iso_date() -> None:
    assert to_iso_date("06/23/2026") == "2026-06-23"
    assert to_iso_date("unknown") == "unknown"
    assert to_iso_date("") is None
    assert to_iso_date("   ") is None
