#!/bin/python3
"""
Microservices for data enrichment :
- /linkedin (JSON-LD schema.org format): full name and email -> 
  fist name, last name, title, company, location, image, linkedin URL
- /whoiscompany : list of domains -> dict of domain : company name
- /emailvalidation : list of emails address -> dict of email address : validation status
- /...
- future: /socialprofiles : person (JSON-LD) -> list of social profiles
"""
import secrets
import os

__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"
__version__ = "0.1"

# fast api
from fastapi import FastAPI
from fastapi import Security, status
from fastapi.exceptions import HTTPException
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware

# import other apis
from transmutation.api import router
from transmutation.api.config import settings
from transmutation.api.logsetup import setup_logger_from_settings

# logging modules
import logging
from fastapi.logger import logger

# X-API-KEY protection
api_key_header_auth = APIKeyHeader(
    name=settings.api_key_name,
    description="Mandatory API Token, required for all endpoints",
)


async def get_api_key(api_key_header: str = Security(api_key_header_auth)):
    if not any(
        secrets.compare_digest(api_key_header, api_key_v)
        for api_key_v in settings.api_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )


# routing composition
app = FastAPI(
    title="Transmutation API",
    description=__doc__,
    version=__version__,
    contact={"name": __copyright__, "email": __author__.split("<")[1][:-1]},
    license_info={"name": __license__},
    dependencies=[Security(get_api_key)],
)
# origins = ["http://localhost:"+os.environ.get("PORT", str(settings.server_port))]
app.add_middleware(
    CORSMiddleware,
    #    allow_origins=origins,
    allow_credentials=True,
    #    allow_methods=["*"],
    #    allow_headers=["*"],
)

app.include_router(router)
setup_logger_from_settings()

# launching this app as a module is for dev purpose
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        port=int(os.environ.get("PORT", settings.server_port)),
        host="0.0.0.0",
        reload=True,
        debug=True,
    )
