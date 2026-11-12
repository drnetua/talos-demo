import csv
import io
import json

from fastapi.testclient import TestClient

from notes.app import EXPORT_FIELDS, create_app
from notes.db import Database


def client() -> TestClient:
    return TestClient(create_app(Database(":memory:")))


def rows(response: TestClient) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(response.text)))


def assert_download(response: TestClient) -> None:
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert response.headers["Content-Disposition"] == 'attachment; filename="notes.csv"'
    assert response.headers["Cache-Control"] == "no-store"
    assert not response.content.startswith(b"\xef\xbb\xbf")


def test_all_notes_and_duplicate_fields_in_canonical_order() -> None:
    c = client()
    for number in range(105):
        tag = "even" if number % 2 == 0 else "odd"
        c.post("/notes", json={"title": f"Note {number}", "tags": [tag]})
    reversed_fields = list(reversed(EXPORT_FIELDS))
    for query in (
        {"fields": reversed_fields + ["title", "id"]},
        {"fields": EXPORT_FIELDS, "tag": ""},
    ):
        response = c.get("/notes/export", params=query)
        assert_download(response)
        parsed = rows(response)
        assert response.text.splitlines()[0] == ",".join(EXPORT_FIELDS)
        assert len(parsed) == 105
        assert [int(row["id"]) for row in parsed] == list(range(1, 106))
        assert parsed[104]["title"] == "Note 104"
        assert json.loads(parsed[0]["tags"]) == ["even"]


def test_single_tag_and_selected_fields_without_trimming() -> None:
    c = client()
    c.post("/notes", json={"title": "Work", "tags": ["Work", "Planning"]})
    c.post("/notes", json={"title": "Personal", "tags": ["home"]})
    multi = c.get("/notes/export", params={"tag": "WORK", "fields": ["title", "id", "tags"]})
    assert rows(multi) == [{"id": "1", "title": "Work", "tags": '["planning","work"]'}]
    one = c.get("/notes/export", params={"tag": "home", "fields": "title"})
    assert rows(one) == [{"title": "Personal"}]
    for tag in (" work ", "work\n", " home"):
        response = c.get("/notes/export", params={"tag": tag, "fields": "title"})
        assert response.text == "title\r\n"


def test_invalid_fields_and_repeated_tags() -> None:
    c = client()
    queries = [{"fields": ""}, {"fields": "unknown"}, {"fields": "Title"}, {"fields": "id,title"}]
    for query in [{"not_fields": "title"}, *queries]:
        response = c.get("/notes/export", params=query)
        assert response.status_code == 422
        assert "content-disposition" not in response.headers
        assert response.json()["detail"][0]["loc"][:2] == ["query", "fields"]
        assert response.json()["detail"][0]["msg"]
    response = c.get("/notes/export?fields=id&tag=one&tag=two")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "tag"]
    assert "content-disposition" not in response.headers


def test_empty_database_and_unmatched_tag_have_heading_only() -> None:
    c = client()
    for query in ({"fields": "title"}, {"fields": "id", "tag": "unmatched"}):
        response = c.get("/notes/export", params=query)
        assert_download(response)
        assert response.text == next(iter(query.values())) + "\r\n"
        assert rows(response) == []


def test_export_schema_and_static_route_precedence() -> None:
    c = client()
    note = c.post("/notes", json={"title": "Alpha", "body": "first"}).json()
    operation = c.get("/openapi.json").json()["paths"]["/notes/export"]["get"]
    assert operation["operationId"] == "export-notes"
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    fields = parameters["fields"]
    assert fields["required"] and fields.get("style", "form") == "form"
    assert fields.get("explode", True)
    assert fields["schema"]["type"] == "array"
    assert fields["schema"]["minItems"] == 1
    assert fields["schema"]["items"]["enum"] == list(EXPORT_FIELDS)
    assert not parameters["tag"]["required"]
    assert {"type": "string"} in parameters["tag"]["schema"]["anyOf"]
    assert {"type": "null"} in parameters["tag"]["schema"]["anyOf"]
    assert "text/csv" in operation["responses"]["200"]["content"]
    assert "application/json" in operation["responses"]["422"]["content"]
    assert_download(c.get("/notes/export", params={"fields": "title"}))
    assert c.get(f"/notes/{note['id']}").json()["title"] == "Alpha"
    assert [item["title"] for item in c.get("/notes/search?q=first").json()] == ["Alpha"]


def test_openapi_documents_export_failure() -> None:
    spec = client().get("/openapi.json").json()
    responses = spec["paths"]["/notes/export"]["get"]["responses"]
    assert responses["500"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ExportErrorResponse"
    }
    assert {"200", "422"} <= set(responses)


FORMULAS = ["=1+1", "+1+1", "-1+1", "@SUM(1,1)", " =1+1", "\t=1+1", "\r=1+1"]


def test_formula_like_cells_get_one_marker_and_stored_notes_are_unchanged() -> None:
    c = client()
    for value in FORMULAS:
        c.post("/notes", json={"title": value, "body": value, "tags": ["t"]})
    before = (c.get("/notes").json(), [c.get(f"/notes/{i}").json() for i in range(1, 8)])
    response = c.get("/notes/export", params={"fields": EXPORT_FIELDS})
    assert_download(response)
    parsed = rows(response)
    for value, row in zip(FORMULAS, parsed, strict=True):
        assert row["title"] == "'" + value
        assert row["body"] == "'" + value
        assert row["tags"] == '["t"]'
    after = (c.get("/notes").json(), [c.get(f"/notes/{i}").json() for i in range(1, 8)])
    assert before == after


def test_ordinary_and_special_values_are_faithful() -> None:
    c = client()
    values = [
        "Meeting",
        "\tindented",
        "\nMeeting",
        'a, "quoted"',
        "line1\r\nline2\nx",
        "Привіт 日本 😀",
    ]
    for value in values:
        c.post("/notes", json={"title": value, "body": value})
    c.post("/notes", json={"title": "Empty"})
    c.post("/notes", json={"title": "Multi", "tags": ["b", "a", "c"]})
    parsed = rows(c.get("/notes/export", params={"fields": EXPORT_FIELDS}))
    for value, row in zip(values, parsed, strict=False):
        assert row["title"] == value
        assert row["body"] == value
    assert parsed[len(values)]["body"] == ""
    assert json.loads(parsed[-1]["tags"]) == ["a", "b", "c"]


def test_openapi_describes_safe_text_rule() -> None:
    description = create_app(Database(":memory:")).openapi()["paths"]["/notes/export"]["get"][
        "description"
    ]
    assert "apostrophe" in description
    assert "Stored notes are not changed" in description
