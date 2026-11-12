import socket
import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest
import uvicorn

from notes.app import create_app
from notes.db import Database

Seed = Callable[[int], list[dict[str, object]]]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/browser" in item.path.as_posix():
            item.add_marker(pytest.mark.browser)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def live_server() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(
        create_app(Database(":memory:")), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("live server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def seed(live_server: str) -> Seed:
    def _seed(count: int) -> list[dict[str, object]]:
        notes: list[dict[str, object]] = []
        for i in range(count):
            resp = httpx.post(f"{live_server}/notes", json={"title": f"note {i}", "tags": []})
            resp.raise_for_status()
            notes.append(resp.json())
        return notes

    return _seed
