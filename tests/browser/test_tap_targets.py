import httpx
import pytest
from playwright.sync_api import Page, expect

WIDTHS = [320, 375]
MIN_SIZE = 44
_NO_SCROLL = "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"


def _undersized(page: Page) -> list[str]:
    """Describe every visible button, input and textarea smaller than 44 × 44 px."""
    small: list[str] = []
    controls = page.locator("button, input, textarea")
    for i in range(controls.count()):
        control = controls.nth(i)
        if not control.is_visible():
            continue
        box = control.bounding_box()
        assert box is not None
        if box["width"] < MIN_SIZE or box["height"] < MIN_SIZE:
            label = control.evaluate(
                "e => e.id ? '#' + e.id : e.tagName.toLowerCase() + '.' + e.className"
                " + ' \"' + (e.textContent || '').trim() + '\"'"
            )
            small.append(f"{label}: {box['width']:.0f} x {box['height']:.0f}")
    return small


def _check(page: Page, width: int, screen: str) -> None:
    assert _undersized(page) == [], f"{screen} at {width} px"
    if width == 320:
        assert page.evaluate(_NO_SCROLL), f"{screen} scrolls horizontally at 320 px"


def _open(page: Page, live_server: str, width: int) -> None:
    created = httpx.post(f"{live_server}/notes", json={"title": "tapped", "tags": ["alpha"]})
    created.raise_for_status()
    page.set_viewport_size({"width": width, "height": 700})
    page.goto(live_server)
    expect(page.locator("#notes li .tag")).to_have_count(1)
    expect(page.locator("#tags .tag-filter")).to_have_count(1)


@pytest.mark.parametrize("width", WIDTHS)
def test_main_screen_targets(page: Page, live_server: str, width: int) -> None:
    _open(page, live_server, width)
    _check(page, width, "main screen")

    page.locator("#tags .tag-filter").click()
    expect(page.locator("#filter-bar")).to_be_visible()
    _check(page, width, "filter bar")
    page.locator("#clear-filter").click()

    page.locator("#search-input").fill("tapped")
    page.locator("#search-submit").click()
    expect(page.locator("#search-bar")).to_be_visible()
    _check(page, width, "search bar")


@pytest.mark.parametrize("width", WIDTHS)
def test_editor_targets(page: Page, live_server: str, width: int) -> None:
    _open(page, live_server, width)
    page.locator("#notes li").first.get_by_role("button", name="Edit").click()
    expect(page.locator("#edit-form")).to_be_visible()
    _check(page, width, "editor")


@pytest.mark.parametrize("width", WIDTHS)
def test_confirmation_dialog_targets(page: Page, live_server: str, width: int) -> None:
    _open(page, live_server, width)
    row = page.locator("#notes li").first

    row.get_by_role("button", name="Delete").click()
    expect(page.locator("#delete-confirm")).to_be_visible()
    _check(page, width, "delete dialog")
    page.locator("#cancel-delete").click()

    row.get_by_role("button", name="Edit").click()
    page.locator("#edit-title").fill("changed")
    page.locator("#edit-close").click()
    expect(page.locator("#discard-confirm")).to_be_visible()
    _check(page, width, "discard dialog")
