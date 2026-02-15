#!/bin/python3

# fast api
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from thedig.__about__ import __author__, __copyright__, __email__, __license__, __summary__, __title__, __version__
from thedig.api import ar, router
from thedig.api.config import settings, setup_cache

# import other apis
from thedig.api.logsetup import setup_logger_from_settings
from thedig.security import get_api_key


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logger_from_settings(log_level=settings.log_level)
    ar.cache = await setup_cache(settings, db=settings.cache_redis_db_person)
    ar.cache_expiration = settings.cache_expiration_person

    await FastAPILimiter.init(await setup_cache(settings, db=settings.cache_redis_db))
    yield


# routing composition
app = FastAPI(
    debug=bool(settings.log_level == "DEBUG"),
    title=__title__,
    summary=__summary__,
    version=__version__,
    contact={"name": f"{__author__} - {__copyright__}", "email": __email__},
    license_info={"name": __license__},
    dependencies=[
        Security(get_api_key),
        Depends(RateLimiter(times=settings.max_requests_times, seconds=settings.max_requests_seconds)),
    ],
    lifespan=lifespan,
    terms_of_service="https://github.com/ankaboot-source/thedig/",
    openapi_tags=[
        {
            "name": "archaeology",
            "description": "🧩➜👤 enrich __iteratively__ data,\
                every enriched data could be potentially used to excavator more data",
        },
        {
            "name": "person",
            "description": "Enrich **person**",
        },
        {
            "name": "company",
            "description": "Extract **company** related info.",
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
)

app.include_router(router)
