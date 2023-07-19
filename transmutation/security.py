"""
Security
"""
import secrets

__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"
__version__ = "0.1"

# fast api
from fastapi import (
    Security,
    WebSocketException,
    status,
    Cookie,
    Query,
    WebSocket,
    Request,
)
from fastapi.exceptions import HTTPException
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from transmutation.api.config import settings

from typing import Annotated


# logging modules
from loguru import logger as log


class UniversalAPIKeyHeader(APIKeyQuery):
    async def __call__(self, request: Request = None, websocket: WebSocket = None):
        request = request or websocket
        if not request:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated"
                )
            return None
        return await super().__call__(request)


# X-API-KEY protection
api_key_header_auth = UniversalAPIKeyHeader(
    name=settings.api_key_name,
    description="Mandatory API Token, required for all endpoints",
)


async def get_api_key(api_key_header: str = Security(api_key_header_auth)):
    log.debug(f"Checking API Key authentication: {api_key_header}")
    if not any(
        secrets.compare_digest(api_key_header, api_key_v)
        for api_key_v in settings.api_keys
    ):
        log.debug(f"Invalid API Key {api_key_header}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )


async def websocket_api_key(
    websocket: WebSocket,
    session: Annotated[str | None, Cookie()] = None,
    token: Annotated[str | None, Query()] = None,
):
    if token:
        api_key = token.get(settings.api_key_name)
    elif session:
        api_key = session.get(settings.api_key_name)

    log.debug(f"Websocket - Checking API Key authentication: {api_key}")
    if session is None and token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    if not any(
        secrets.compare_digest(api_key, api_key_v) for api_key_v in settings.api_keys
    ):
        log.debug(f"Invalid API Key {api_key}")
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
