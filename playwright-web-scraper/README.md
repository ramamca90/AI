# Playwright Web Scraper

A production-style, **async web scraping framework built on Python Playwright**, with two
reference scrapers that show the two problems Playwright solves best:

| Scraper  | Target                                  | What it demonstrates |
|----------|-----------------------------------------|----------------------|
| `books`  | `books.toscrape.com` (1,000 books, 50 pages) | Pagination, **bounded-concurrency fan-out** over hundreds of detail pages, per-item retries & failure isolation |
| `quotes` | `quotes.toscrape.com/scroll`            | **JavaScript-rendered** content + **infinite scroll** - the case `requests` + BeautifulSoup cannot handle |

Both targets are public sandboxes built specifically for scraping practice.

---

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

scraper books --max-pages 2          # -> data/books.jsonl
scraper books -f csv -c 10           # all 1,000 books, 10 tabs in parallel, CSV
scraper quotes --headed              # watch the browser scroll
python -m webscraper --help
```

Exit codes: `0` success · `1` fatal error · `2` finished but some items failed · `130` interrupted.

## Architecture

```
src/webscraper/
├── cli.py            argparse CLI; CLI flags > env vars > .env > defaults
├── config.py         pydantic-settings, validated config (SCRAPER_* env vars)
├── runner.py         orchestration: robots.txt -> browser -> scraper -> storage -> summary
├── browser.py        browser/context lifecycle, resource blocking, typed HTTP errors
├── retry.py          async retry, exponential backoff + full jitter, retry policy
├── exceptions.py     retryable vs non-retryable error taxonomy
├── models.py         pydantic output schemas - scraped data is validated before saving
├── parsing.py        pure text normalisers (price, rating, stock) - unit tested
├── storage.py        streaming JSONL/CSV writers with atomic rename
├── robots.py         robots.txt compliance
├── logging_config.py human or JSON-lines logs
└── scrapers/
    ├── base.py       BaseScraper[T]: async-generator contract + shared helpers
    ├── books.py      pagination + concurrent detail pages
    └── quotes.py     JS rendering + infinite scroll
```

```
CLI ─► Settings ─► run_scraper ─► robots.txt check
                        │
                        ▼
              browser_context()  (1 browser, 1 isolated context, images/fonts blocked)
                        │
                        ▼
            scraper.scrape(ctx)  ── async generator ──►  open_writer()  ──► data/x.jsonl.part
              │                                                                │ os.replace
              ├─ listing pages (sequential, follow "next")                     ▼
              └─ detail pages  (asyncio.Semaphore(N) tabs, retry each)    data/x.jsonl
```

## Production concerns and how they're handled

| Concern | Approach |
|---|---|
| **Throughput** | `asyncio` + one tab per worker, capped by `asyncio.Semaphore(concurrency)`. One browser process, one context - tabs are cheap, browsers aren't. |
| **Bandwidth / speed** | `context.route("**/*")` aborts image, font and media requests. |
| **Transient failures** | `retry_async` with exponential backoff + full jitter. Timeouts, `net::ERR_*`, 408/429/5xx retry; 404/403 and layout changes (`ParseError`) fail fast. |
| **Failure isolation** | A failed detail page is logged and recorded in `stats.failed_urls`; the run continues. Exit code `2` signals partial success to schedulers. |
| **Dynamic content** | Explicit waits (`locator.wait_for`, `page.wait_for_function`) instead of `sleep()`. |
| **Data quality** | Every record passes a pydantic model (types, ranges, `Decimal` money) before it's written. A bad layout raises `ParseError` instead of silently writing empty fields. |
| **Output integrity** | Streamed to `*.part`, atomically renamed on success. Crashes never leave half-written files or clobber the last good output. Constant memory regardless of size. |
| **Resource leaks** | Async context managers close pages, context and browser on every path, including Ctrl+C; pending tasks are cancelled if the consumer stops early. |
| **Politeness / compliance** | robots.txt check, configurable per-worker delay, identifiable user-agent. |
| **Observability** | Structured logging (`SCRAPER_LOG_JSON=true`) with a run summary record; `--log-level DEBUG`. |
| **Configuration** | Typed, validated settings from CLI / env / `.env` (see `.env.example`). |
| **Extensibility** | New site = subclass `BaseScraper[YourModel]`, implement `async def scrape()`, register in `scrapers/__init__.py`. |
| **Hooks** | `run_scraper(..., setup_context=fn)` - load auth cookies, start tracing, or mock the network. |

## Testing

```bash
pytest                 # offline suite (default) - real Chromium, mocked network
pytest --cov           # with coverage
pytest -m live         # smoke tests against the real sites (canary for layout changes)
ruff check . && ruff format --check . && mypy
```

The offline suite drives a real browser against an **in-memory fake site** served via
`context.route()` (`tests/mock_site.py`). That makes tests fast and deterministic, and lets
them inject failures that the real site can't produce on demand - a page that returns 500
once (asserts it's retried exactly once) and a 404 (asserts it's *not* retried and the run
continues). The quotes fake renders content with JS and appends batches on scroll.

## Configuration

All settings can be set as `SCRAPER_<NAME>` env vars or in a `.env` file:

| Setting | Default | |
|---|---|---|
| `BROWSER` | `chromium` | `chromium` / `firefox` / `webkit` |
| `HEADLESS` | `true` | |
| `CONCURRENCY` | `5` | parallel tabs (1-32) |
| `MAX_RETRIES` | `3` | |
| `RETRY_BASE_DELAY_S` / `RETRY_MAX_DELAY_S` | `1.0` / `20.0` | backoff |
| `REQUEST_DELAY_S` | `0` | politeness delay per worker |
| `NAVIGATION_TIMEOUT_MS` | `30000` | |
| `BLOCK_RESOURCES` | `true` | |
| `RESPECT_ROBOTS_TXT` | `true` | |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `false` | |

## Docker

```bash
docker build -t webscraper .
docker run --rm -v "$PWD/data:/app/data" webscraper books --max-pages 2
```

## Adding a new site

```python
class ProductsScraper(BaseScraper[Product]):
    name = "products"
    start_url = "https://example.com/products"

    async def scrape(self, context):
        page = await context.new_page()
        await self.with_retry(lambda: goto(page, self.start_url), self.start_url)
        for card in await page.locator(".product").all():
            yield Product(name=await card.locator("h2").inner_text(), ...)
```

## Possible next steps

- Persist a crawl frontier (SQLite/Redis) for resumable runs and cross-process scaling
- Proxy rotation and per-domain rate limiting
- Playwright tracing (`context.tracing`) on failure for post-mortem debugging
- Prometheus metrics; schedule via cron/Airflow with the exit-code contract
