import httpx
from playwright.sync_api import Page, Route, expect

from .conftest import Seed

REFRESHED = "The list was refreshed from the start."


def _reject_cursor_once(page: Page) -> list[str]:
    seen: list[str] = []

    def handle(route: Route) -> None:
        if seen:
            route.continue_()
            return
        seen.append(route.request.url)
        route.fulfill(
            status=422,
            content_type="application/json",
            body='{"detail": "invalid page cursor"}',
        )

    page.route("**/notes?*cursor=*", handle)
    return seen


def _assert_no_raw_error(page: Page) -> None:
    text = page.locator("body").inner_text()
    for raw in ("422", "detail", "invalid page cursor"):
        assert raw not in text


def test_rejected_cursor_restarts_list(page: Page, seed: Seed, live_server: str) -> None:
    seed(60)
    seen = _reject_cursor_once(page)
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(50)
    page.locator("#load-more").click()
    expect(page.locator("#message")).to_have_text(REFRESHED)
    expect(page.locator("#notes li")).to_have_count(50)
    ids = page.locator("#notes li").evaluate_all("els => els.map(e => e.dataset.id)")
    assert len(set(ids)) == 50
    assert len(seen) == 1
    _assert_no_raw_error(page)
    # the list still works afterwards
    page.locator("#load-more").click()
    expect(page.locator("#notes li")).to_have_count(60)


def test_rejected_cursor_keeps_tag_filter(page: Page, seed: Seed, live_server: str) -> None:
    for i, note in enumerate(seed(60)):
        tags = ["a"] if i < 55 else ["b"]
        httpx.put(
            f"{live_server}/notes/{note['id']}", json={"title": note["title"], "tags": tags}
        ).raise_for_status()
    seen = _reject_cursor_once(page)
    page.goto(live_server)
    page.get_by_role("button", name="Filter by tag a,").click()
    expect(page.locator("#notes li")).to_have_count(50)
    page.locator("#load-more").click()
    expect(page.locator("#message")).to_have_text(REFRESHED)
    expect(page.locator("#notes li")).to_have_count(50)
    expect(page.locator("#filter-tag")).to_have_text("a")
    titles = page.locator("#notes li .note-title").all_inner_texts()
    assert all(int(t.split()[1]) < 55 for t in titles)
    assert len(seen) == 1
    _assert_no_raw_error(page)
