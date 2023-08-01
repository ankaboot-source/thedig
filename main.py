#!/bin/python3
"""
Microservices for data enrichment :
- /linkedin (JSON-LD schema.org format): full name and email ->
  fist name, last name, title, company, location, image, linkedin URL
- /whoiscompany : list of domains -> dict of domain : company name
- /emailvalidation : list of emails address -> dict of validation status
- /...
- future: /socialprofiles : person (JSON-LD) -> list of social profiles
"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"
__version__ = "0.1"

# fast api
from contextlib import asynccontextmanager
from fastapi import FastAPI, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter

# import other apis
from transmutation.api import router
from transmutation.api.config import settings, setup_cache
from transmutation.api.logsetup import setup_logger_from_settings

# X-API-KEY protection
from transmutation.security import get_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger_from_settings()
    await FastAPILimiter.init(await setup_cache(settings, 8))
    yield


# routing composition
app = FastAPI(
    title="Transmutation API",
    description=__doc__,
    version=__version__,
    contact={"name": __copyright__, "email": __author__.split("<")[1][:-1]},
    license_info={"name": __license__},
    dependencies=[Security(get_api_key)],
    lifespan=lifespan,
)


# origins = [f"http://{settings.server}:{settings.server_port}""]
app.add_middleware(
    CORSMiddleware,
    #    allow_origins=origins,
    allow_credentials=True,
)


app.include_router(router)


# launching this app as a module is for dev purpose
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        port=settings.server_port,
        host="0.0.0.0",
        reload=True,
    )
