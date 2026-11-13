import requests

from src.scraper.fetch import fetch_one, select_entries
from src.scraper.sitemap import SitemapEntry


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class FakeSession:
    """Returns queued responses (or raises queued exceptions) in order."""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


ENTRY = SitemapEntry(tech_id=123, url="https://example.test/NCD/123.html", lastmod=None)


def no_sleep(_seconds: float) -> None:
    pass


def test_select_entries_spreads_across_range() -> None:
    entries = [SitemapEntry(i, f"u{i}", None) for i in range(100)]
    picked = select_entries(entries, 4)
    assert [e.tech_id for e in picked] == [0, 25, 50, 75]
    assert select_entries(entries, None) == entries


def test_fetch_one_saves_page(tmp_path) -> None:
    session = FakeSession([FakeResponse(200, b"<html>ok</html>")])
    result = fetch_one(ENTRY, session, tmp_path, sleep=no_sleep)
    assert result.status == "200"
    assert (tmp_path / "123.html").read_bytes() == b"<html>ok</html>"


def test_fetch_one_skips_existing_without_request(tmp_path) -> None:
    (tmp_path / "123.html").write_bytes(b"existing")
    session = FakeSession([])
    result = fetch_one(ENTRY, session, tmp_path, sleep=no_sleep)
    assert result.status == "skipped"
    assert session.calls == 0
    assert (tmp_path / "123.html").read_bytes() == b"existing"


def test_fetch_one_does_not_retry_404(tmp_path) -> None:
    session = FakeSession([FakeResponse(404)])
    result = fetch_one(ENTRY, session, tmp_path, sleep=no_sleep)
    assert result.status == "404"
    assert session.calls == 1
    assert not (tmp_path / "123.html").exists()


def test_fetch_one_retries_then_succeeds(tmp_path) -> None:
    session = FakeSession(
        [requests.ConnectionError("boom"), FakeResponse(503), FakeResponse(200, b"x")]
    )
    result = fetch_one(ENTRY, session, tmp_path, sleep=no_sleep)
    assert result.status == "200"
    assert session.calls == 3


def test_fetch_one_gives_up_after_max_retries(tmp_path) -> None:
    session = FakeSession([FakeResponse(503)] * 3)
    result = fetch_one(ENTRY, session, tmp_path, sleep=no_sleep)
    assert result.status == "error"
    assert "503" in result.error
