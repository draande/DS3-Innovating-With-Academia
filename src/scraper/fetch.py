"""Step 2: download each technology page to data/raw/html/<tech_id>.html.

The download is resumable: pages already on disk are skipped, so the script can
be stopped and restarted at any time. Every attempt is appended to
data/raw/fetch_log.csv so failures (e.g. 404s) can be reviewed afterwards.

Usage:
    python -m src.scraper.fetch --limit 50   # trial run on 50 pages
    python -m src.scraper.fetch              # all pages
"""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.scraper import config
from src.scraper.sitemap import SitemapEntry, load_entries

LOG_FIELDS = ["tech_id", "url", "status", "bytes", "fetched_at", "error"]

# HTTP statuses worth retrying (temporary server-side problems / rate limiting).
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    """Outcome of fetching one page.

    Attributes:
        tech_id: Tech ID of the page.
        url: URL requested.
        status: HTTP status code, "skipped" if already on disk, or "error".
        bytes: Size of the saved page (0 if nothing was saved).
        error: Error message, if any.
    """

    tech_id: int
    url: str
    status: str
    bytes: int = 0
    error: str = ""


def html_path(tech_id: int, html_dir: Path = config.HTML_DIR) -> Path:
    """Return the local path where a page's raw HTML is stored."""
    return html_dir / f"{tech_id}.html"


def select_entries(entries: list[SitemapEntry], limit: int | None) -> list[SitemapEntry]:
    """Pick which entries to fetch.

    With a limit, entries are spread evenly across the ID range (rather than
    taking the first N) so a trial run covers both old and new page layouts.

    Args:
        entries: All sitemap entries, sorted by tech_id.
        limit: Maximum number of entries, or None for all.

    Returns:
        The selected entries.
    """
    if limit is None or limit >= len(entries):
        return entries
    if limit <= 0:
        return []
    step = len(entries) / limit
    return [entries[int(i * step)] for i in range(limit)]


def fetch_one(
    entry: SitemapEntry,
    session: requests.Session,
    html_dir: Path = config.HTML_DIR,
    sleep=time.sleep,
) -> FetchResult:
    """Download one page, retrying temporary failures, and save it on success.

    Args:
        entry: The sitemap entry to fetch.
        session: HTTP session (reused for connection pooling).
        html_dir: Directory to save HTML into.
        sleep: Sleep function (injectable so tests run instantly).

    Returns:
        A FetchResult describing what happened. Existing files are never
        overwritten; they return status "skipped".
    """
    path = html_path(entry.tech_id, html_dir)
    if path.exists():
        return FetchResult(entry.tech_id, entry.url, "skipped", path.stat().st_size)

    last_error = ""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(entry.url, timeout=config.REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(response.content)
                return FetchResult(entry.tech_id, entry.url, "200", len(response.content))
            if response.status_code not in RETRYABLE_STATUSES:
                return FetchResult(entry.tech_id, entry.url, str(response.status_code))
            last_error = f"HTTP {response.status_code}"
        if attempt < config.MAX_RETRIES:
            sleep(config.RETRY_BACKOFF_SECONDS * attempt)
    return FetchResult(entry.tech_id, entry.url, "error", error=last_error)


def append_log(result: FetchResult, log_path: Path = config.FETCH_LOG_PATH) -> None:
    """Append one fetch result to the CSV log (creating it with a header if new)."""
    is_new = not log_path.exists()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "tech_id": result.tech_id,
                "url": result.url,
                "status": result.status,
                "bytes": result.bytes,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "error": result.error,
            }
        )


def fetch_all(
    entries: list[SitemapEntry],
    html_dir: Path = config.HTML_DIR,
    log_path: Path = config.FETCH_LOG_PATH,
    delay: float = config.REQUEST_DELAY_SECONDS,
) -> list[FetchResult]:
    """Fetch every entry sequentially with a polite delay between requests.

    Args:
        entries: Entries to fetch.
        html_dir: Directory to save HTML into.
        log_path: CSV log of attempts (skipped pages are not logged).
        delay: Seconds to wait after each network request.

    Returns:
        One FetchResult per entry.
    """
    results: list[FetchResult] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = config.USER_AGENT
        for i, entry in enumerate(entries, start=1):
            result = fetch_one(entry, session, html_dir)
            results.append(result)
            if result.status != "skipped":
                append_log(result, log_path)
                time.sleep(delay)
            if i % 100 == 0 or i == len(entries):
                print(f"[{i}/{len(entries)}] last: {entry.tech_id} -> {result.status}", flush=True)
    return results


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="fetch at most N pages")
    args = parser.parse_args()

    entries = select_entries(load_entries(), args.limit)
    results = fetch_all(entries)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print("Summary:", counts)


if __name__ == "__main__":
    main()
