"""An in-memory fake of books.toscrape.com / quotes.toscrape.com.

Served through Playwright's ``context.route`` so tests run fully offline, deterministically,
and can inject failures (500s, 404s) that are impossible to trigger on the real site.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from playwright.async_api import BrowserContext, Route

BOOKS_BASE = "https://books.toscrape.com/"
QUOTES_URL = "https://quotes.toscrape.com/scroll"

RATINGS = ["Zero", "One", "Two", "Three", "Four", "Five"]


def listing_html(book_hrefs: list[str], next_href: str | None) -> str:
    articles = "\n".join(
        f"""<article class="product_pod">
              <h3><a href="{href}" title="t">t</a></h3>
              <p class="price_color">£1.00</p>
            </article>"""
        for href in book_hrefs
    )
    nxt = f'<li class="next"><a href="{next_href}">next</a></li>' if next_href else ""
    return f"<html><body><section>{articles}</section><ul class='pager'>{nxt}</ul></body></html>"


def book_html(
    title: str, *, price: str, rating: int, stock: str, upc: str, category: str = "Poetry"
) -> str:
    return f"""<html><body>
      <ul class="breadcrumb">
        <li><a href="/">Home</a></li><li><a href="#">Books</a></li>
        <li><a href="#">{category}</a></li><li class="active">{title}</li>
      </ul>
      <div id="product_gallery"><img src="../../media/cover.jpg"></div>
      <div class="product_main">
        <h1>{title}</h1>
        <p class="price_color">{price}</p>
        <p class="instock availability"><i class="icon-ok"></i>
            {stock}
        </p>
        <p class="star-rating {RATINGS[rating]}"></p>
      </div>
      <div id="product_description"><h2>Product Description</h2></div>
      <p>A description of {title}.</p>
      <table class="table table-striped">
        <tr><th>UPC</th><td>{upc}</td></tr>
        <tr><th>Product Type</th><td>Books</td></tr>
      </table>
    </body></html>"""


# Infinite-scroll page: renders quotes with JS, appends a batch on each scroll to bottom.
QUOTES_HTML = """<html><body style="margin:0">
<div id="quotes"></div><div style="height:2000px"></div>
<script>
  const batches = [
    [["“First quote”", "Ada", ["a", "b"]], ["“Second”", "Linus", []]],
    [["“Third”", "Grace", ["c"]]],
    [["“Fourth”", "Alan", ["d", "e"]]],
  ];
  let next = 0;
  function load() {
    if (next >= batches.length) return;
    for (const [t, a, tags] of batches[next++]) {
      const d = document.createElement('div'); d.className = 'quote';
      d.innerHTML = `<span class="text">${t}</span><small class="author">${a}</small>
        <div class="tags">${tags.map(x => `<a class="tag">${x}</a>`).join('')}</div>`;
      document.getElementById('quotes').appendChild(d);
    }
  }
  setTimeout(load, 50);  // first batch arrives after load, like a real XHR
  window.addEventListener('scroll', () => {
    if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 5) setTimeout(load, 50);
  });
</script></body></html>"""


@dataclass
class MockSite:
    """Maps absolute URL -> (status, body). ``flaky`` URLs fail with 500 N times first."""

    pages: dict[str, tuple[int, str]] = field(default_factory=dict)
    flaky: dict[str, int] = field(default_factory=dict)
    hits: Counter[str] = field(default_factory=Counter)

    async def handle(self, route: Route) -> None:
        url = route.request.url
        self.hits[url] += 1
        if self.flaky.get(url, 0) >= self.hits[url]:
            await route.fulfill(status=500, body="boom")
            return
        status, body = self.pages.get(url, (404, "not found"))
        await route.fulfill(status=status, body=body, content_type="text/html; charset=utf-8")

    async def install(self, context: BrowserContext) -> None:
        await context.route("https://books.toscrape.com/**", self.handle)
        await context.route("https://quotes.toscrape.com/**", self.handle)


def build_books_site() -> MockSite:
    """Two listing pages, four books: one flaky (500 once), one missing (404)."""
    site = MockSite()
    cat = BOOKS_BASE + "catalogue/"
    site.pages[BOOKS_BASE] = (
        200,
        listing_html(
            ["catalogue/book-a_1/index.html", "catalogue/book-b_2/index.html"],
            "catalogue/page-2.html",
        ),
    )
    site.pages[cat + "page-2.html"] = (
        200,
        listing_html(["book-c_3/index.html", "book-missing_4/index.html"], None),
    )
    site.pages[cat + "book-a_1/index.html"] = (
        200,
        book_html("Book A", price="£51.77", rating=3, stock="In stock (22 available)", upc="A1"),
    )
    site.pages[cat + "book-b_2/index.html"] = (
        200,
        book_html("Book B", price="£10.00", rating=5, stock="In stock (1 available)", upc="B2"),
    )
    site.pages[cat + "book-c_3/index.html"] = (
        200,
        book_html("Book C", price="£0.99", rating=1, stock="Out of stock", upc="C3"),
    )
    site.flaky[cat + "book-b_2/index.html"] = 1
    return site


def build_quotes_site() -> MockSite:
    return MockSite(pages={QUOTES_URL: (200, QUOTES_HTML)})
