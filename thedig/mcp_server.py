from __future__ import annotations

import os
import re
from http import HTTPStatus

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import EmailStr, TypeAdapter

EMAIL_ADAPTER = TypeAdapter(EmailStr)
NAME_SEPARATOR_RE = re.compile(r"[._+\-]+")

mcp = FastMCP("TheDig")


def infer_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0].strip()
    tokens = [token for token in NAME_SEPARATOR_RE.split(local_part) if token]
    alphabetic_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
    parts = alphabetic_tokens or tokens or ["Contact"]
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def load_settings() -> dict[str, str | float | None]:
    return {
        "api_base_url": os.getenv("THEDIG_API_BASE_URL", "http://localhost:8080").rstrip("/"),
        "api_key": os.getenv("THEDIG_API_KEY"),
        "api_key_header": os.getenv("THEDIG_API_KEY_HEADER", "X-API-KEY"),
        "timeout": float(os.getenv("THEDIG_MCP_TIMEOUT", "30")),
    }


def response_to_result(response: httpx.Response, used_name: str) -> dict[str, object]:
    if response.status_code == HTTPStatus.NO_CONTENT:
        return {
            "status": "no_data",
            "used_name": used_name,
            "person": None,
        }

    if response.status_code == HTTPStatus.OK:
        return {
            "status": "enriched",
            "used_name": used_name,
            "person": response.json(),
        }

    if response.status_code == HTTPStatus.NON_AUTHORITATIVE_INFORMATION:
        return {
            "status": "partial",
            "used_name": used_name,
            "person": response.json(),
        }

    detail: object
    try:
        detail = response.json()
    except ValueError:
        detail = response.text

    message = f"TheDig API returned {response.status_code}: {detail}"
    raise RuntimeError(message)


async def enrich_email_with_thedig(email: str, name: str | None = None) -> dict[str, object]:
    validated_email = str(EMAIL_ADAPTER.validate_python(email))
    used_name = name.strip() if name and name.strip() else infer_name_from_email(validated_email)
    settings = load_settings()

    headers = {"accept": "application/json"}
    if settings["api_key"]:
        headers[str(settings["api_key_header"])] = str(settings["api_key"])

    async with httpx.AsyncClient(base_url=str(settings["api_base_url"]), timeout=float(settings["timeout"])) as client:
        response = await client.post("/person/", json={"email": validated_email, "name": used_name}, headers=headers)

    return response_to_result(response, used_name)


@mcp.tool(name="enrich_person_email")
async def enrich_person_email(email: str, name: str | None = None) -> dict[str, object]:
    return await enrich_email_with_thedig(email=email, name=name)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
