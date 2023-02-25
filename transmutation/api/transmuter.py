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
from fastapi import APIRouter

# Schema.org Person
from pydantic_schemaorg.Person import Person

# types
from pydantic import EmailStr

# logger
from loguru import logger as log

# service
from ..miners.linkedin import LinkedInSearch
from ..miners.whoiscompany import get_company
from ..miners.gravatar import gravatar
from ..miners.vision import SocialNetworkMiner


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


# @router.post("/transmute", response_model=list[Person], response_model_exclude_none=True)
# def transmute_many(self):

# @router.patch("/transmute")
# def transmute_bulk(self):

# @router.get("/transmute/status")
# def status(self):
