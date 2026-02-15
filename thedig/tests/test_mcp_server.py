from __future__ import annotations

from http import HTTPStatus

import httpx
import pytest

from thedig.mcp_server import enrich_email_with_thedig, infer_name_from_email, response_to_result


def test_infer_name_from_email():
    assert infer_name_from_email("john.doe@example.com") == "John Doe"
    assert infer_name_from_email("jane_doe+sales@example.com") == "Jane Doe Sales"


def test_response_to_result_no_content():
    response = httpx.Response(HTTPStatus.NO_CONTENT, request=httpx.Request("POST", "http://localhost/person/"))
    result = response_to_result(response, "John Doe")
    assert result == {"status": "no_data", "used_name": "John Doe", "person": None}


@pytest.mark.asyncio
async def test_enrich_email_with_thedig_uses_inferred_name_and_headers(monkeypatch):
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["init_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return httpx.Response(
                HTTPStatus.OK,
                request=httpx.Request("POST", "http://localhost:8080/person/"),
                json={"name": json["name"], "email": json["email"]},
            )

    monkeypatch.setenv("THEDIG_API_KEY", "test-key")
    monkeypatch.setenv("THEDIG_API_KEY_HEADER", "X-API-KEY")
    monkeypatch.setattr("thedig.mcp_server.httpx.AsyncClient", FakeAsyncClient)

    result = await enrich_email_with_thedig("john.doe@example.com")

    assert captured["url"] == "/person/"
    assert captured["json"] == {"email": "john.doe@example.com", "name": "John Doe"}
    assert captured["headers"] == {"accept": "application/json", "X-API-KEY": "test-key"}
    assert result["status"] == "enriched"
