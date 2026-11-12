import httpx
import pytest
from playwright.sync_api import Page, expect


def test_openapi_is_served(page: Page, live_server: str) -> None:
    response = page.goto(f"{live_server}/openapi.json")
    assert response is not None
    assert response.status == 200


_MEASURE = """() => [...document.querySelectorAll('button, input')]
  .filter(e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden')
  .map(e => {
    const r = e.getBoundingClientRect();
    return [e.id || e.className || e.tagName, r.width, r.height];
  })
  .filter(([, w, h]) => w < 44 || h < 44)"""

_NO_SCROLL = "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"


def _assert_targets(page: Page, width: int) -> None:
    assert page.evaluate(_MEASURE) == []
    if width == 320:
        assert page.evaluate(_NO_SCROLL)


@pytest.mark.parametrize("width", [320, 375])
def test_controls_are_at_least_44px(page: Page, live_server: str, width: int) -> None:
    created = httpx.post(f"{live_server}/notes", json={"title": "tapped", "tags": ["alpha"]})
    created.raise_for_status()
    page.set_viewport_size({"width": width, "height": 700})
    page.goto(live_server)
    row = page.locator("#notes li").first
    expect(row.locator(".tag")).to_have_count(1)
    expect(page.locator("#tags .tag-filter")).to_have_count(1)
    _assert_targets(page, width)

    page.locator("#tags .tag-filter").click()
    expect(page.locator("#filter-bar")).to_be_visible()
    _assert_targets(page, width)
    page.locator("#clear-filter").click()

    page.locator("#search-input").fill("tapped")
    page.locator("#search-submit").click()
    expect(page.locator("#search-bar")).to_be_visible()
    _assert_targets(page, width)
    page.locator("#clear-search").click()

    row.get_by_role("button", name="Delete").click()
    expect(page.locator("#delete-confirm")).to_be_visible()
    _assert_targets(page, width)
    page.locator("#cancel-delete").click()

    row.get_by_role("button", name="Edit").click()
    expect(page.locator("#edit-form")).to_be_visible()
    _assert_targets(page, width)
    page.locator("#edit-title").fill("changed")
    page.locator("#edit-close").click()
    expect(page.locator("#discard-confirm")).to_be_visible()
    _assert_targets(page, width)
