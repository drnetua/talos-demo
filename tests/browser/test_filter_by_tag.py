import httpx
from playwright.sync_api import Page, expect

from .conftest import Seed


def _tag_notes(live_server: str, seed: Seed, count: int, tags: list[list[str]]) -> None:
    for note, note_tags in zip(seed(count), tags, strict=True):
        resp = httpx.put(
            f"{live_server}/notes/{note['id']}", json={"title": note["title"], "tags": note_tags}
        )
        resp.raise_for_status()


def _filter_button(page: Page, tag: str):  # type: ignore[no-untyped-def]
    return page.get_by_role("button", name=f"Filter by tag {tag},")


def test_tags_listed_with_counts(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 3, [["a", "b"], ["a"], []])
    page.goto(live_server)
    expect(page.locator("#tags button")).to_have_text(["a (2)", "b (1)"])


def test_select_and_clear(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 3, [["a"], ["b"], ["a"]])
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(3)
    _filter_button(page, "a").click()
    expect(page.locator("#notes li")).to_have_count(2)
    expect(page.locator("#filter-bar")).to_be_visible()
    expect(page.locator("#filter-tag")).to_have_text("a")
    page.get_by_role("button", name="Clear filter").click()
    expect(page.locator("#notes li")).to_have_count(3)
    expect(page.locator("#filter-bar")).to_be_hidden()


def test_load_more_under_filter(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 60, [["a"] if i % 3 else ["b"] for i in range(60)])
    page.goto(live_server)
    _filter_button(page, "a").click()
    expect(page.locator("#notes li")).to_have_count(40)
    expect(page.locator("#load-more")).to_be_hidden()
    _filter_button(page, "b").click()
    expect(page.locator("#notes li")).to_have_count(20)
    page.get_by_role("button", name="Clear filter").click()
    expect(page.locator("#notes li")).to_have_count(50)
    page.locator("#load-more").click()
    expect(page.locator("#notes li")).to_have_count(60)
    ids = page.locator("#notes li").evaluate_all("els => els.map(e => e.dataset.id)")
    assert len(set(ids)) == 60


def test_load_more_pages_within_filter(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 55, [["a"] for _ in range(55)])
    page.goto(live_server)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url) if "/notes?" in r.url else None)
    _filter_button(page, "a").click()
    expect(page.locator("#notes li")).to_have_count(50)
    page.locator("#load-more").click()
    expect(page.locator("#notes li")).to_have_count(55)
    assert "cursor" not in requests[0] and "tag=a" in requests[0]
    assert "tag=a" in requests[1] and "cursor=" in requests[1]


def test_special_character_tags(page: Page, live_server: str, seed: Seed) -> None:
    special = ["a/b", "c#d", "e&f", "g+h", "ünï"]
    _tag_notes(live_server, seed, 6, [[t] for t in special] + [[]])
    page.goto(live_server)
    for tag in special:
        _filter_button(page, tag).click()
        expect(page.locator("#filter-tag")).to_have_text(tag)
        expect(page.locator("#notes li")).to_have_count(1)
        expect(page.locator("#notes li .tag")).to_have_text([tag])


def test_click_count(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 2, [["a"], ["b"]])
    page.goto(live_server)
    expect(page.locator("#notes li")).to_have_count(2)
    page.evaluate(
        "window.clicks = 0; document.addEventListener('click', () => window.clicks++, true)"
    )
    _filter_button(page, "a").click()
    expect(page.locator("#notes li")).to_have_count(1)
    assert page.evaluate("window.clicks") <= 3


def _remove_tag(page: Page, row_index: int, tag: str) -> None:
    page.locator("#notes li").nth(row_index).get_by_role("button", name=f"Remove tag {tag}").click()


def test_remove_filtered_tag_drops_note(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 2, [["a", "b"], ["a"]])
    page.goto(live_server)
    _filter_button(page, "a").click()
    expect(page.locator("#notes li")).to_have_count(2)
    _remove_tag(page, 0, "a")
    expect(page.locator("#notes li")).to_have_count(1)
    expect(page.locator("#tags button")).to_have_text(["a (1)", "b (1)"])


def test_remove_last_use_clears_filter(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 2, [["a"], ["b"]])
    page.goto(live_server)
    _filter_button(page, "a").click()
    expect(page.locator("#notes li")).to_have_count(1)
    _remove_tag(page, 0, "a")
    expect(page.locator("#filter-bar")).to_be_hidden()
    expect(page.locator("#notes li")).to_have_count(2)
    expect(page.locator("#tags button")).to_have_text(["b (1)"])


def test_add_other_tag_keeps_note(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 1, [["a"]])
    page.goto(live_server)
    _filter_button(page, "a").click()
    row = page.locator("#notes li").first
    row.get_by_label("New tag").fill("c")
    row.get_by_role("button", name="Add tag").click()
    expect(page.locator("#notes li")).to_have_count(1)
    expect(page.locator("#tags button")).to_have_text(["a (1)", "c (1)"])


def test_counts_after_create_edit_delete(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 1, [["a"]])
    page.goto(live_server)
    page.locator("#note-title").fill("new")
    page.locator("#note-tags").fill("a, z")
    page.locator("#save").click()
    expect(page.locator("#tags button")).to_have_text(["a (2)", "z (1)"])
    new_row = page.locator("#notes li", has_text="new")
    new_row.get_by_role("button", name="Edit").click()
    page.locator("#edit-tags").fill("a")
    page.locator("#edit-save").click()
    expect(page.locator("#tags button")).to_have_text(["a (2)"])
    new_row.get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").click()
    expect(page.locator("#tags button")).to_have_text(["a (1)"])


def test_empty_filtered_message(page: Page, live_server: str, seed: Seed) -> None:
    _tag_notes(live_server, seed, 2, [["a", "b"], ["a"]])
    page.goto(live_server)
    _filter_button(page, "b").click()
    expect(page.locator("#notes li")).to_have_count(1)
    page.locator("#note-title").fill("other")
    page.locator("#save").click()
    expect(page.locator("#notes li")).to_have_count(1)
