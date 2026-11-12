import httpx
from playwright.sync_api import Page, expect

from .conftest import Seed


def _post(live_server: str, title: str, body: str = "", tags: list[str] | None = None) -> None:
    resp = httpx.post(
        f"{live_server}/notes", json={"title": title, "body": body, "tags": tags or []}
    )
    resp.raise_for_status()


def _search(page: Page, text: str) -> None:
    page.get_by_label("Search notes").fill(text)
    page.get_by_role("button", name="Search", exact=True).click()


def test_search_title_and_body(page: Page, live_server: str) -> None:
    _post(live_server, "apple pie")
    _post(live_server, "groceries", "buy an apple")
    _post(live_server, "other")
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(3)
    _search(page, "apple")
    expect(page.locator("#notes li")).to_have_count(2)
    expect(page.locator("#search-bar")).to_be_visible()
    expect(page.locator("#search-text")).to_have_text("apple")
    expect(page.locator("#load-more")).to_be_hidden()


def test_search_replaces_tag_filter_and_back(page: Page, live_server: str) -> None:
    _post(live_server, "apple one", tags=["a"])
    _post(live_server, "pear", tags=["a"])
    _post(live_server, "apple two", tags=["b"])
    page.goto(live_server)
    page.get_by_role("button", name="Filter by tag a,").click()
    expect(page.locator("#filter-bar")).to_be_visible()
    _search(page, "apple")
    expect(page.locator("#filter-bar")).to_be_hidden()
    expect(page.locator("#search-bar")).to_be_visible()
    expect(page.locator("#notes li")).to_have_count(2)
    page.get_by_role("button", name="Filter by tag b,").click()
    expect(page.locator("#search-bar")).to_be_hidden()
    expect(page.get_by_label("Search notes")).to_have_value("")
    expect(page.locator("#filter-bar")).to_be_visible()
    expect(page.locator("#notes li")).to_have_count(1)


def test_no_match_message(page: Page, live_server: str, seed: Seed) -> None:
    seed(2)
    page.goto(live_server)
    _search(page, "zzz")
    expect(page.locator("#message")).to_have_text("No notes found")
    expect(page.locator("#notes li")).to_have_count(0)


def test_clear_search_returns_first_page(page: Page, live_server: str, seed: Seed) -> None:
    seed(60)
    page.goto(live_server)
    _search(page, "note 1")
    expect(page.locator("#search-bar")).to_be_visible()
    page.get_by_role("button", name="Clear search").click()
    expect(page.locator("#search-bar")).to_be_hidden()
    expect(page.locator("#notes li")).to_have_count(50)
    expect(page.locator("#load-more")).to_be_visible()


def test_search_needs_one_click(page: Page, live_server: str, seed: Seed) -> None:
    seed(3)
    page.goto(live_server)
    clicks: list[int] = []
    page.expose_function("record_click", lambda: clicks.append(1))
    page.evaluate("document.addEventListener('click', () => window.record_click(), true)")
    _search(page, "note 2")
    expect(page.locator("#notes li")).to_have_count(1)
    assert len(clicks) <= 3


def test_search_request_is_encoded(page: Page, live_server: str) -> None:
    text = "a&b #c ü"
    _post(live_server, text)
    _post(live_server, "plain")
    page.goto(live_server)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url) if "/notes/search" in r.url else None)
    _search(page, text)
    expect(page.locator("#notes li")).to_have_count(1)
    assert requests[0].endswith("/notes/search?q=a%26b%20%23c%20%C3%BC")
