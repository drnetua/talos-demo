from playwright.sync_api import Page


def test_openapi_is_served(page: Page, live_server: str) -> None:
    response = page.goto(f"{live_server}/openapi.json")
    assert response is not None
    assert response.status == 200
