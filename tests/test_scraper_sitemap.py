from src.scraper.sitemap import SitemapEntry, parse_sitemap

SAMPLE_SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://techtransfer.universityofcalifornia.edu/Categories.aspx</loc><lastmod>2026-11-12</lastmod></url>
  <url><loc>https://techtransfer.universityofcalifornia.edu/NCD/34887.html</loc><lastmod>2026-11-12</lastmod></url>
  <url><loc>https://techtransfer.universityofcalifornia.edu/NCD/10027.html</loc><lastmod>2010-04-14</lastmod></url>
  <url><loc>https://techtransfer.universityofcalifornia.edu/NCD/10027.html</loc><lastmod>2010-04-14</lastmod></url>
  <url><loc>https://techtransfer.universityofcalifornia.edu/NCD/20000.html</loc></url>
</urlset>
"""


def test_parse_sitemap_keeps_only_articles_sorted_and_deduped() -> None:
    entries = parse_sitemap(SAMPLE_SITEMAP)
    assert [e.tech_id for e in entries] == [10027, 20000, 34887]


def test_parse_sitemap_fields() -> None:
    entries = {e.tech_id: e for e in parse_sitemap(SAMPLE_SITEMAP)}
    assert entries[34887] == SitemapEntry(
        tech_id=34887,
        url="https://techtransfer.universityofcalifornia.edu/NCD/34887.html",
        lastmod="2026-11-12",
    )
    assert entries[20000].lastmod is None
