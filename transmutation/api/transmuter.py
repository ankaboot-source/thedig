# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""Transmuter API"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"


# config
import asyncio

from .config import settings
from .config import setup_cache

# fast api
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse, Response
from fastapi import WebSocket, WebSocketDisconnect, WebSocketException
from fastapi_limiter.depends import WebSocketRateLimiter, RateLimiter

# websocket manager
from .websocketmanager import manager as ws_manager

# types
from pydantic import EmailStr, HttpUrl
from .person import Person, PersonRequest, PersonResponse
from .person import person_request_ta, person_response_ta, ValidationError

# logger
from loguru import logger as log

# json
import json

# service
from ..miners.linkedin import LinkedInSearch
from ..miners.whoiscompany import get_company
from ..miners.domainlogo import guess_country
from ..miners.gravatar import gravatar
from ..miners.vision import SocialNetworkMiner
from ..miners.alchemist import Alchemist
from ..miners.splitfullname import split_fullname
from ..miners.bio import find_jobtitle

# init fast api
router = APIRouter()

search_api_params = {
    "google_api_key": settings.google_api_key,
    "google_cx": settings.google_cx,
    "query_type": settings.query_type,
}

MAX_REQUESTS_PER_SEC = {"times": 3, "seconds": 10}

# init cache for transmuter
cache = asyncio.get_event_loop().run_until_complete(setup_cache(settings, 7))


al = Alchemist(router)


@al.register(element="name")
async def miner_linkedin(name: str, email: EmailStr = None, worksFor: str = None) -> Person:
    miner = LinkedInSearch(search_api_params)
    person = await miner.search(name=name, email=email, company=worksFor)
    return person


@al.register(
    element="url",
    update=(
        "worksFor",
        "jobTitle",
        "workLocation",
    ),
    insert=("givenName", "familyName"),
)
async def miner_from_linkedin_url(name: str, url: HttpUrl) -> Person:
    person: Person = {}
    if "linkedin" in p["url"]:
        miner = LinkedInSearch(search_api_params)
        person.update(await miner.search(name=p["name"], linkedin_url=p["url"]))
    return person


@al.register(element="email", update=("image",))
async def miner_gravatar(email) -> Person:
    avatar = await gravatar(email)
    return {'image': avatar} if avatar else {}


@al.register(element="email")
async def mine_social(p: dict) -> Person:
    snm = SocialNetworkMiner(p)

    # if there is an image, let's vision mine it
    # it will ads other social network URLs
    if "image" in p:
        await snm.image()
        pass

    # fuzzy identifier miner
    # it's not an independent miner since identifier can't be mined
    # until confirmed social profiles are found
    await snm.identifier()

    snm.sameAs()

    if "OptOut" in snm.person:
        return {'OptOut': True}

    return snm.person


@al.register(element="email", update=("worksFor",))
async def mine_worksfor(email: EmailStr) -> Person:
    # otherwise, the domain will give us the @org
    # except for public email providers
    domain = email.split("@")[1]
    works_for = {}
    if domain not in settings.public_email_providers:
        company = await cache.get(domain)
        if not company:
            company = get_company(domain)
            # redis refuses to store None so we'll use a void string instead
            # we won't check for this domain again for some time
            await cache.set(domain, company or "", ex=settings.cache_expiration)
        if company:
            works_for['worksFor'] = company
    return works_for


@al.register(element="description", update=("jobTitle",))
async def mine_bio(description: str = None) -> Person:
    desc: set[str] = {
        description,
    }
    job_title = {}
    jt = set()
    for d in desc:
        jobtitle = find_jobtitle(d)
        if jobtitle:
            jt |= jobtitle

    if jt:
        job_title['jobTitle'] = jt

    return job_title


@al.register(element="name", update=("givenName", "familyName"))
async def mine_name(name: str, email: EmailStr) -> Person:
    splitted: Person = split_fullname(name, email.split("@")[1])
    return splitted


@al.register(element="email", insert=("workLocation",))
async def mine_country(email: EmailStr) -> Person:
    country = guess_country(email.split("@")[-1])
    return {"workLocation": country} if country else {}


@router.get("/transmute/{email}", dependencies=[Depends(RateLimiter(**MAX_REQUESTS_PER_SEC))])
async def transmute_email(email: EmailStr, name: str) -> Person:
    al_status, transmuted = await al.person({"email": email, "name": name})
    if not al_status:
        raise HTTPException(status_code=404, detail="No result for this person")
    return transmuted


@router.post("/transmute/{email}", dependencies=[Depends(RateLimiter(**MAX_REQUESTS_PER_SEC))])
async def transmute_person(person: Person) -> Person:
    al_status, transmuted = await al.person({"email": email, "name": name})
    if not al_status:
        raise HTTPException(status_code=404, detail="No result for this person")
    return transmuted


@router.websocket("/transmute/{user_id}/websocket")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await ws_manager.connect(websocket)
    ratelimit = WebSocketRateLimiter(**MAX_REQUESTS_PER_SEC)
    transmuted_count = 0
    log.info(f"Websocket connected: {websocket} - {user_id}")

    try:
        while True:
            # Wait for any message from the client
            await ratelimit(websocket)

            try:
                person: PersonRequest = await websocket.receive_json()
                person_request_ta.validate_python(person)
            except json.JSONDecodeError as e:
                log.debug(f"JSON malformed: {e}")
                raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA)
            except ValidationError:
                log.debug(f"invalid data: {person}")
                raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA)

            al_status = None

            # person_c = cache.get(f"{user_id}-{person['email']}")
            # person_c = None
            # if person_c:
            #    al_status = True
            #    person = dict(**json.loads(person_c))
            #    log.debug(f"{person['email']} found: {person_c}")

            al_status, transmuted = await al.person(person["person"])

            if al_status:
                # cache.set(f"{user_id}-{person['email']}", transmuted.json(), ex=settings.cache_expiration)
                transmuted_count += 1

            response: PersonResponse = {"status": al_status, "person": transmuted}
            person_response_ta.validate_python(response)

            # Send message when transmutation finished
            await ws_manager.message(websocket, {person["uid"]: response})
    except WebSocketDisconnect:
        log.info(f"Websocket disconnected: {websocket}")
        ws_manager.disconnect(websocket)
