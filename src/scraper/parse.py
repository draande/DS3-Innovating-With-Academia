"""Step 3: turn a raw technology page (HTML) into a structured record.

Every page shares the same skeleton (title, Tech ID, contact, inventors,
categories, keywords...), but the free-text sections vary by campus and era:
e.g. "Background" vs "BACKGROUND", or "Technology Description" vs
"Full Description" vs "DESCRIPTION". We keep every section verbatim in
``Technology.sections`` and also map common headings onto a small set of
canonical section types (see ``SECTION_TYPES``) so they can be queried
consistently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Tag

# --- Campus names ----------------------------------------------------------
# Pages label the campus inconsistently ("UCLA", "University of California,
# Davis", ...). Map every known variant onto one canonical name.
CAMPUS_ALIASES = {
    "University of California, Berkeley": "UC Berkeley",
    "UC Berkeley": "UC Berkeley",
    "UCB": "UC Berkeley",
    "University of California, Davis": "UC Davis",
    "UC Davis": "UC Davis",
    "UCD": "UC Davis",
    "University of California, Irvine": "UC Irvine",
    "UC Irvine": "UC Irvine",
    "UCI": "UC Irvine",
    "University of California, Los Angeles": "UCLA",
    "UCLA": "UCLA",
    "University of California, Merced": "UC Merced",
    "UC Merced": "UC Merced",
    "UCM": "UC Merced",
    "University of California, Riverside": "UC Riverside",
    "UC Riverside": "UC Riverside",
    "UCR": "UC Riverside",
    "University of California, San Diego": "UC San Diego",
    "UC San Diego": "UC San Diego",
    "UCSD": "UC San Diego",
    "University of California, San Francisco": "UCSF",
    "UCSF": "UCSF",
    "University of California, Santa Barbara": "UC Santa Barbara",
    "UC Santa Barbara": "UC Santa Barbara",
    "UCSB": "UC Santa Barbara",
    "University of California, Santa Cruz": "UC Santa Cruz",
    "UC Santa Cruz": "UC Santa Cruz",
    "UCSC": "UC Santa Cruz",
}

# --- Section headings ------------------------------------------------------
# Lower-cased heading -> canonical section type. Headings not listed here are
# kept with type "other" (nothing is dropped).
SECTION_TYPES = {
    "background": "background",
    "summary": "summary",
    "brief description": "summary",
    "abstract": "summary",
    "technology description": "description",
    "full description": "description",
    "description": "description",
    "innovation": "description",
    "applications": "applications",
    "application": "applications",
    "suggested uses": "applications",
    "advantages": "advantages",
    "features/benefits": "advantages",
    "benefits": "advantages",
    "value proposition": "advantages",
    "state of development": "state_of_development",
    "stage of development": "state_of_development",
    "intellectual property info": "intellectual_property",
    "intellectual property information": "intellectual_property",
    "patent status": "patent_status",
    "related materials": "related_materials",
}

# Canonical types that get their own column on the main technologies table.
MAIN_SECTION_COLUMNS = ("background", "summary", "description", "applications", "advantages")

_TECH_ID_RE = re.compile(r"Tech ID:\s*(\d+)")
# Matches both absolute ("https://.../NCD/20472.html?...") and relative
# ("34880.html?...") links to other technology pages.
_NCD_LINK_RE = re.compile(r"(?:^|/)(\d+)\.html")
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v ]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


@dataclass
class Section:
    """One free-text section of a technology page.

    Attributes:
        position: Order of the section on the page (0-based).
        heading: Heading exactly as shown on the page.
        section_type: Canonical type from SECTION_TYPES, or "other".
        text: Plain-text body (HTML, scripts and images removed).
    """

    position: int
    heading: str
    section_type: str
    text: str


@dataclass
class Patent:
    """One row of a page's patent-status table."""

    country: str
    patent_type: str
    number: str
    dated: str
    case: str


@dataclass
class Technology:
    """Structured record for one technology page.

    One-to-many fields (inventors, categories, ...) are lists; Step 4 stores
    them in their own tables linked by ``tech_id``.
    """

    tech_id: int
    title: str
    uc_case: str | None
    campus: str | None
    campus_raw: str | None
    contact_name: str | None
    contact_email: str | None
    meta_description: str | None
    sections: list[Section] = field(default_factory=list)
    inventors: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    # (category, subcategory) pairs; subcategory is None for top-level only.
    categories: list[tuple[str, str | None]] = field(default_factory=list)
    related_cases: list[str] = field(default_factory=list)
    patents: list[Patent] = field(default_factory=list)
    # (tech_id, relation) where relation is "related" or "same_inventor".
    related_technologies: list[tuple[int, str]] = field(default_factory=list)

    def section_text(self, section_type: str) -> str | None:
        """Return all text for one canonical section type, or None if absent."""
        parts = [s.text for s in self.sections if s.section_type == section_type and s.text]
        return "\n\n".join(parts) if parts else None


class ParseError(ValueError):
    """Raised when a page does not look like a technology page."""


# --- Helpers ---------------------------------------------------------------
def clean_text(text: str) -> str:
    """Collapse whitespace while keeping paragraph/list line breaks."""
    text = _WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def _block_text(nodes: list) -> str:
    """Convert a run of sibling HTML nodes into readable plain text.

    List items become "- item" lines and block elements become separate lines.
    """
    lines: list[str] = []
    for node in nodes:
        if isinstance(node, Comment):
            continue
        if not isinstance(node, Tag):
            text = str(node).strip()
            if text:
                lines.append(text)
            continue
        for li in node.find_all("li"):
            li.insert(0, "- ")
        for br in node.find_all("br"):
            br.replace_with("\n")
        lines.append(node.get_text("\n" if node.name in ("ul", "ol") else " "))
    return clean_text("\n\n".join(lines))


def _text_or_none(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    text = clean_text(tag.get_text(" "))
    return text or None


def normalize_campus(raw: str | None) -> str | None:
    """Map a campus label onto its canonical name (unknown labels pass through)."""
    if not raw:
        return None
    raw = raw.strip()
    return CAMPUS_ALIASES.get(raw, raw)


def section_type_for(heading: str) -> str:
    """Return the canonical section type for a heading (case-insensitive)."""
    return SECTION_TYPES.get(clean_text(heading).lower().rstrip(":"), "other")


def _split_list(text: str | None) -> list[str]:
    """Split a comma/semicolon separated string, dropping blanks and duplicates."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for item in re.split(r"[,;]", text):
        item = clean_text(item).strip(" .")
        if item:
            seen.setdefault(item, None)
    return list(seen)


# --- Field parsers ---------------------------------------------------------
def _parse_sections(fields: Tag | None) -> tuple[list[Section], list[Patent]]:
    """Split the main content block into sections at each <h3> heading."""
    if fields is None:
        return [], []
    for junk in fields.find_all(["script", "style", "img", "noscript"]):
        junk.decompose()

    sections: list[Section] = []
    patents: list[Patent] = []
    heading: str | None = None
    body: list = []

    def flush() -> None:
        if heading is None:
            return
        stype = section_type_for(heading)
        nodes = body
        if stype == "patent_status":
            for node in body:
                if isinstance(node, Tag):
                    tables = [node] if node.name == "table" else node.find_all("table")
                    for table in tables:
                        patents.extend(_parse_patent_table(table))
            nodes = [n for n in body if not (isinstance(n, Tag) and n.name == "table")]
        text = _block_text(nodes)
        # Some pages have headings with nothing under them (e.g. an empty
        # "Abstract"); skip those rather than storing blank sections.
        if text:
            sections.append(Section(len(sections), clean_text(heading), stype, text))

    for child in fields.children:
        if isinstance(child, Tag) and child.name == "h3":
            flush()
            heading, body = child.get_text(" "), []
        elif heading is not None:
            body.append(child)
    flush()
    return sections, patents


def _parse_patent_table(table: Tag) -> list[Patent]:
    """Parse a patent-status table (Country | Type | Number | Dated | Case)."""
    patents = []
    for row in table.find_all("tr"):
        if "patentHeader" in (row.get("class") or []):
            continue
        cells = [clean_text(td.get_text(" ")) for td in row.find_all("td")]
        if len(cells) < 5 or cells[0] == "Country":
            continue
        patents.append(Patent(*cells[:5]))
    return patents


def _parse_categories(block: Tag | None) -> list[tuple[str, str | None]]:
    """Parse the nested "Categorized As" list into (category, subcategory) pairs."""
    if block is None or block.find("ul") is None:
        return []
    pairs: list[tuple[str, str | None]] = []
    for top in block.find("ul").find_all("li", recursive=False):
        parent_tag = top.find("strong") or top.find("a")
        parent = _text_or_none(parent_tag)
        if not parent:
            continue
        children = top.find("ul")
        subs = [_text_or_none(li) for li in children.find_all("li")] if children else []
        subs = [s for s in subs if s]
        if subs:
            pairs.extend((parent, s) for s in subs)
        else:
            pairs.append((parent, None))
    return list(dict.fromkeys(pairs))


def _parse_related_tech(soup: BeautifulSoup, own_id: int) -> list[tuple[int, str]]:
    """Collect links to other technologies from the right-hand panels."""
    found: dict[tuple[int, str], None] = {}
    for css, relation in (("div.related-ncd", "related"), ("div.inventor-ncd", "same_inventor")):
        block = soup.select_one(css)
        if block is None:
            continue
        for a in block.find_all("a", href=True):
            match = _NCD_LINK_RE.search(a["href"])
            if match and int(match.group(1)) != own_id:
                found.setdefault((int(match.group(1)), relation), None)
    return list(found)


# --- Public API ------------------------------------------------------------
def parse_technology(html: bytes | str) -> Technology:
    """Parse one technology page into a Technology record.

    Args:
        html: Raw page HTML.

    Returns:
        The parsed Technology.

    Raises:
        ParseError: If the page has no title or Tech ID (e.g. an error page).
    """
    soup = BeautifulSoup(html, "lxml")

    title = _text_or_none(soup.select_one("h1.tech-heading-main"))
    ref = soup.select_one("div.ncd-data.ref-data")
    id_match = _TECH_ID_RE.search(ref.get_text(" ")) if ref else None
    if not title or not id_match:
        raise ParseError("page has no title or Tech ID")
    tech_id = int(id_match.group(1))

    leadcase = _text_or_none(soup.select_one("span#leadcase"))
    uc_case = re.sub(r"^/?\s*UC Case\s*", "", leadcase).strip() if leadcase else None

    campus_meta = soup.find("meta", attrs={"name": "Campus"})
    campus_raw = campus_meta.get("content", "").strip() if campus_meta else None
    desc_meta = soup.find("meta", attrs={"name": "description"})
    meta_description = clean_text(desc_meta.get("content", "")) if desc_meta else None

    contact = soup.select_one("div.contact-info")
    contact_name = _text_or_none(contact.select_one("#contact-person")) if contact else None
    contact_email = _text_or_none(contact.select_one("#email")) if contact else None

    inventors_block = soup.select_one("div.ncd-data.inventors")
    inventors = (
        list(dict.fromkeys(t for li in inventors_block.find_all("li") if (t := _text_or_none(li))))
        if inventors_block
        else []
    )

    keywords_block = soup.select_one("div.otherdata-keywords p")
    related_block = soup.select_one("div.otherdata-related-cases p")

    sections, patents = _parse_sections(soup.select_one("div.ncd-data.fields"))

    return Technology(
        tech_id=tech_id,
        title=title,
        uc_case=uc_case or None,
        campus=normalize_campus(campus_raw),
        campus_raw=campus_raw or None,
        contact_name=contact_name,
        contact_email=contact_email,
        meta_description=meta_description or None,
        sections=sections,
        inventors=inventors,
        keywords=_split_list(keywords_block.get_text(" ") if keywords_block else None),
        categories=_parse_categories(soup.select_one("div.otherdata-categories")),
        related_cases=_split_list(related_block.get_text(" ") if related_block else None),
        patents=patents,
        related_technologies=_parse_related_tech(soup, tech_id),
    )


def parse_file(path: Path) -> Technology:
    """Parse a saved HTML file (see ``src.scraper.fetch.html_path``)."""
    return parse_technology(path.read_bytes())
