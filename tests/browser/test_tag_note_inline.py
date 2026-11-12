from pathlib import Path

import httpx
from playwright.sync_api import Page, Route, expect

from .conftest import Seed


def _load(page: Page, live_server: str, seed: Seed, tags: list[str] | None = None) -> int:
    note_id = int(str(seed(1)[0]["id"]))
    if tags:
        httpx.put(f"{live_server}/notes/{note_id}", json={"title": "note 0", "tags": tags})
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(1)
    return note_id


def _add(page: Page, tag: str) -> None:
    row = page.locator("#notes li").first
    row.get_by_label("New tag").fill(tag)
    row.get_by_role("button", name="Add tag").click()


def _stored(live_server: str, note_id: int) -> list[str]:
    tags: list[str] = httpx.get(f"{live_server}/notes/{note_id}").json()["tags"]
    return tags


def test_add_shows_chip(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _load(page, live_server, seed)
    _add(page, "work")
    expect(page.locator("#notes li .tag")).to_have_text(["work\u00d7"])
    expect(page.locator("#edit-form")).to_be_hidden()
    assert _stored(live_server, note_id) == ["work"]


def test_remove_keeps_other_tags(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _load(page, live_server, seed, ["a", "b"])
    page.get_by_role("button", name="Remove tag a").click()
    expect(page.locator("#notes li .tag")).to_have_count(1)
    assert _stored(live_server, note_id) == ["b"]


def test_special_characters_use_put_body(page: Page, live_server: str, seed: Seed) -> None:
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.method + " " + r.url) if r.method != "GET" else None)
    note_id = _load(page, live_server, seed)
    _add(page, "a/b c")
    expect(page.locator("#notes li .tag")).to_have_count(1)
    _add(page, "ünï #1")
    expect(page.locator("#notes li .tag")).to_have_count(2)
    stored = _stored(live_server, note_id)
    assert "a/b c" in stored and "ünï #1" in stored
    page.get_by_role("button", name="Remove tag a/b c").click()
    expect(page.locator("#notes li .tag")).to_have_count(1)
    page.get_by_role("button", name="Remove tag ünï #1").click()
    expect(page.locator("#notes li .tag")).to_have_count(0)
    assert _stored(live_server, note_id) == []
    assert urls and all(u.startswith("PUT ") and "/tags" not in u for u in urls)


def test_duplicate_keeps_one_copy(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _load(page, live_server, seed, ["work"])
    _add(page, "  WORK ")
    expect(page.locator("#notes li .add-tag-form input")).to_have_value("")
    expect(page.locator("#notes li .tag")).to_have_count(1)
    assert _stored(live_server, note_id) == ["work"]


def test_click_counts(page: Page, live_server: str, seed: Seed) -> None:
    _load(page, live_server, seed, ["x"])
    page.evaluate(
        "window.clicks = 0; document.addEventListener('click', () => window.clicks++, true)"
    )
    row = page.locator("#notes li").first
    row.get_by_label("New tag").fill("y")
    row.get_by_role("button", name="Add tag").click()
    expect(page.locator("#notes li .tag")).to_have_count(2)
    assert page.evaluate("window.clicks") <= 3
    page.evaluate("window.clicks = 0")
    page.get_by_role("button", name="Remove tag y").click()
    expect(page.locator("#notes li .tag")).to_have_count(1)
    assert page.evaluate("window.clicks") <= 1


def _fail_method(page: Page, method: str, abort: bool) -> None:
    def handler(route: Route) -> None:
        if route.request.method != method:
            route.fallback()
        elif abort:
            route.abort()
        else:
            route.fulfill(status=500, body="boom")

    page.route("**/notes/*", handler)


def test_errors_keep_tags(page: Page, live_server: str, seed: Seed) -> None:
    for method, abort in (("GET", True), ("PUT", False), ("PUT", True)):
        _fail_method(page, method, abort)
        note_id = _load(page, live_server, seed, ["keep"])
        _add(page, "new")
        expected = "The action did not succeed." if not abort else "The service is unavailable."
        expect(page.locator("#message")).to_have_text(expected)
        expect(page.locator("#notes li .tag")).to_have_text(["keep\u00d7"])
        assert _stored(live_server, note_id) == ["keep"]
        page.unroute_all()
        httpx.delete(f"{live_server}/notes/{note_id}")


def test_404_removes_row(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _load(page, live_server, seed)
    httpx.delete(f"{live_server}/notes/{note_id}")
    _add(page, "late")
    expect(page.locator("#notes li")).to_have_count(0)
    expect(page.locator("#message")).to_have_text("This note no longer exists")


def test_disabled_while_note_is_open_for_edit(page: Page, live_server: str, seed: Seed) -> None:
    _load(page, live_server, seed, ["a"])
    page.get_by_role("button", name="Edit", exact=True).click()
    expect(page.get_by_label("New tag")).to_be_disabled()
    expect(page.get_by_role("button", name="Remove tag a")).to_be_disabled()
    page.locator("#edit-close").click()
    expect(page.get_by_label("New tag")).to_be_enabled()


def test_remove_control_shows_times_sign(page: Page, live_server: str, seed: Seed) -> None:
    _load(page, live_server, seed, tags=["work"])
    remove = page.locator("#notes li .remove-tag")
    expect(remove).to_have_text("\u00d7")
    assert "\ufffd" not in remove.inner_text()
    before = remove.evaluate("el => getComputedStyle(el, '::before').content")
    assert before in ("none", '""')
    assert remove.get_attribute("aria-label") == "Remove tag work"
    expect(page.get_by_role("button", name="Remove tag work")).to_be_visible()
    css = Path("src/notes/ui/app.css").read_bytes()
    assert b"\x00" not in css
