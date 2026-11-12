from collections.abc import Callable

import httpx
from playwright.sync_api import Dialog, Page, Route, expect

from .conftest import Seed


def _open(page: Page, live_server: str, seed: Seed) -> int:
    note_id = int(str(seed(2)[0]["id"]))
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(2)
    page.locator("#notes li").first.get_by_role("button", name="Edit").click()
    expect(page.locator("#edit-form")).to_be_visible()
    return note_id


def test_edit_and_save_updates_row_without_reload(
    page: Page, live_server: str, seed: Seed
) -> None:
    note_id = _open(page, live_server, seed)
    page.evaluate("window.marker = 1")
    expect(page.locator("#edit-title")).to_have_value("note 0")
    page.locator("#edit-title").fill("  New title ")
    page.locator("#edit-body").fill("new body")
    page.locator("#edit-tags").fill("Alpha, beta,,")
    page.locator("#edit-save").click()
    expect(page.locator("#edit-form")).to_be_hidden()
    row = page.locator("#notes li").first
    expect(row.locator(".note-title")).to_have_text("New title")
    expect(row.locator(".note-body")).to_have_text("new body")
    expect(row.locator(".tag")).to_have_text(["alpha", "beta"])
    assert page.evaluate("window.marker") == 1
    stored = httpx.get(f"{live_server}/notes/{note_id}").json()
    assert stored["title"] == "New title"
    assert stored["body"] == "new body"
    assert stored["tags"] == ["alpha", "beta"]


def test_empty_title_sends_no_put(page: Page, live_server: str, seed: Seed) -> None:
    puts: list[str] = []
    page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" else None)
    note_id = _open(page, live_server, seed)
    page.locator("#edit-title").fill("   ")
    page.locator("#edit-save").click()
    expect(page.locator("#edit-message")).to_have_text("Please enter a title.")
    assert puts == []
    assert httpx.get(f"{live_server}/notes/{note_id}").json()["title"] == "note 0"


def test_open_and_save_take_at_most_three_clicks(
    page: Page, live_server: str, seed: Seed
) -> None:
    seed(1)
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(1)
    page.evaluate(
        "window.clicks = 0; document.addEventListener('click', () => window.clicks++, true)"
    )
    page.get_by_role("button", name="Edit").click()
    page.locator("#edit-title").fill("Changed")
    page.locator("#edit-save").click()
    expect(page.locator("#notes li .note-title")).to_have_text("Changed")
    assert page.evaluate("window.clicks") <= 3


def test_errors_keep_text_and_hide_details(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _open(page, live_server, seed)

    def fail(status: int) -> Callable[[Route], None]:
        def handler(route: Route) -> None:
            if route.request.method == "PUT":
                route.fulfill(status=status, json={"detail": "secret-detail"})
            else:
                route.continue_()

        return handler

    page.locator("#edit-title").fill("Keep")
    page.locator("#edit-body").fill("body text")
    page.locator("#edit-tags").fill("x")
    for status, text in {500: "did not succeed", 422: "Please enter a title"}.items():
        page.route("**/notes/*", fail(status))
        page.locator("#edit-save").click()
        message = page.locator("#edit-message")
        expect(message).to_contain_text(text)
        expect(message).not_to_contain_text(str(status))
        expect(message).not_to_contain_text("secret-detail")
        expect(page.locator("#edit-title")).to_have_value("Keep")
        expect(page.locator("#edit-body")).to_have_value("body text")
        expect(page.locator("#edit-tags")).to_have_value("x")
        expect(page.locator("#edit-save")).to_be_enabled()
        page.unroute("**/notes/*")
    page.route("**/notes/*", fail(404))
    page.locator("#edit-save").click()
    expect(page.locator("#message")).to_have_text("This note no longer exists")
    expect(page.locator("#notes li")).to_have_count(1)
    page.unroute("**/notes/*")
    assert httpx.get(f"{live_server}/notes/{note_id}").json()["title"] == "note 0"


def test_close_returns_to_list(page: Page, live_server: str, seed: Seed) -> None:
    _open(page, live_server, seed)
    page.locator("#edit-title").fill("discarded")
    page.get_by_role("button", name="Close").click()
    page.get_by_role("button", name="Discard edits").click()
    expect(page.locator("#edit-form")).to_be_hidden()
    expect(page.locator("#notes li")).to_have_count(2)
    expect(page.locator("#notes li .note-title").first).to_have_text("note 0")


def _dirty_close(page: Page, live_server: str, seed: Seed) -> int:
    note_id = _open(page, live_server, seed)
    page.locator("#edit-title").fill("typed title")
    page.locator("#edit-body").fill("typed body")
    page.locator("#edit-tags").fill("a, b")
    page.get_by_role("button", name="Close").click()
    return note_id


def test_dirty_close_asks_to_confirm(page: Page, live_server: str, seed: Seed) -> None:
    _dirty_close(page, live_server, seed)
    confirm = page.locator("#discard-confirm")
    expect(confirm).to_be_visible()
    expect(confirm).to_have_attribute("role", "alertdialog")
    expect(confirm.get_by_role("button", name="Keep editing")).to_be_visible()
    expect(confirm.get_by_role("button", name="Discard edits")).to_be_visible()
    expect(page.locator("#edit-form")).to_be_visible()


def test_keep_editing_preserves_fields(page: Page, live_server: str, seed: Seed) -> None:
    _dirty_close(page, live_server, seed)
    page.get_by_role("button", name="Keep editing").click()
    expect(page.locator("#discard-confirm")).to_be_hidden()
    expect(page.locator("#edit-form")).to_be_visible()
    expect(page.locator("#edit-title")).to_have_value("typed title")
    expect(page.locator("#edit-body")).to_have_value("typed body")
    expect(page.locator("#edit-tags")).to_have_value("a, b")


def test_discard_edits_closes_and_keeps_note(page: Page, live_server: str, seed: Seed) -> None:
    note_id = _dirty_close(page, live_server, seed)
    page.get_by_role("button", name="Discard edits").click()
    expect(page.locator("#edit-form")).to_be_hidden()
    expect(page.locator("#discard-confirm")).to_be_hidden()
    expect(page.locator("#notes li .note-title").first).to_have_text("note 0")
    assert httpx.get(f"{live_server}/notes/{note_id}").json()["title"] == "note 0"


def test_clean_close_asks_nothing(page: Page, live_server: str, seed: Seed) -> None:
    _open(page, live_server, seed)
    page.get_by_role("button", name="Close").click()
    expect(page.locator("#edit-form")).to_be_hidden()
    expect(page.locator("#discard-confirm")).to_be_hidden()


def test_reverting_to_original_values_asks_nothing(
    page: Page, live_server: str, seed: Seed
) -> None:
    _open(page, live_server, seed)
    page.locator("#edit-title").fill("changed")
    page.locator("#edit-title").fill("note 0")
    page.get_by_role("button", name="Close").click()
    expect(page.locator("#edit-form")).to_be_hidden()
    expect(page.locator("#discard-confirm")).to_be_hidden()


def test_opening_another_note_is_guarded(page: Page, live_server: str, seed: Seed) -> None:
    _open(page, live_server, seed)
    page.locator("#edit-title").fill("unsaved")
    page.locator("#notes li").nth(1).get_by_role("button", name="Edit").click()
    expect(page.locator("#discard-confirm")).to_be_visible()
    expect(page.locator("#edit-title")).to_have_value("unsaved")
    page.get_by_role("button", name="Discard edits").click()
    expect(page.locator("#edit-title")).to_have_value("note 1")
    expect(page.locator("#discard-confirm")).to_be_hidden()


def test_save_resets_baseline(page: Page, live_server: str, seed: Seed) -> None:
    _open(page, live_server, seed)
    page.locator("#edit-title").fill("saved")
    page.locator("#edit-save").click()
    expect(page.locator("#edit-form")).to_be_hidden()
    page.locator("#notes li").first.get_by_role("button", name="Edit").click()
    page.get_by_role("button", name="Close").click()
    expect(page.locator("#edit-form")).to_be_hidden()
    expect(page.locator("#discard-confirm")).to_be_hidden()


def test_beforeunload_only_when_dirty(page: Page, live_server: str, seed: Seed) -> None:
    _open(page, live_server, seed)
    page.locator("#edit-title").fill("unsaved")
    types: list[str] = []

    def on_dialog(dialog: Dialog) -> None:
        types.append(dialog.type)
        dialog.dismiss()

    page.on("dialog", on_dialog)
    with page.expect_event("dialog"):
        page.close(run_before_unload=True)
    assert types == ["beforeunload"]
    assert not page.is_closed()


def test_no_beforeunload_when_clean(page: Page, live_server: str, seed: Seed) -> None:
    _open(page, live_server, seed)
    types: list[str] = []

    def on_dialog(dialog: Dialog) -> None:
        types.append(dialog.type)
        dialog.dismiss()

    page.on("dialog", on_dialog)
    with page.expect_event("close"):
        page.close(run_before_unload=True)
    assert types == []
