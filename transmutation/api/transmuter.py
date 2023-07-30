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
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import WebSocket, WebSocketDisconnect, WebSocketException

# websocket manager
from .websocketmanager import manager as ws_manager

# types
from pydantic import EmailStr
from typing import Set, Annotated

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

# init cache for transmuter
cache = setup_cache(settings, 7)

al = Alchemist()


@al.register(element="name")
async def miner_linkedin(p: dict):
    miner = LinkedInSearch(search_api_params)
    person = await miner.search(
        name=p["name"], email=p.get("email"), company=p.get("worksFor")
    )
    return person


@al.register(element="email", update=("image",))
async def miner_gravatar(p: dict):
    p_new = {}
    avatar = await gravatar(p["email"])
    if avatar:
        p_new["image"] = avatar
    return p_new


@al.register(element="email")
async def mine_social(p: dict):
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
    log.debug(f"{snm._person}, {snm.profiles}")

    if "OptOut" in snm.person:
        return None

    return snm.person


@al.register(element="email", update=("worksFor",))
async def mine_worksfor(p: dict):
    # otherwise, the domain will give us the @org
    # except for public email providers
    if "worksFor" not in p:
        domain = p["email"].split("@")[1]
        if domain not in settings.public_email_providers:
            company = cache.get(domain)
            if not company:
                company = get_company(domain)
                # redis refuses to store None so we'll use a void string instead
                # we won't check for this domain again for some time
                cache.set(domain, company or "", ex=settings.cache_expiration)
            if company:
                p["worksFor"] = company
                return p


@al.register(element="description", update=("jobTitle",))
async def mine_bio(p: dict):
    if "description" not in p:
        return None

    if type(p["description"]) is str:
        desc = (p["description"],)
    else:
        desc = p["description"]

    jt = set()
    for d in desc:
        jobtitle = find_jobtitle(d)
        if jobtitle:
            jt |= jobtitle

    if not jt:
        return None

    return {"jobTitle": jt}


@al.register(element="name", update=("givenName", "familyName"))
async def mine_name(p: dict):
    splitted = split_fullname(p["name"], p["email"].split("@")[1])
    log.debug(splitted)
    return splitted


@al.register(element="email", insert=("location",))
async def mine_country(p: dict):
    country = guess_country(p["email"].split("@")[-1])
    return {"location": country} if country else None


@router.get("/transmute/{email}")
async def transmute_one(email: EmailStr, name: str) -> dict:
    al_status, transmuted = await al.person({"email": email, "name": name})
    if not al_status:
        raise HTTPException(
            status_code=404, detail="No result for this person")
    return transmuted


@router.websocket("/transmute/{user_id}/websocket")
async def websocket_endpoint(websocket: WebSocket, user_id: int, q: int | None = None):
    await ws_manager.connect(websocket)
    transmuted_count = 0
    log.info(f"Websocket connected: {websocket} - {user_id}")

    try:
        while True:
            # Wait for any message from the client
            try:
                person = await websocket.receive_json()
            except json.JSONDecodeError as e:
                log.debug(f"JSON malformed: {e}")
                raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA)

            al_status = None

            # person_c = cache.get(f"{user_id}-{person['email']}")
            # person_c = None
            # if person_c:
            #    al_status = True
            #    person = dict(**json.loads(person_c))
            #    log.debug(f"{person['email']} found: {person_c}")
            # aqueue.put(person)
            # al_status, transmuted = await al.person(await aqueue.get())

            # data validation
            try:
                uid, person = person.popitem()
            except:
                log.debug(f"invalid data: {person}")
                raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA)

            al_status, transmuted = await al.person(person)

            if al_status:
                # cache.set(f"{user_id}-{person['email']}", transmuted.json(), ex=settings.cache_expiration)
                transmuted_count += 1

            # Send message when transmutation finished
            await websocket.send_text(
                f"['{uid}': {{'status': {al_status}, 'person': {transmuted}}}]"
            )

    except WebSocketDisconnect:
        log.info(f"Websocket disconnected: {websocket}")
        ws_manager.disconnect(websocket)
