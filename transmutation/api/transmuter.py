# Copyright 2022 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

"""LinkedIn Miner API"""
import redis

__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"


# config
from .config import settings

# fast api
from fastapi import APIRouter, Depends, status
from fastapi import WebSocket, WebSocketDisconnect, WebSocketException
from ..security import websocket_api_key

# Schema.org Person
from pydantic_schemaorg.Person import Person

# types
from pydantic import EmailStr
from typing import Set

# logger
from loguru import logger as log

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

# redis for cache

# init cache for whois
redis_param = {
    setting_k.removeprefix("redis_"): setting_v
    for setting_k, setting_v in settings.dict().items()
    if setting_k.startswith("redis")
}
redis_param["db"] = settings.cache_redis_db
redis_param["decode_responses"] = True
cache = redis.Redis(**redis_param)
log.info("Set-up Redis cache for whoiscompany")


@router.get(
    "/transmute/{email}", response_model=Person, response_model_exclude_none=True
)
def transmute_one(email: EmailStr, name: str) -> Person:
    # first, let's find him on LinkedIn
    miner = LinkedInSearch(search_api_params)
    person = miner.search(name=name, email=email)

    if not person:
        person = Person(email=email, name=name)

    # then if there is no image, let's gravatar it
    if not person.image:
        image = gravatar(person.email)
        if image:
            person.image = image

    snm = SocialNetworkMiner(person)

    # fuzzy identifier miner
    snm.identifier()

    # if there is an image, let's vision mine it
    # it will ads other social network URLs
    if person.image:
        snm.image()

    # otherwise, the domain will give us the org
    # except for public email providers
    if not person.worksFor:
        domain = email.split("@")[1]
        if domain not in settings.public_email_providers:
            company = cache.get(domain)
            if not company:
                company = get_company(domain)
                # redis refuse to store None so we'll use a void string instead
                # we won't check for this domain again for some time
                cache.set(domain, company or "", ex=settings.cache_expiration)
            if company:
                person.worksFor = company

    return person


al = Alchemist()


@al.register(element="email")
async def miner_gravatar(p: Person):
    status = False
    avatar = gravatar(p.email)
    if avatar:
        status = True
    return status, {"image": avatar}


class WebSocketManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.remove(websocket)

    async def message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.connections:
            await connection.send_text(message)


wss_manager = WebSocketManager()


@router.websocket("/transmute/{user_id}/websocket")
async def websocket_endpoint(
    websocket: WebSocket, user_id: int, token: str = Depends(websocket_api_key)
):
    await wss_manager.connect(websocket)
    transmuted_count = 0
    log.debug(f"Websocket connected: {websocket}")
    try:
        while transmuted_count < settings.persons_bulk_max:
            # Wait for any message from the client
            person_data = await websocket.receive_json()
            if (
                type(person_data) is dict
                and "email" in person_data
                and "name" in person_data
            ):
                person = Person(**person_data)
            else:
                log.debug(f"invalid data: {person_data} - {type(person_data)}")
                raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA)
            # Send message to the client
            mining_status, person = await al.transmute_person(person)
            if not mining_status:
                continue
            else:
                transmuted_count += 1
            await websocket.send_text(person.json())
        # reached bulk limit
        log.debug(
            f"limit reached: {transmuted_count}/{settings.persons_bulk_max}")
        raise WebSocketException(code=status.WS_1009_MESSAGE_TOO_BIG)
    except WebSocketDisconnect:
        log.debug(f"Websocket disconnected: {websocket}")
        wss_manager.disconnect(websocket)
