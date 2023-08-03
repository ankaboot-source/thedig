"""
Security
"""
import secrets

__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"
__version__ = "0.1"

# fast api
from fastapi import Security, status, WebSocket, Request
from fastapi.exceptions import HTTPException
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from transmutation.api.config import settings


# logging modules
from loguru import logger as log


class UniversalAPIKey(APIKeyHeader):
    async def __call__(self, request: Request = None, websocket: WebSocket = None):
        if not request and not websocket:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated"
                )
            return None
        if websocket:
            return await APIKeyQuery.__call__(self, websocket)
        return await super().__call__(request)


# X-API-KEY protection
api_key_header_auth = UniversalAPIKey(
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
