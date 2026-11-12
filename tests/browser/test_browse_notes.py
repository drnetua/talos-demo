import httpx
from playwright.sync_api import Page, expect

from .conftest import Seed


def test_first_page_and_load_more(page: Page, live_server: str, seed: Seed) -> None:
    notes = seed(75)
    page.goto(live_server)
    rows = page.locator("#notes li")
    expect(rows).to_have_count(50)
    ids = [int(i) for i in rows.evaluate_all("els => els.map(e => e.dataset.id)")]
    assert ids == [n["id"] for n in notes[:50]]
    page.get_by_role("button", name="Load more").click()
    expect(rows).to_have_count(75)
    ids = [int(i) for i in rows.evaluate_all("els => els.map(e => e.dataset.id)")]
    assert ids == [n["id"] for n in notes]
    assert len(set(ids)) == 75
    expect(page.get_by_role("button", name="Load more")).to_be_hidden()


def test_note_created_between_loads_not_duplicated(
    page: Page, live_server: str, seed: Seed
) -> None:
    seed(60)
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(50)
    httpx.post(f"{live_server}/notes", json={"title": "late"}).raise_for_status()
    page.get_by_role("button", name="Load more").click()
    expect(page.locator("#notes li")).to_have_count(61)
    ids = page.locator("#notes li").evaluate_all("els => els.map(e => e.dataset.id)")
    assert len(set(ids)) == len(ids)


def test_html_is_shown_literally(page: Page, live_server: str) -> None:
    title = "<b>bold</b>"
    body = '<img src=x onerror="window.pwned=1">'
    httpx.post(
        f"{live_server}/notes", json={"title": title, "body": body, "tags": ["<b>t</b>"]}
    ).raise_for_status()
    page.goto(live_server)
    row = page.locator("#notes li")
    expect(row).to_have_count(1)
    expect(row).to_contain_text(title)
    expect(row).to_contain_text(body)
    expect(row).to_contain_text("<b>t</b>")
    assert page.locator("#notes b, #notes img").count() == 0


def test_empty_store(page: Page, live_server: str) -> None:
    page.goto(live_server)
    expect(page.get_by_text("No notes yet")).to_be_visible()
    expect(page.get_by_role("button", name="Load more")).to_be_hidden()
