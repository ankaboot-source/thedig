# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""LinkedIn Miner API"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"


# config
import asyncio
from .config import settings
from .config import setup_cache

# fast api
from fastapi import APIRouter, Depends, status
from fastapi import WebSocket, WebSocketDisconnect, WebSocketException
from ..security import websocket_api_key

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
from ..miners.gravatar import gravatar
from ..miners.vision import SocialNetworkMiner
from ..miners.alchemist import Alchemist

# init fast api
router = APIRouter()

search_api_params = {
    "google_api_key": settings.google_api_key,
    "google_cx": settings.google_cx,
    "query_type": settings.query_type,
}

# init cache for transmuter
cache = setup_cache(settings, 7)


@router.get("/transmute/{email}", response_model_exclude_none=True)
def transmute_one(email: EmailStr, name: str) -> dict:
    # first, let's find him on LinkedIn
    miner = LinkedInSearch(search_api_params)
    person = miner.search(name=name, email=email)

    if not person:
        person = dict(email=email, name=name)

    # then if there is no image, let's gravatar it
    if not "image" in person:
        image = gravatar(person["email"])
        if image:
            person["image"] = image

    snm = SocialNetworkMiner(person)

    # fuzzy identifier miner
    snm.identifier()

    # if there is an image, let's vision mine it
    # it will ads other social network URLs
    if "image" in person:
        snm.image()

    # otherwise, the domain will give us the org
    # except for public email providers
    if "worksFor" not in person:
        domain = email.split("@")[1]
        if domain not in settings.public_email_providers:
            company = cache.get(domain)
            if not company:
                company = get_company(domain)
                # redis refuses to store None so we'll use a void string instead
                # we won't check for this domain again for some time
                cache.set(domain, company or "", ex=settings.cache_expiration)
            if company:
                person["worksFor"] = company

    return person


al = Alchemist()

""""
@al.register(element="email")
async def miner_gravatar(p: dict):
    p_new = {}
    avatar = gravatar(p.email)
    if avatar:
        p_new['image'] = avatar
    return p_new


@al.register(element="email")
async def mine_identifier(p: dict):
    return {'identifier': p.email.split('@')[0]}
"""


@al.register(element="email")
async def mine_country(p: dict):
    tld = p["email"].split(".")[-1]
    # tld used generically are irrelevant to guess country
    # exclude = ('io', 're', 'tv', 'sk', 'ly', 'in', 'me', 'sh', 'ws', 'ai', 'cc', 'bz', 'co', 'fm', 'im', 'to', 'am', 'it', 'at', 'mu', 'nu', 'is', 'tk')
    country = "France" if tld == "fr" else ""
    return {"location": country}


@router.websocket("/transmute/{user_id}/websocket")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: int,
    q: int | None = None,
    cookie_or_token: str = Annotated[str, Depends(websocket_api_key)],
):
    await ws_manager.connect(websocket)
    transmuted_count = 0
    log.debug(f"Websocket connected: {websocket}")

    # this async queue is for buffering results
    # aqueue = asyncio.Queue(maxsize=20)

    try:
        while transmuted_count < settings.persons_bulk_max:
            # Wait for any message from the client
            person = await websocket.receive_json()
            al_status = None

            # data validation
            if (
                not type(person) is dict
                or not "email" in person
                or "name" not in person
            ):
                log.debug(f"invalid data: {person}")
                raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA)

            # person_c = cache.get(f"{user_id}-{person['email']}")
            # person_c = None
            # if person_c:
            #    al_status = True
            #    person = dict(**json.loads(person_c))
            #    log.debug(f"{person['email']} found: {person_c}")
            # aqueue.put(person)
            # al_status, transmuted = await al.person(await aqueue.get())

            al_status, transmuted = await al.person(person)

            if al_status:
                # cache.set(f"{user_id}-{person['email']}", transmuted.json(), ex=settings.cache_expiration)
                transmuted_count += 1

            # Send message when transmutation finished
            websocket.send_text(f"[{al_status}, {transmuted.json()}]")

        # reached bulk limit
        log.debug(
            f"limit reached: {transmuted_count}/{settings.persons_bulk_max}")
        raise WebSocketException(code=status.WS_1009_MESSAGE_TOO_BIG)

    except WebSocketDisconnect:
        log.debug(f"Websocket disconnected: {websocket}")
        ws_manager.disconnect(websocket)
