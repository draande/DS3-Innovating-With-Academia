"""Tests for src.scraper.parse using real pages saved in tests/fixtures/.

Fixtures (saved copies of live pages, Nov 2026):
- 10027.html: oldest layout, single "DESCRIPTION" section, no keywords.
- 34791.html: Abstract / Full Description layout with a patent table.
- 29501.html: modern UCLA layout (Summary, Background, Innovation, ...).
"""

from pathlib import Path

import pytest

from src.scraper.parse import (
    ParseError,
    clean_text,
    normalize_campus,
    parse_file,
    parse_technology,
    section_type_for,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def old_page():
    return parse_file(FIXTURES / "10027.html")


@pytest.fixture(scope="module")
def patent_page():
    return parse_file(FIXTURES / "34791.html")


@pytest.fixture(scope="module")
def modern_page():
    return parse_file(FIXTURES / "29501.html")


def test_old_layout_core_fields(old_page) -> None:
    assert old_page.tech_id == 10027
    assert old_page.title == "Vectors for the Recombinant Expression of Human Immunoglobulins"
    assert old_page.uc_case == "1990-558-0"
    assert old_page.campus == "UCLA"
    assert old_page.contact_email == "ncd@tdg.ucla.edu"
    assert old_page.inventors == ["Guardino, Alice E.", "Morrison, Sherie L.", "Wims, Letitia A."]
    assert old_page.keywords == []


def test_old_layout_description_and_categories(old_page) -> None:
    description = old_page.section_text("description")
    assert description.startswith("Monoclonal antibodies (mAbs) are an essential tool")
    assert "<" not in description  # no leftover HTML
    assert old_page.categories == [
        ("Biotechnology", "Genomics"),
        ("Biotechnology", "Health"),
        ("Biotechnology", "Other"),
        ("Medical", "Therapeutics"),
    ]
    assert (20472, "same_inventor") in old_page.related_technologies


def test_campus_is_normalized(patent_page) -> None:
    assert patent_page.campus_raw == "University of California, Davis"
    assert patent_page.campus == "UC Davis"


def test_patent_table_parsed(patent_page) -> None:
    assert len(patent_page.patents) == 3
    first = patent_page.patents[0]
    assert (first.country, first.patent_type, first.number, first.dated, first.case) == (
        "United States Of America",
        "Issued Patent",
        "12661340",
        "06/23/2026",
        "2018-471",
    )
    # The table itself must not leak into the patent-status text.
    assert "Country" not in (patent_page.section_text("patent_status") or "")


def test_heading_variants_map_to_canonical_types(patent_page, modern_page) -> None:
    assert [s.section_type for s in patent_page.sections] == [
        "summary", "description", "applications", "advantages", "patent_status",
    ]
    assert [s.heading for s in modern_page.sections][:3] == ["Summary", "Background", "Innovation"]
    assert modern_page.section_text("description") is not None  # "Innovation"


def test_keywords_split(modern_page) -> None:
    assert modern_page.keywords[:3] == ["Phase contrast MRI", "4D-flow", "temporal modulation"]


def test_related_technology_links_relative_and_absolute() -> None:
    html = """
    <html><head><meta name="Campus" content="UCSC"></head><body>
    <h1 class="tech-heading tech-heading-main">Thing</h1>
    <div class="ncd-data ref-data">Tech ID: 5 <span id="leadcase">/ UC Case 2020-1-0</span></div>
    <div class="ncd-mktg related-ncd"><ul><li><a href="34880.html?x=1">A</a></li></ul></div>
    <div class="ncd-mktg inventor-ncd"><ul>
      <li><a href="https://techtransfer.universityofcalifornia.edu/NCD/20472.html?y">B</a></li>
      <li><a href="5.html">self link ignored</a></li>
    </ul></div>
    </body></html>
    """
    tech = parse_technology(html)
    assert tech.related_technologies == [(34880, "related"), (20472, "same_inventor")]
    assert tech.campus == "UC Santa Cruz"
    assert tech.uc_case == "2020-1-0"


def test_non_technology_page_raises() -> None:
    with pytest.raises(ParseError):
        parse_technology("<html><body><h1>Not found</h1></body></html>")


def test_helpers() -> None:
    assert clean_text("  a  b \n\n\n c ") == "a b\n\nc"
    assert normalize_campus("Some New Lab") == "Some New Lab"
    assert section_type_for("BACKGROUND") == "background"
    assert section_type_for("Features/Benefits") == "advantages"
    assert section_type_for("Something Else") == "other"
    assert section_type_for("Brief Descripton") == "summary"  # site typo
    assert section_type_for("IP STATUS") == "intellectual_property"
