import httpx
from playwright.sync_api import Page, Route, expect

from .conftest import Seed


def _load(page: Page, live_server: str, seed: Seed) -> int:
    note_id = int(str(seed(2)[0]["id"]))
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(2)
    return note_id


def _track_deletes(page: Page) -> list[str]:
    deletes: list[str] = []
    page.on("request", lambda r: deletes.append(r.url) if r.method == "DELETE" else None)
    return deletes


def test_confirm_removes_row_and_note(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _load(page, live_server, seed)
    page.evaluate("window.marker = 1")
    page.locator("#notes li").first.get_by_role("button", name="Delete").click()
    expect(page.locator("#delete-confirm")).to_be_visible()
    page.locator("#confirm-delete").click()
    expect(page.locator("#notes li")).to_have_count(1)
    expect(page.locator("#delete-confirm")).to_be_hidden()
    assert page.evaluate("window.marker") == 1
    assert httpx.get(f"{live_server}/notes/{note_id}").status_code == 404


def test_cancel_and_escape_keep_note(page: Page, live_server: str, seed: Seed) -> None:
    deletes = _track_deletes(page)
    note_id = _load(page, live_server, seed)
    delete = page.locator("#notes li").first.get_by_role("button", name="Delete")
    delete.click()
    page.locator("#cancel-delete").click()
    expect(page.locator("#delete-confirm")).to_be_hidden()
    delete.click()
    expect(page.locator("#delete-confirm")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#delete-confirm")).to_be_hidden()
    expect(page.locator("#notes li")).to_have_count(2)
    assert deletes == []
    assert httpx.get(f"{live_server}/notes/{note_id}").status_code == 200


def test_delete_alone_sends_no_request(page: Page, live_server: str, seed: Seed) -> None:
    deletes = _track_deletes(page)
    note_id = _load(page, live_server, seed)
    page.locator("#notes li").first.get_by_role("button", name="Delete").click()
    expect(page.locator("#delete-confirm")).to_be_visible()
    assert deletes == []
    assert httpx.get(f"{live_server}/notes/{note_id}").status_code == 200


def test_delete_takes_at_most_two_clicks(page: Page, live_server: str, seed: Seed) -> None:
    seed(1)
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(1)
    page.evaluate(
        "window.clicks = 0; document.addEventListener('click', () => window.clicks++, true)"
    )
    page.get_by_role("button", name="Delete", exact=True).click()
    page.locator("#confirm-delete").click()
    expect(page.locator("#notes li")).to_have_count(0)
    assert page.evaluate("window.clicks") <= 2


def test_404_removes_row_with_message(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _load(page, live_server, seed)
    httpx.delete(f"{live_server}/notes/{note_id}")
    page.locator("#notes li").first.get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").click()
    expect(page.locator("#notes li")).to_have_count(1)
    expect(page.locator("#message")).to_have_text("This note no longer exists")


def test_server_error_keeps_row(page: Page, live_server: str, seed: Seed) -> None:
    def fail(route: Route) -> None:
        route.fulfill(status=500, body="boom")

    page.route("**/notes/*", lambda r: fail(r) if r.request.method == "DELETE" else r.fallback())
    note_id = _load(page, live_server, seed)
    page.locator("#notes li").first.get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").click()
    expect(page.locator("#message")).to_have_text("The action did not succeed.")
    expect(page.locator("#notes li")).to_have_count(2)
    assert "500" not in page.locator("#message").inner_text()
    assert httpx.get(f"{live_server}/notes/{note_id}").status_code == 200


def test_network_failure_keeps_row(page: Page, live_server: str, seed: Seed) -> None:
    page.route(
        "**/notes/*",
        lambda r: r.abort() if r.request.method == "DELETE" else r.fallback(),
    )
    _load(page, live_server, seed)
    page.locator("#notes li").first.get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").click()
    expect(page.locator("#message")).to_have_text("The service is unavailable.")
    expect(page.locator("#notes li")).to_have_count(2)
