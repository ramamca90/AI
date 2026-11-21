import pytest

from webscraper.cli import build_parser, settings_from_args


def test_cli_flags_override_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPER_CONCURRENCY", "2")
    args = build_parser().parse_args(
        ["books", "--max-pages", "3", "-c", "9", "--headed", "--no-robots"]
    )
    s = settings_from_args(args)
    assert args.max_pages == 3
    assert s.concurrency == 9  # CLI beats env
    assert s.headless is False
    assert s.respect_robots_txt is False


def test_env_used_when_flag_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPER_CONCURRENCY", "2")
    s = settings_from_args(build_parser().parse_args(["quotes"]))
    assert s.concurrency == 2


def test_target_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
