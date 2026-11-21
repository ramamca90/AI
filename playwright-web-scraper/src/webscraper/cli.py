"""Command-line entry point.

Examples::

    scraper books --max-pages 2 --concurrency 8 -o data/books.csv
    scraper quotes --headed --format jsonl
    SCRAPER_LOG_JSON=true scraper books        # structured logs for production
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel, ValidationError

from webscraper import __version__
from webscraper.config import BrowserName, ScraperSettings
from webscraper.exceptions import ScraperError
from webscraper.logging_config import setup_logging
from webscraper.runner import run_scraper
from webscraper.scrapers import BooksScraper, QuotesScraper
from webscraper.scrapers.base import BaseScraper
from webscraper.storage import OutputFormat

logger = logging.getLogger("webscraper")

EXIT_OK, EXIT_ERROR, EXIT_PARTIAL = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("common options")
    g.add_argument("-o", "--output", type=Path, help="Output file (default: data/<target>.<fmt>)")
    g.add_argument("-f", "--format", choices=["jsonl", "csv"], default="jsonl")
    g.add_argument("--browser", choices=get_args(BrowserName))
    g.add_argument("--headed", action="store_true", help="Show the browser window")
    g.add_argument("-c", "--concurrency", type=int, help="Parallel pages")
    g.add_argument("--max-retries", type=int)
    g.add_argument("--delay", type=float, dest="request_delay_s", help="Politeness delay (s)")
    g.add_argument("--no-robots", action="store_true", help="Skip robots.txt check")
    g.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    g.add_argument("--log-json", action="store_true", default=None)

    parser = argparse.ArgumentParser(prog="scraper", description="Async Playwright web scraper.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="target", required=True, metavar="TARGET")

    books = sub.add_parser("books", parents=[common], help="books.toscrape.com catalogue")
    books.add_argument("--max-pages", type=int, help="Stop after N listing pages (default: all)")

    quotes = sub.add_parser("quotes", parents=[common], help="quotes.toscrape.com (JS + scroll)")
    quotes.add_argument("--max-scrolls", type=int, default=50)
    return parser


def settings_from_args(args: argparse.Namespace) -> ScraperSettings:
    overrides: dict[str, Any] = {
        "browser": args.browser,
        "concurrency": args.concurrency,
        "max_retries": args.max_retries,
        "request_delay_s": args.request_delay_s,
        "log_level": args.log_level,
        "log_json": args.log_json,
    }
    if args.headed:
        overrides["headless"] = False
    if args.no_robots:
        overrides["respect_robots_txt"] = False
    # Only pass explicit CLI values so env vars / .env still apply otherwise.
    return ScraperSettings(**{k: v for k, v in overrides.items() if v is not None})


def build_scraper(args: argparse.Namespace, settings: ScraperSettings) -> BaseScraper[BaseModel]:
    if args.target == "books":
        return BooksScraper(settings, max_pages=args.max_pages)  # type: ignore[return-value]
    return QuotesScraper(settings, max_scrolls=args.max_scrolls)  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = settings_from_args(args)
    except ValidationError as exc:
        print(f"Invalid configuration:\n{exc}")
        return EXIT_ERROR

    setup_logging(settings.log_level, json_output=settings.log_json)
    fmt: OutputFormat = args.format
    output: Path = args.output or Path("data") / f"{args.target}.{fmt}"

    try:
        summary = asyncio.run(run_scraper(build_scraper(args, settings), settings, output, fmt))
    except KeyboardInterrupt:
        logger.warning("Interrupted - partial output discarded")
        return 130
    except ScraperError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR
    except Exception:
        logger.exception("Unexpected failure")
        return EXIT_ERROR
    return EXIT_OK if summary.ok else EXIT_PARTIAL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
