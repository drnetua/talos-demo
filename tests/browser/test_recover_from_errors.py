import re

import httpx
import pytest
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


REJECTED = "The action did not succeed."
UNAVAILABLE = "The service is unavailable."
MESSAGES = "#message, #form-message, #edit-message"


def _fail(page: Page, method: str, mode: str) -> None:
    def handle(route: Route) -> None:
        if route.request.method != method:
            route.continue_()
        elif mode == "abort":
            route.abort()
        elif mode == "403":
            route.fulfill(status=403, content_type="application/json", body='{"detail": "no"}')
        else:
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"detail": "Traceback boom"}',
            )

    page.route(re.compile(r"/notes(/\d+)?$"), handle)


def _assert_plain(page: Page) -> None:
    for text in page.locator(MESSAGES).all_inner_texts():
        for raw in ("500", "403", "detail", "Traceback"):
            assert raw not in text


MODES = [("500", REJECTED), ("403", REJECTED), ("abort", UNAVAILABLE)]


@pytest.mark.parametrize(("mode", "text"), MODES)
def test_create_failure_keeps_text(page: Page, live_server: str, mode: str, text: str) -> None:
    page.goto(live_server)
    expect(page.locator("#message")).to_have_text("No notes yet")
    _fail(page, "POST", mode)
    page.locator("#note-title").fill("Keep me")
    page.locator("#note-body").fill("body text")
    page.locator("#note-tags").fill("a, b")
    page.locator("#save").click()
    expect(page.locator("#form-message")).to_have_text(text)
    expect(page.locator("#note-title")).to_have_value("Keep me")
    expect(page.locator("#note-body")).to_have_value("body text")
    expect(page.locator("#note-tags")).to_have_value("a, b")
    expect(page.locator("#notes li")).to_have_count(0)
    _assert_plain(page)


@pytest.mark.parametrize(("mode", "text"), MODES)
def test_edit_failure_keeps_text(
    page: Page, live_server: str, seed: Seed, mode: str, text: str
) -> None:
    seed(1)
    page.goto(live_server)
    page.get_by_role("button", name="Edit").click()
    expect(page.locator("#edit-form")).to_be_visible()
    _fail(page, "PUT", mode)
    page.locator("#edit-title").fill("Changed")
    page.locator("#edit-save").click()
    expect(page.locator("#edit-message")).to_have_text(text)
    expect(page.locator("#edit-title")).to_have_value("Changed")
    expect(page.locator("#notes .note-title")).to_have_text("note 0")
    _assert_plain(page)


@pytest.mark.parametrize(("mode", "text"), MODES)
def test_delete_failure_keeps_row(
    page: Page, live_server: str, seed: Seed, mode: str, text: str
) -> None:
    seed(1)
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(1)
    _fail(page, "DELETE", mode)
    page.get_by_role("button", name="Delete", exact=True).click()
    page.locator("#confirm-delete").click()
    expect(page.locator("#message")).to_have_text(text)
    expect(page.locator("#notes li")).to_have_count(1)
    _assert_plain(page)


@pytest.mark.parametrize(("mode", "text"), MODES)
def test_tag_add_failure_keeps_note(
    page: Page, live_server: str, seed: Seed, mode: str, text: str
) -> None:
    seed(1)
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(1)
    _fail(page, "PUT", mode)
    page.get_by_label("New tag").fill("x")
    page.get_by_role("button", name="Add tag").click()
    expect(page.locator("#message")).to_have_text(text)
    expect(page.locator("#notes li .tag")).to_have_count(0)
    _assert_plain(page)


@pytest.mark.parametrize(("mode", "text"), MODES)
def test_tag_remove_failure_keeps_note(
    page: Page, live_server: str, seed: Seed, mode: str, text: str
) -> None:
    note = seed(1)[0]
    httpx.put(f"{live_server}/notes/{note['id']}", json={"title": "note 0", "tags": ["x"]})
    page.goto(live_server)
    expect(page.locator("#notes li .tag")).to_have_count(1)
    _fail(page, "PUT", mode)
    page.get_by_label("Remove tag x").click()
    expect(page.locator("#message")).to_have_text(text)
    expect(page.locator("#notes li .tag")).to_have_count(1)
    _assert_plain(page)
