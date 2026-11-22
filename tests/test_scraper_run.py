from src.scraper.run import parse_args


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.limit is None
    assert not args.parse_only
    assert not args.refresh_sitemap


def test_parse_args_options() -> None:
    args = parse_args(["--limit", "50", "--parse-only"])
    assert args.limit == 50
    assert args.parse_only
