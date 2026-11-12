from collections.abc import Callable

import httpx
from playwright.sync_api import Page, Route, expect

from .conftest import Seed


def _fill(page: Page, title: str, body: str = "", tags: str = "") -> None:
    page.get_by_label("Title").fill(title)
    page.get_by_label("Body").fill(body)
    page.get_by_label("Tags").fill(tags)


def _count(live_server: str) -> int:
    return len(httpx.get(f"{live_server}/notes").json()["items"])


def test_title_body_tags_appear_without_reload(page: Page, live_server: str, seed: Seed) -> None:
    seed(2)
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(2)
    page.evaluate("window.marker = 1")
    _fill(page, "Groceries", "milk and eggs", " Food , HOME,, ")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("#notes li")).to_have_count(3)
    assert page.evaluate("window.marker") == 1
    row = page.locator("#notes li").last
    expect(row).to_contain_text("Groceries")
    expect(row).to_contain_text("milk and eggs")
    expect(row.locator(".tag")).to_have_text(["food\u00d7", "home\u00d7"])
    created = httpx.get(f"{live_server}/notes").json()["items"][-1]
    assert created["title"] == "Groceries"
    assert created["tags"] == ["food", "home"]


def test_title_only_clears_form(page: Page, live_server: str) -> None:
    page.goto(live_server)
    expect(page.get_by_text("No notes yet")).to_be_visible()
    _fill(page, "Just a title")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("#notes li")).to_have_count(1)
    expect(page.locator("#notes li .note-body")).to_have_text("")
    expect(page.locator("#notes li .tag")).to_have_count(0)
    expect(page.get_by_label("Title")).to_have_value("")
    expect(page.get_by_label("Body")).to_have_value("")
    expect(page.get_by_label("Tags")).to_have_value("")
    expect(page.get_by_text("No notes yet")).to_have_count(0)


def test_blank_title_shows_message_and_sends_nothing(page: Page, live_server: str) -> None:
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.goto(live_server)
    for title in ("", "   "):
        _fill(page, title, "keep me", "a,b")
        page.get_by_role("button", name="Save").click()
        expect(page.locator("#form-message")).to_have_text("Please enter a title.")
        expect(page.get_by_label("Body")).to_have_value("keep me")
        expect(page.get_by_label("Tags")).to_have_value("a,b")
    assert posts == []
    assert _count(live_server) == 0
    expect(page.locator("#notes li")).to_have_count(0)


def test_save_is_the_only_click(page: Page, live_server: str) -> None:
    page.goto(live_server)
    page.evaluate(
        "window.clicks = 0; document.addEventListener('click', () => window.clicks++, true)"
    )
    _fill(page, "One click")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("#notes li")).to_have_count(1)
    assert page.evaluate("window.clicks") <= 3


def test_service_errors_keep_text_and_add_nothing(page: Page, live_server: str) -> None:
    page.goto(live_server)
    expect(page.get_by_label("Title")).to_have_attribute("maxlength", "200")

    def fail(status: int) -> Callable[[Route], None]:
        def handler(route: Route) -> None:
            route.fulfill(status=status, json={"detail": "secret-detail"})

        return handler

    cases = {500: "The action did not succeed.", 422: "Please enter a title of at most 200"}
    for status, text in cases.items():
        page.route("**/notes", fail(status))
        _fill(page, "Keep", "body text", "x")
        page.get_by_role("button", name="Save").click()
        message = page.locator("#form-message")
        expect(message).to_contain_text(text)
        expect(message).not_to_contain_text(str(status))
        expect(message).not_to_contain_text("secret-detail")
        expect(page.get_by_label("Title")).to_have_value("Keep")
        expect(page.get_by_label("Body")).to_have_value("body text")
        expect(page.get_by_role("button", name="Save")).to_be_enabled()
        expect(page.locator("#notes li")).to_have_count(0)
        page.unroute("**/notes")
    assert _count(live_server) == 0


def test_html_is_shown_literally(page: Page, live_server: str) -> None:
    page.goto(live_server)
    _fill(page, "<b>bold</b>", '<img src=x onerror="window.pwned=1">', "<i>t</i>")
    page.get_by_role("button", name="Save").click()
    row = page.locator("#notes li")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("<b>bold</b>")
    expect(row).to_contain_text('<img src=x onerror="window.pwned=1">')
    expect(row).to_contain_text("<i>t</i>")
    assert page.locator("#notes b, #notes img, #notes i").count() == 0
