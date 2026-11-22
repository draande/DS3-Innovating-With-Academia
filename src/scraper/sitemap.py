"""Step 1: download the site's sitemap and list every technology article."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import requests

from src.scraper import config

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_ARTICLE_RE = re.compile(config.ARTICLE_URL_PATTERN)


@dataclass(frozen=True)
class SitemapEntry:
    """One technology article listed in the sitemap.

    Attributes:
        tech_id: Numeric Tech ID taken from the URL (e.g. 34887).
        url: Full URL of the article page.
        lastmod: Last-modified date string from the sitemap (YYYY-MM-DD), or None.
    """

    tech_id: int
    url: str
    lastmod: str | None


def download_sitemap(path: Path = config.SITEMAP_PATH, overwrite: bool = False) -> Path:
    """Download sitemap.xml to ``path`` and return the path.

    Args:
        path: Where to save the sitemap.
        overwrite: Re-download even if the file already exists. Defaults to
            False so the raw snapshot in data/raw/ is never silently replaced.

    Returns:
        The path the sitemap was saved to.
    """
    if path.exists() and not overwrite:
        return path
    response = requests.get(
        config.SITEMAP_URL,
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return path


def parse_sitemap(xml_bytes: bytes) -> list[SitemapEntry]:
    """Extract technology article entries from sitemap XML.

    Non-article URLs (e.g. Default.aspx, Categories.aspx) are skipped.

    Args:
        xml_bytes: Raw sitemap XML.

    Returns:
        Entries sorted by tech_id, with duplicates removed.
    """
    root = ET.fromstring(xml_bytes)
    entries: dict[int, SitemapEntry] = {}
    for url_el in root.findall("sm:url", _SITEMAP_NS):
        loc = (url_el.findtext("sm:loc", default="", namespaces=_SITEMAP_NS) or "").strip()
        match = _ARTICLE_RE.search(loc)
        if not match:
            continue
        lastmod = url_el.findtext("sm:lastmod", default=None, namespaces=_SITEMAP_NS)
        tech_id = int(match.group(1))
        entries[tech_id] = SitemapEntry(
            tech_id=tech_id, url=loc, lastmod=lastmod.strip() if lastmod else None
        )
    return [entries[k] for k in sorted(entries)]


def load_entries(path: Path = config.SITEMAP_PATH) -> list[SitemapEntry]:
    """Download the sitemap if needed and return all article entries.

    Args:
        path: Location of the local sitemap snapshot.

    Returns:
        All technology article entries in the sitemap.
    """
    download_sitemap(path)
    return parse_sitemap(path.read_bytes())
